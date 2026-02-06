#!/usr/bin/env python3
"""
Secured Admin API for tenant management.
Called by Mystra admin service to create/delete ERPNext tenants.

Endpoints:
  GET    /admin/tenant     - List all tenants
  POST   /admin/tenant     - Create tenant, returns credentials
  DELETE /admin/tenant/:id  - Delete tenant

Authentication: X-Admin-API-Key header or Authorization: Bearer <key>
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

# Import tenant utilities
sys.path.insert(0, os.path.dirname(__file__))
try:
    from tenant_utils import (
        create_tenant as create_tenant_py,
        resolve_tenant_port,
        create_frontend_for_tenant,
        remove_frontend_for_tenant,
    )
except ImportError:
    create_tenant_py = None
    resolve_tenant_port = None
    create_frontend_for_tenant = None
    remove_frontend_for_tenant = None


def _ensure_port(result: dict, site_name: str) -> None:
    """Ensure result has 'port' key. Mutates result in place."""
    if result.get("ok") and "port" not in result:
        result["port"] = resolve_tenant_port(site_name) if resolve_tenant_port else 8080

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
BENCH_PATH = "/home/frappe/frappe-bench"
HOST = os.environ.get("ADMIN_API_HOST", "0.0.0.0")
PORT = int(os.environ.get("ADMIN_API_PORT", "9090"))


def run_bench(*args: str) -> subprocess.CompletedProcess:
    """Run bench command in the bench directory."""
    cmd = ["bench"] + list(args)
    return subprocess.run(
        cmd,
        cwd=BENCH_PATH,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def require_auth(handler: BaseHTTPRequestHandler) -> bool:
    """Validate admin API key. Returns True if authorized."""
    if not ADMIN_API_KEY:
        return False
    key = handler.headers.get("X-Admin-API-Key") or ""
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        key = key or auth[7:]
    return key == ADMIN_API_KEY


def json_response(handler: BaseHTTPRequestHandler, status: int, data: dict) -> None:
    """Send JSON response."""
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.end_headers()
    handler.wfile.write(json.dumps(data).encode())


def read_json_body(handler: BaseHTTPRequestHandler) -> dict | None:
    """Read and parse JSON body from POST request."""
    content_length = int(handler.headers.get("Content-Length", 0))
    if content_length <= 0:
        return None
    body = handler.rfile.read(content_length).decode("utf-8", errors="replace")
    try:
        return json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        return None


def list_tenants() -> dict:
    """List all tenants (sites with site_config.json)."""
    sites_dir = os.path.join(BENCH_PATH, "sites")
    tenants = []
    try:
        for name in sorted(os.listdir(sites_dir)):
            if name.startswith(".") or name in ("assets", "common_site_config.json", "apps.txt", "currentsite.txt"):
                continue
            path = os.path.join(sites_dir, name)
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "site_config.json")):
                tenants.append(name)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "tenants": tenants, "count": len(tenants)}


def create_tenant(
    site_name: str,
    admin_password: str,
    port: int | None = None,
    create_frontend: bool = False,
) -> dict:
    """Create a new tenant. Uses Python function if available, falls back to shell script."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$", site_name):
        return {"ok": False, "error": "Invalid site name"}

    if not DB_PASSWORD:
        return {"ok": False, "error": "DB_PASSWORD not configured"}

    if create_frontend and (port is None or port < 1 or port > 65535):
        return {"ok": False, "error": "port required and must be 1-65535 when create_frontend is true"}

    if create_frontend and not create_tenant_py:
        return {"ok": False, "error": "create_frontend requires tenant_utils (Python path)"}

    # Use Python function if available (cleaner, no subprocess overhead)
    if create_tenant_py:
        try:
            result = create_tenant_py(
                site_name,
                admin_password,
                DB_PASSWORD,
                BENCH_PATH,
                verbose=False,
                port=port,
                create_frontend=create_frontend,
            )
            _ensure_port(result, site_name)
            return result
        except Exception as e:
            sys.stderr.write(f"[admin-api] create_tenant_py exception: {e}\n")
            return {"ok": False, "error": f"Tenant creation failed: {str(e)}"}

    # Fallback to shell script (for backward compatibility)
    script_path = os.path.join(BENCH_PATH, "create-tenant.sh")
    if not os.path.isfile(script_path):
        return {"ok": False, "error": "create-tenant.sh not found (mount scripts in compose)"}

    r = subprocess.run(
        ["bash", script_path, site_name, admin_password],
        cwd=BENCH_PATH,
        capture_output=True,
        text=True,
        env={**os.environ, "DB_PASSWORD": DB_PASSWORD},
    )

    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        if err:
            sys.stderr.write(f"[admin-api] create-tenant.sh failed:\n{err}\n")
        skip = ("[=", "Updating DocTypes", "Updating customizations", "Updating Dashboard", "Installing ")
        lines = [l for l in err.split("\n") if l.strip() and not any(s in l for s in skip)]
        concise = "\n".join(lines[-5:]) if lines else "Tenant creation failed. Check admin-api container logs for details."
        return {"ok": False, "error": concise[:300] if len(concise) > 300 else concise}

    # Parse JSON from last line of stdout
    for line in reversed((r.stdout or "").strip().split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                data = json.loads(line)
                if data.get("ok"):
                    _ensure_port(data, site_name)
                    return data
                return {"ok": False, "error": data.get("error", "Unknown error")}
            except json.JSONDecodeError:
                continue
    return {"ok": False, "error": "Could not parse credentials from create-tenant.sh"}


def delete_tenant(site_name: str, no_backup: bool = True, remove_frontend: bool = True) -> dict:
    """Delete a tenant (drop site + database, optionally remove frontend)."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$", site_name):
        return {"ok": False, "error": "Invalid site name"}

    # Remove frontend container first (if any)
    frontend_removed = False
    if remove_frontend and remove_frontend_for_tenant:
        fr = remove_frontend_for_tenant(site_name, verbose=False)
        frontend_removed = fr.get("removed", False)

    args = [
        "drop-site",
        site_name,
        f"--db-root-password={DB_PASSWORD}",
        "--force",
    ]
    if no_backup:
        args.append("--no-backup")

    r = run_bench(*args)
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr or r.stdout or "drop-site failed"}

    return {
        "ok": True,
        "site_name": site_name,
        "message": "Tenant deleted",
        "frontend_removed": frontend_removed,
    }


class AdminAPIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stderr.write(f"[admin-api] {format % args}\n")

    def do_GET(self):
        if self.path in ("/", "/health", "/admin/health"):
            json_response(self, 200, {"status": "ok", "service": "admin-api"})
            return
        if self.path == "/admin/tenant":
            if not require_auth(self):
                json_response(self, 401, {"error": "Unauthorized"})
                return
            result = list_tenants()
            status = 200 if result.get("ok") else 500
            json_response(self, status, result)
            return
        json_response(self, 404, {"error": "Not found"})

    def do_POST(self):
        if self.path == "/admin/tenant":
            if not require_auth(self):
                json_response(self, 401, {"error": "Unauthorized"})
                return
            body = read_json_body(self)
            if not body:
                json_response(self, 400, {"error": "JSON body required"})
                return
            site_name = (body.get("site_name") or "").strip()
            admin_password = body.get("admin_password") or ""
            if not site_name or not admin_password:
                json_response(
                    self, 400, {"error": "site_name and admin_password required"}
                )
                return
            if not DB_PASSWORD:
                json_response(self, 500, {"error": "DB_PASSWORD not configured"})
                return
            port = body.get("port")
            if port is not None:
                try:
                    port = int(port)
                except (TypeError, ValueError):
                    port = None
            create_frontend = bool(body.get("create_frontend", False))
            result = create_tenant(site_name, admin_password, port=port, create_frontend=create_frontend)
            status = 201 if result.get("ok") else 400
            json_response(self, status, result)
            return
        json_response(self, 404, {"error": "Not found"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        m = re.match(r"^/admin/tenant/(.+)$", parsed.path)
        if m:
            if not require_auth(self):
                json_response(self, 401, {"error": "Unauthorized"})
                return
            site_name = m.group(1).split("?")[0].strip()
            if not site_name:
                json_response(self, 400, {"error": "site_name required"})
                return
            if not DB_PASSWORD:
                json_response(self, 500, {"error": "DB_PASSWORD not configured"})
                return
            qs = parse_qs(parsed.query)
            no_backup = qs.get("no_backup", ["true"])[0].lower() != "false"
            remove_frontend = qs.get("remove_frontend", ["true"])[0].lower() != "false"
            result = delete_tenant(site_name, no_backup=no_backup, remove_frontend=remove_frontend)
            status = 200 if result.get("ok") else 400
            json_response(self, status, result)
            return
        json_response(self, 404, {"error": "Not found"})


def main():
    if not ADMIN_API_KEY:
        sys.stderr.write("ERROR: ADMIN_API_KEY environment variable is required\n")
        sys.exit(1)
    if not DB_PASSWORD:
        sys.stderr.write("ERROR: DB_PASSWORD environment variable is required\n")
        sys.exit(1)

    server = HTTPServer((HOST, PORT), AdminAPIHandler)
    sys.stderr.write(f"Admin API listening on {HOST}:{PORT}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
