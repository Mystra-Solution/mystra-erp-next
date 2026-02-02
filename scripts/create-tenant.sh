#!/usr/bin/env bash
#
# Create a new ERPNext tenant (new site + new MariaDB database, same Redis).
# Sets Administrator password, creates API keys, and returns credentials.
#
# In this setup:
#   - One MariaDB server: each tenant = new database on the same server (created by bench new-site).
#   - One Redis: shared by all tenants (redis-cache, redis-queue).
#   - One bench: multiple sites (one site per tenant).
#
# Usage (from host, with Docker Compose):
#   export COMPOSE_PROJECT_NAME=frappe
#   export COMPOSE_FILE=compose.custom.yaml
#   export DB_PASSWORD='your-db-root-password'
#   ./scripts/create-tenant.sh tenant2.example.com 'AdminPass123!'
#
# Or with explicit args:
#   ./scripts/create-tenant.sh <site_name> <admin_password> [db_root_password] [--json]
#
#   --json   Output credentials as JSON to stdout (for Admin API)
#
# Usage (inside backend container):
#   ./scripts/create-tenant.sh tenant2.example.com 'AdminPass123!'
#   (DB_PASSWORD from env or pass as third arg)
#
set -euo pipefail

SITE_NAME=""
ADMIN_PASSWORD=""
DB_PASSWORD_ARG=""
JSON_OUTPUT=""
ENV_DB_PASSWORD="${DB_PASSWORD:-}"

# Parse args: site_name, admin_password, [db_root_password], [--json]
for arg in "$@"; do
  if [[ "$arg" == "--json" ]]; then
    JSON_OUTPUT="1"
  elif [[ -z "$SITE_NAME" ]]; then
    SITE_NAME="$arg"
  elif [[ -n "$SITE_NAME" && -z "$ADMIN_PASSWORD" ]]; then
    ADMIN_PASSWORD="$arg"
  elif [[ -n "$ADMIN_PASSWORD" && -z "$DB_PASSWORD_ARG" && "$arg" != --* ]]; then
    DB_PASSWORD_ARG="$arg"
  fi
done
DB_PASSWORD="${DB_PASSWORD_ARG:-$ENV_DB_PASSWORD}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-frappe}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.custom.yaml}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose -p $COMPOSE_PROJECT_NAME -f $COMPOSE_FILE}"

usage() {
  echo "Usage: $0 <site_name> <admin_password> [db_root_password] [--json]"
  echo ""
  echo "  site_name       Tenant site name (e.g. tenant2.example.com or tenant2.kynolabs.dev)"
  echo "  admin_password  Administrator login password (also used as default password)"
  echo "  db_root_password Optional. MariaDB root password (default: \$DB_PASSWORD)"
  echo "  --json          Output credentials as JSON (for Admin API)"
  echo ""
  echo "Creates: new bench site + new MariaDB database for this tenant. Redis is shared."
  echo "Returns: credentials (login + API key/secret) for the tenant."
  echo "Env: DB_PASSWORD, COMPOSE_PROJECT_NAME, COMPOSE_FILE, COMPOSE_CMD"
  exit 1
}

if [[ -z "$SITE_NAME" || -z "$ADMIN_PASSWORD" ]]; then
  usage
fi

if [[ -z "$DB_PASSWORD" ]]; then
  echo "ERROR: DB root password required. Set DB_PASSWORD or pass as third argument." >&2
  usage
fi

run_bench() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    $COMPOSE_CMD exec -T backend bench "$@"
  else
    bench "$@"
  fi
}

# When --json: redirect all progress to stderr so only JSON goes to stdout
if [[ -n "$JSON_OUTPUT" ]]; then
  exec 3>&1
  exec 1>&2
fi

echo "[$(date +%FT%T)] Creating tenant site: $SITE_NAME"
echo "[$(date +%FT%T)] New MariaDB database will be created on the same server; Redis is shared."

run_bench new-site "$SITE_NAME" \
  --mariadb-user-host-login-scope='172.%.%.%' \
  --db-root-password "$DB_PASSWORD" \
  --admin-password "$ADMIN_PASSWORD"

echo "[$(date +%FT%T)] Installing ERPNext on site: $SITE_NAME"
run_bench --site "$SITE_NAME" install-app erpnext

echo "[$(date +%FT%T)] Generating API key for Administrator"
GEN_SCRIPT='
import json
try:
    r = frappe.call("frappe.core.doctype.user.user.generate_keys", user="Administrator")
    print(json.dumps(r))
except Exception as e:
    print(json.dumps({"error": str(e)}), file=__import__("sys").stderr)
    raise
'
API_RESULT=$(run_bench --site "$SITE_NAME" execute "$GEN_SCRIPT" 2>/dev/null | tail -1)

if [[ -z "$API_RESULT" || "$API_RESULT" == *"error"* ]]; then
  echo "[$(date +%FT%T)] WARNING: Could not generate API key. You can generate it manually in the UI: User → Administrator → Settings → API Access → Generate Keys." >&2
  API_KEY=""
  API_SECRET=""
else
  API_KEY=$(echo "$API_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('api_key',''))" 2>/dev/null || echo "")
  API_SECRET=$(echo "$API_RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('api_secret',''))" 2>/dev/null || echo "")
fi

if [[ -n "$JSON_OUTPUT" ]]; then
  exec 1>&3  # restore stdout for JSON
  # Machine-readable output for Admin API (args avoid injection)
  python3 -c "
import json, sys
s, p, k, v = (sys.argv[i] if len(sys.argv) > i else '' for i in range(1, 5))
t = 'token ' + k + ':' + v if k and v else None
print(json.dumps({'ok': True, 'site_name': s, 'credentials': {'username': 'Administrator', 'password': p, 'api_key': k, 'api_secret': v, 'token': t}}))
" "$SITE_NAME" "$ADMIN_PASSWORD" "$API_KEY" "$API_SECRET"
else
  echo ""
  echo "=============================================="
  echo "Tenant created: $SITE_NAME"
  echo "=============================================="
  echo ""
  echo "Login credentials (web UI):"
  echo "  Username: Administrator"
  echo "  Password: $ADMIN_PASSWORD"
  echo ""
  if [[ -n "$API_KEY" && -n "$API_SECRET" ]]; then
    echo "API credentials (for REST API calls):"
    echo "  API Key:    $API_KEY"
    echo "  API Secret: $API_SECRET"
    echo "  Token (use in Authorization header): token $API_KEY:$API_SECRET"
    echo ""
    echo "  Example: curl -H \"Authorization: token $API_KEY:$API_SECRET\" http://<host>:<port>/api/method/frappe.auth.get_logged_user"
  else
    echo "API credentials: Generate manually in User → Administrator → Settings → API Access → Generate Keys"
  fi
  echo ""
  echo "To serve this tenant: set FRAPPE_SITE_NAME_HEADER=$SITE_NAME for the frontend (or use multi-tenant by port)."
  echo "=============================================="
fi
