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
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

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


def create_tenant(site_name: str, admin_password: str) -> dict:
    """Create a new tenant by running create-tenant.sh. Returns credentials or error."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$", site_name):
        return {"ok": False, "error": "Invalid site name"}

    script_path = os.path.join(BENCH_PATH, "create-tenant.sh")
    if not os.path.isfile(script_path):
        return {"ok": False, "error": "create-tenant.sh not found (mount scripts in compose)"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        out_path = f.name

    try:
        r = subprocess.run(
            ["bash", script_path, site_name, admin_password, "--output", out_path],
            cwd=BENCH_PATH,
            capture_output=True,
            text=True,
            env={**os.environ, "DB_PASSWORD": DB_PASSWORD},
        )

        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            if err:
                sys.stderr.write(f"[admin-api] create-tenant failed:\n{err}\n")
            # Never expose verbose progress in API response; cap at 300 chars
            skip = ("[=", "Updating DocTypes", "Updating customizations", "Updating Dashboard", "Installing ")
            lines = [l for l in err.split("\n") if l.strip() and not any(s in l for s in skip)]
            concise = "\n".join(lines[-5:]) if lines else "Tenant creation failed. Check admin-api container logs for details."
            return {"ok": False, "error": concise[:300] if len(concise) > 300 else concise}

        if not os.path.isfile(out_path):
            return {"ok": False, "error": "Credentials file not created"}
        with open(out_path) as f:
            data = json.load(f)
        if data.get("ok"):
            return data
        return {"ok": False, "error": data.get("error", "Unknown error")}
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


def delete_tenant(site_name: str, no_backup: bool = True) -> dict:
    """Delete a tenant (drop site + database)."""
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9.-]*[a-zA-Z0-9]$", site_name):
        return {"ok": False, "error": "Invalid site name"}

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

    return {"ok": True, "site_name": site_name, "message": "Tenant deleted"}


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
            result = create_tenant(site_name, admin_password)
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
            result = delete_tenant(site_name, no_backup=no_backup)
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
