#!/usr/bin/env python3
"""
Tenant management utilities for ERPNext.
Can be imported by admin_api.py or used as a module.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime

# Optional: for dynamic frontend creation
try:
    import docker
except ImportError:
    docker = None


def run_bench(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run bench command. Returns CompletedProcess. When running as root, runs bench as frappe user."""
    bench_cmd = ["bench"] + list(args)
    # When process is root (for Docker socket access), run bench as frappe to avoid "do not run as root" warning
    if os.geteuid() == 0:
        cmd = ["runuser", "-u", "frappe", "--"] + bench_cmd
    else:
        cmd = bench_cmd
    return subprocess.run(
        cmd,
        cwd=cwd or "/home/frappe/frappe-bench",
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def _sanitize_service_name(site_name: str) -> str:
    """Convert site name to valid Docker compose service name (lowercase, alphanumeric, hyphens)."""
    return re.sub(r"[^a-z0-9-]", "-", site_name.lower()).strip("-") or "tenant"


def create_frontend_for_tenant(
    site_name: str,
    port: int,
    image: str | None = None,
    network: str | None = None,
    sites_volume: str | None = None,
    backend_host: str = "backend:8000",
    websocket_host: str = "websocket:9000",
    verbose: bool = False,
) -> dict:
    """
    Create an nginx frontend container for a tenant.

    Args:
        site_name: Tenant site name (e.g. tenant.example.com)
        port: Host port to publish (e.g. 8085)
        image: Docker image (default from env FRONTEND_IMAGE or frappe/erpnext:version-15)
        network: Docker network name (default from env DOCKER_NETWORK or frappe_docker_default)
        sites_volume: Sites volume name (default from env DOCKER_SITES_VOLUME or frappe_docker_sites)
        backend_host: Backend host:port
        websocket_host: WebSocket host:port
        verbose: If True, log progress to stderr

    Returns:
        dict with 'ok' (bool), 'container_id', 'service_name' or 'error'
    """
    log = lambda msg: sys.stderr.write(f"[{datetime.now().isoformat()}] {msg}\n") if verbose else None

    if not docker:
        return {"ok": False, "error": "Docker SDK not installed. Use admin-api image with docker package for frontend creation."}

    service_name = f"frontend-tenant-{_sanitize_service_name(site_name)}"
    image = image or os.environ.get("FRONTEND_IMAGE", "frappe/erpnext:version-15")
    network_name = network or os.environ.get("DOCKER_NETWORK", "frappe_docker_default")
    sites_volume = sites_volume or os.environ.get("DOCKER_SITES_VOLUME", "frappe_docker_sites")

    try:
        client = docker.from_env()
    except docker.errors.DockerException as e:
        log(f"ERROR: Cannot connect to Docker: {e}")
        return {"ok": False, "error": f"Cannot connect to Docker: {e}"}

    # Resolve network: try to get network from backend container first (most reliable)
    # Docker Compose prefixes container names with project name, so search by label instead
    resolved_network_name = network_name
    backend_container = None
    try:
        # Try exact name first (for manual setups)
        try:
            backend_container = client.containers.get("backend")
        except docker.errors.NotFound:
            # Search by Docker Compose label (com.docker.compose.service=backend)
            containers = client.containers.list(
                filters={"label": "com.docker.compose.service=backend"},
                all=True
            )
            if containers:
                backend_container = containers[0]
                log(f"Found backend container: {backend_container.name}")
            else:
                # Try name pattern (frappe-backend-1, mystra-erp-next-backend-1, etc.)
                all_containers = client.containers.list(all=True)
                for c in all_containers:
                    if c.name.endswith("-backend-1") or c.name == "backend":
                        backend_container = c
                        log(f"Found backend container by pattern: {backend_container.name}")
                        break
        
        if not backend_container:
            return {"ok": False, "error": "Backend container not found. Start the stack first."}
        
        if backend_container.status != "running":
            return {"ok": False, "error": f"Backend container is not running (status: {backend_container.status}). Start the stack first."}
        
        backend_networks = backend_container.attrs.get("NetworkSettings", {}).get("Networks", {})
        if backend_networks:
            resolved_network_name = list(backend_networks.keys())[0]
            log(f"Using network from backend container: {resolved_network_name}")
        else:
            log(f"WARNING: Backend has no networks, using provided network: {network_name}")
    except Exception as e:
        log(f"WARNING: Could not resolve network from backend: {e}, using name: {network_name}")

    # Verify network exists
    try:
        client.networks.get(resolved_network_name)
    except docker.errors.NotFound:
        return {"ok": False, "error": f"Network '{resolved_network_name}' not found. Check DOCKER_NETWORK env var or ensure backend is on the expected network."}

    # Check if port is already in use
    try:
        all_containers = client.containers.list(all=True)
        for container in all_containers:
            container_ports = container.attrs.get("HostConfig", {}).get("PortBindings", {})
            for container_port, host_bindings in container_ports.items():
                if host_bindings:
                    for binding in host_bindings:
                        host_port = binding.get("HostPort")
                        if host_port and int(host_port) == port:
                            container_name = container.name
                            log(f"Port {port} is already in use by container {container_name}")
                            return {
                                "ok": False,
                                "error": f"Port {port} is already in use by container '{container_name}'. Please use a different port."
                            }
    except Exception as e:
        log(f"WARNING: Could not check port availability: {e}")

    # Check if container already exists
    try:
        existing = client.containers.get(service_name)
        if existing.status == "running":
            log(f"Frontend {service_name} already running")
            return {"ok": True, "container_id": existing.id, "service_name": service_name}
        existing.remove(force=True)
    except docker.errors.NotFound:
        pass

    env = {
        "BACKEND": backend_host,
        "SOCKETIO": websocket_host,
        "FRAPPE_SITE_NAME_HEADER": site_name,
        "CLIENT_MAX_BODY_SIZE": "50m",
        "PROXY_READ_TIMEOUT": "120",
        "UPSTREAM_REAL_IP_ADDRESS": "127.0.0.1",
        "UPSTREAM_REAL_IP_HEADER": "X-Forwarded-For",
        "UPSTREAM_REAL_IP_RECURSIVE": "off",
    }

    try:
        container = client.containers.run(
            image=image,
            name=service_name,
            detach=True,
            restart_policy={"Name": "unless-stopped"},
            ports={"8080/tcp": port},
            environment=env,
            volumes={sites_volume: {"bind": "/home/frappe/frappe-bench/sites", "mode": "rw"}},
            network=resolved_network_name,
            command="nginx-entrypoint.sh",
        )
        log(f"Created frontend container {service_name} on port {port}")
        return {"ok": True, "container_id": container.id, "service_name": service_name}
    except docker.errors.ImageNotFound:
        return {"ok": False, "error": f"Image not found: {image}"}
    except docker.errors.APIError as e:
        log(f"ERROR: Docker API error: {e}")
        return {"ok": False, "error": str(e)}


def remove_frontend_for_tenant(site_name: str, verbose: bool = False) -> dict:
    """
    Remove the nginx frontend container for a tenant.

    Returns:
        dict with 'ok' (bool), 'removed' (bool) or 'error'
    """
    log = lambda msg: sys.stderr.write(f"[{datetime.now().isoformat()}] {msg}\n") if verbose else None

    if not docker:
        return {"ok": False, "error": "Docker SDK not installed."}

    service_name = f"frontend-tenant-{_sanitize_service_name(site_name)}"

    try:
        client = docker.from_env()
        container = client.containers.get(service_name)
        container.stop(timeout=10)
        container.remove()
        log(f"Removed frontend container {service_name}")
        return {"ok": True, "removed": True}
    except docker.errors.NotFound:
        log(f"Frontend {service_name} not found (already removed?)")
        return {"ok": True, "removed": False}
    except docker.errors.DockerException as e:
        log(f"ERROR: {e}")
        return {"ok": False, "error": str(e)}


def create_tenant(
    site_name: str,
    admin_password: str,
    db_password: str,
    bench_path: str = "/home/frappe/frappe-bench",
    verbose: bool = False,
    port: int | None = None,
    create_frontend: bool = False,
) -> dict:
    """
    Create a new ERPNext tenant (site + database + ERPNext install + API keys).

    Args:
        site_name: Tenant site name (e.g. tenant.example.com)
        admin_password: Administrator password
        db_password: MariaDB root password
        bench_path: Path to bench directory
        verbose: If True, log progress to stderr
        port: Optional port for frontend (required if create_frontend=True)
        create_frontend: If True and port is set, create nginx frontend container

    Returns:
        dict with 'ok' (bool), 'site_name', 'port', 'credentials' (or 'error' on failure)
    """
    log = lambda msg: sys.stderr.write(f"[{datetime.now().isoformat()}] {msg}\n") if verbose else None

    log(f"Creating tenant site: {site_name}")
    log("New MariaDB database will be created on the same server; Redis is shared.")

    # bench new-site
    r = run_bench(
        "new-site",
        site_name,
        "--mariadb-user-host-login-scope=172.%.%.%",
        f"--db-root-password={db_password}",
        f"--admin-password={admin_password}",
        cwd=bench_path,
    )
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "new-site failed").strip()
        log(f"ERROR: new-site failed: {err}")
        return {"ok": False, "error": err}

    log(f"Installing ERPNext on site: {site_name}")
    r = run_bench("--site", site_name, "install-app", "erpnext", cwd=bench_path)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "install-app failed").strip()
        log(f"ERROR: install-app failed: {err}")
        return {"ok": False, "error": err}

    log("Generating API key for Administrator")
    debug = lambda msg: sys.stderr.write(f"[tenant_utils DEBUG] {msg}\n")

    out_file = f"/tmp/api_keys_{uuid.uuid4().hex}.json"
    debug(f"API key temp file: {out_file}")

    gen_script = f'''
import json
out_file = "{out_file}"
try:
    r = frappe.call("frappe.core.doctype.user.user.generate_keys", user="Administrator")
    with open(out_file, "w") as f:
        json.dump(r, f)
except Exception as e:
    with open(out_file, "w") as f:
        json.dump({{"error": str(e)}}, f)
    raise
'''
    r = run_bench("--site", site_name, "execute", gen_script, cwd=bench_path)
    debug(f"bench execute returncode={r.returncode}")
    debug(f"bench execute stdout (last 500 chars): {repr((r.stdout or '')[-500:])}")
    debug(f"bench execute stderr (last 500 chars): {repr((r.stderr or '')[-500:])}")

    api_key = ""
    api_secret = ""
    try:
        file_exists = os.path.isfile(out_file)
        debug(f"Temp file exists: {file_exists}")
        if r.returncode == 0 and file_exists:
            with open(out_file) as f:
                raw = f.read()
            debug(f"Temp file content (first 200 chars): {raw[:200]!r}")
            d = json.loads(raw)
            api_key = d.get("api_key", "")
            api_secret = d.get("api_secret", "")
            debug(f"Parsed api_key present: {bool(api_key)}, api_secret present: {bool(api_secret)}")
    except json.JSONDecodeError as e:
        debug(f"JSONDecodeError: {e}")
    except OSError as e:
        debug(f"OSError reading file: {e}")
    finally:
        try:
            os.unlink(out_file)
            debug("Temp file removed")
        except OSError as e:
            debug(f"Could not remove temp file: {e}")

    if not api_key or not api_secret:
        debug("API keys empty - generate_keys may have failed or returned different format")
        log("WARNING: Could not generate API key. User can generate manually in UI.")

    # Resolve port: use provided port, else from env
    resolved_port = port if port is not None else resolve_tenant_port(site_name)

    # Create nginx frontend if requested
    frontend_result = None
    if create_frontend and resolved_port:
        frontend_result = create_frontend_for_tenant(site_name, resolved_port, verbose=verbose)
        if not frontend_result.get("ok"):
            return {
                "ok": False,
                "error": f"Tenant created but frontend failed: {frontend_result.get('error', 'Unknown error')}",
                "site_name": site_name,
                "port": resolved_port,
            }

    return {
        "ok": True,
        "site_name": site_name,
        "port": resolved_port,
        "frontend_created": frontend_result.get("ok", False) if frontend_result else False,
        "credentials": {
            "username": "Administrator",
            "password": admin_password,
            "api_key": api_key,
            "api_secret": api_secret,
            "token": f"token {api_key}:{api_secret}" if api_key and api_secret else None,
        },
    }


def resolve_tenant_port(site_name: str) -> int:
    """Resolve HTTP port for tenant from env (FRAPPE_SITE_NAME_HEADER, TENANT2_SITE_NAME, etc.)."""
    def _parse_port(val: str, default: int) -> int:
        try:
            return int(val) if val and str(val).strip() else default
        except (ValueError, TypeError):
            return default

    default_port = _parse_port(os.environ.get("HTTP_PUBLISH_PORT", ""), 8080)
    if site_name == os.environ.get("FRAPPE_SITE_NAME_HEADER", ""):
        return default_port
    if site_name == os.environ.get("TENANT2_SITE_NAME", ""):
        return _parse_port(os.environ.get("TENANT2_HTTP_PORT", ""), 8081)
    if site_name == os.environ.get("TENANT3_SITE_NAME", ""):
        return _parse_port(os.environ.get("TENANT3_HTTP_PORT", ""), 8082)
    # TENANT_PORTS env: "tenant4.com:8083,tenant5.com:8084,tenant6.com:8085" for extensibility
    mapping = os.environ.get("TENANT_PORTS", "")
    for pair in mapping.split(","):
        pair = pair.strip()
        if ":" in pair:
            s, p = pair.rsplit(":", 1)
            if s.strip() == site_name:
                port = _parse_port(p.strip(), default_port)
                if port:
                    return port
    return default_port


if __name__ == "__main__":
    # CLI usage: python tenant_utils.py <site_name> <admin_password> [db_password]
    if len(sys.argv) < 3:
        print("Usage: python tenant_utils.py <site_name> <admin_password> [db_password]", file=sys.stderr)
        sys.exit(1)
    site_name = sys.argv[1]
    admin_password = sys.argv[2]
    db_password = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("DB_PASSWORD", "")
    if not db_password:
        print("ERROR: DB_PASSWORD required", file=sys.stderr)
        sys.exit(1)
    result = create_tenant(site_name, admin_password, db_password, verbose=True)
    if result.get("ok"):
        print(json.dumps(result, indent=2))
    else:
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        sys.exit(1)
