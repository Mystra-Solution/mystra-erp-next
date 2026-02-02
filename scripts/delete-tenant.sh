#!/usr/bin/env bash
#
# Delete an ERPNext tenant (drop site + drop MariaDB database).
# Removes the site from bench and drops its database. Site folder is moved to archived_sites.
#
# In this setup:
#   - One MariaDB server: tenant database is dropped.
#   - Redis: shared, no tenant-specific cleanup needed.
#   - Bench: site is removed from sites/ (moved to archived_sites).
#
# Usage (from host, with Docker Compose):
#   export COMPOSE_PROJECT_NAME=frappe
#   export COMPOSE_FILE=compose.custom.yaml
#   export DB_PASSWORD='your-db-root-password'
#   ./scripts/delete-tenant.sh tenant2.example.com
#
# Or with explicit args:
#   ./scripts/delete-tenant.sh <site_name> [db_root_password] [--no-backup]
#
# Usage (inside backend container):
#   ./scripts/delete-tenant.sh tenant2.example.com
#   (DB_PASSWORD from env or pass as second arg)
#
# Options:
#   --no-backup   Skip backup before deletion (faster, use when data is disposable)
#   --force       Skip site-exists check (use when list-sites is empty or unreliable)
#
set -euo pipefail

SITE_NAME=""
DB_PASSWORD_ARG=""
NO_BACKUP=""
SKIP_CHECK=""

# Parse args: site_name, optional db_password, optional --no-backup, optional --force
for arg in "$@"; do
  if [[ "$arg" == "--no-backup" ]]; then
    NO_BACKUP="--no-backup"
  elif [[ "$arg" == "--force" ]]; then
    SKIP_CHECK="1"
  elif [[ -z "$SITE_NAME" && "$arg" != --* ]]; then
    SITE_NAME="$arg"
  elif [[ -n "$SITE_NAME" && -z "$DB_PASSWORD_ARG" && "$arg" != --* ]]; then
    DB_PASSWORD_ARG="$arg"
  fi
done

DB_PASSWORD="${DB_PASSWORD_ARG:-${DB_PASSWORD:-}}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-frappe}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.custom.yaml}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose -p $COMPOSE_PROJECT_NAME -f $COMPOSE_FILE}"

usage() {
  echo "Usage: $0 <site_name> [db_root_password] [--no-backup]"
  echo ""
  echo "  site_name       Tenant site name to delete (e.g. tenant2.example.com)"
  echo "  db_root_password Optional. MariaDB root password (default: \$DB_PASSWORD)"
  echo "  --no-backup     Skip backup before deletion (faster)"
  echo "  --force         Skip site-exists check (when list-sites is empty)"
  echo ""
  echo "Removes: bench site + MariaDB database. Site folder moved to archived_sites."
  echo "Env: DB_PASSWORD, COMPOSE_PROJECT_NAME, COMPOSE_FILE, COMPOSE_CMD"
  exit 1
}

if [[ -z "$SITE_NAME" ]]; then
  usage
fi

if [[ -z "$DB_PASSWORD" ]]; then
  echo "ERROR: DB root password required. Set DB_PASSWORD or pass as second argument." >&2
  usage
fi

run_bench() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    $COMPOSE_CMD exec -T backend bench "$@"
  else
    bench "$@"
  fi
}

# Verify site exists (unless --force)
# Note: bench list-sites was removed in newer Frappe; list sites/ dirs with site_config.json
if [[ -z "$SKIP_CHECK" ]]; then
  list_sites_cmd='cd /home/frappe/frappe-bench 2>/dev/null && for d in sites/*/; do [ -f "${d}site_config.json" ] && basename "$d"; done'
  if command -v docker >/dev/null 2>&1; then
    SITES=$($COMPOSE_CMD exec -T backend sh -c "$list_sites_cmd" 2>/dev/null || true)
  else
    SITES=""
  fi
  if [[ "$SITES" != *"$SITE_NAME"* ]]; then
    echo "ERROR: Site '$SITE_NAME' not found. Available sites:" >&2
    echo "$SITES" >&2
    echo "" >&2
    echo "If the site exists, run with --force to skip this check." >&2
    exit 1
  fi
fi

echo "[$(date +%FT%T)] Deleting tenant: $SITE_NAME"
echo "[$(date +%FT%T)] Database will be dropped; site folder will be moved to archived_sites."

run_bench drop-site "$SITE_NAME" \
  --db-root-password "$DB_PASSWORD" \
  --force \
  $NO_BACKUP

echo ""
echo "=============================================="
echo "Tenant deleted: $SITE_NAME"
echo "=============================================="
echo "  - MariaDB database dropped"
echo "  - Site folder moved to archived_sites/"
echo "  - Redis: no tenant-specific data (shared)"
echo ""
echo "If this tenant had a dedicated frontend port, remove it from compose overrides."
echo "=============================================="
