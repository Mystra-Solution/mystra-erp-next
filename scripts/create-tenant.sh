#!/usr/bin/env bash
#
# Create a new ERPNext tenant (new site + new MariaDB database, same Redis).
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
#   ./scripts/create-tenant.sh <site_name> <admin_password> [db_root_password]
#
# Usage (inside backend container):
#   ./scripts/create-tenant.sh tenant2.example.com 'AdminPass123!'
#   (DB_PASSWORD from env or pass as third arg)
#
set -euo pipefail

SITE_NAME="${1:-}"
ADMIN_PASSWORD="${2:-}"
DB_PASSWORD="${3:-${DB_PASSWORD:-}}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-frappe}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.custom.yaml}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose -p $COMPOSE_PROJECT_NAME -f $COMPOSE_FILE}"

usage() {
  echo "Usage: $0 <site_name> <admin_password> [db_root_password]"
  echo ""
  echo "  site_name       Tenant site name (e.g. tenant2.example.com or tenant2.kynolabs.dev)"
  echo "  admin_password  Administrator login password for this tenant"
  echo "  db_root_password Optional. MariaDB root password (default: \$DB_PASSWORD)"
  echo ""
  echo "Creates: new bench site + new MariaDB database for this tenant. Redis is shared."
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

echo "[$(date +%FT%T)] Creating tenant site: $SITE_NAME"
echo "[$(date +%FT%T)] New MariaDB database will be created on the same server; Redis is shared."

run_bench new-site "$SITE_NAME" \
  --mariadb-user-host-login-scope='172.%.%.%' \
  --db-root-password "$DB_PASSWORD" \
  --admin-password "$ADMIN_PASSWORD"

echo "[$(date +%FT%T)] Installing ERPNext on site: $SITE_NAME"
run_bench --site "$SITE_NAME" install-app erpnext

echo "[$(date +%FT%T)] Tenant created: $SITE_NAME"
echo "  - Site name: $SITE_NAME"
echo "  - Login: Administrator / (your admin password)"
echo "  - To serve this tenant by domain: set FRAPPE_SITE_NAME_HEADER to $SITE_NAME for the frontend that will serve it (or use multi-tenant nginx/Traefik by host)."
