# Admin API — Tenant Management

Secured HTTP API for creating and deleting ERPNext tenants. Intended to be called from the **Mystra admin service**.

## Setup

1. **Add the admin-api override** when generating your compose file:

   ```bash
   docker compose -f compose.yaml -f overrides/compose.mariadb.yaml -f overrides/compose.redis.yaml \
     -f overrides/compose.admin-api.yaml -f overrides/compose.noproxy.yaml \
     --env-file custom.env config > compose.custom.yaml
   ```

   **On Mac (Apple Silicon):** add `-f overrides/compose.mac-arm64.yaml` to avoid platform errors.

2. **Set `ADMIN_API_KEY`** in `custom.env` (required):

   ```
   ADMIN_API_KEY=your-secure-random-key-here
   ```

   Generate a strong key, e.g.:

   ```bash
   openssl rand -hex 32
   ```

3. **Restart the stack** to start the admin-api service:

   ```bash
   docker compose -p frappe -f compose.custom.yaml up -d
   ```

The admin API listens on port **9090** by default (configurable via `ADMIN_API_PORT`).

---

## Authentication

All endpoints (except health) require authentication via one of:

- **Header:** `X-Admin-API-Key: <your-key>`
- **Header:** `Authorization: Bearer <your-key>`

---

## Endpoints

### List tenants

```
GET /admin/tenant
X-Admin-API-Key: <your-key>
```

**Success (200):**

```json
{
  "ok": true,
  "tenants": ["erp.kynolabs.dev", "tenant2.example.com", "tenant3.example.com"],
  "count": 3
}
```

---

### Health check (no auth)

```
GET /health
GET /admin/health
```

**Response:** `200 OK`

```json
{"status": "ok", "service": "admin-api"}
```

---

### Create tenant

```
POST /admin/tenant
Content-Type: application/json
X-Admin-API-Key: <your-key>

{
  "site_name": "tenant3.example.com",
  "admin_password": "SecurePass123!",
  "port": 8085,
  "create_frontend": true
}
```

**Body fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `site_name` | Yes | Tenant site name (e.g. tenant3.example.com) |
| `admin_password` | Yes | Administrator password |
| `port` | No | Host port for the tenant. Required when `create_frontend` is true. |
| `create_frontend` | No | If `true`, create an nginx frontend container for this tenant on the given port. Requires Docker socket and docker package in admin-api image. |

**Success (201):**

```json
{
  "ok": true,
  "site_name": "tenant3.example.com",
  "port": 8085,
  "frontend_created": true,
  "credentials": {
    "username": "Administrator",
    "password": "SecurePass123!",
    "api_key": "xxxxxxxxxxxx",
    "api_secret": "xxxxxxxxxxxx",
    "token": "token api_key:api_secret"
  }
}
```

- `port`: Resolved from request body, or from env (`FRAPPE_SITE_NAME_HEADER` → 8080, `TENANT2_SITE_NAME` → 8081, etc., or `TENANT_PORTS`).
- `frontend_created`: `true` when an nginx frontend container was created for this tenant.

**Error (400):**

```json
{"ok": false, "error": "site_name and admin_password required"}
{"ok": false, "error": "port required and must be 1-65535 when create_frontend is true"}
```

---

### Frontend creation (create_frontend=true)

To create an nginx frontend for each tenant automatically:

1. **The admin-api override builds the admin-api image** with the Docker SDK. Ensure `ADMIN_API_BASE_IMAGE` matches your main app image:
   - Using custom build: `ADMIN_API_BASE_IMAGE=custom:15` in `custom.env`
   - Using default: `ADMIN_API_BASE_IMAGE` can be omitted (defaults to `frappe/erpnext:version-15`)

2. **Regenerate compose and build** the admin-api service:
   ```bash
   docker compose -f compose.custom.yaml build admin-api
   docker compose -f compose.custom.yaml up -d --force-recreate admin-api
   ```

3. **Docker socket** is mounted by default in `compose.admin-api.yaml` for frontend creation.

4. **Env vars** (optional): `FRONTEND_IMAGE`, `DOCKER_NETWORK`, `DOCKER_SITES_VOLUME` — defaults work with the standard compose setup.

---

### Delete tenant

```
DELETE /admin/tenant/<site_name>
X-Admin-API-Key: <your-key>
```

**Query params:**

- `no_backup` — `true` (default) to skip backup before deletion; `false` to create a backup
- `remove_frontend` — `true` (default) to stop and remove the tenant's nginx frontend container; `false` to keep it

**Example:**

```
DELETE /admin/tenant/tenant3.example.com
DELETE /admin/tenant/tenant3.example.com?no_backup=false
DELETE /admin/tenant/tenant3.example.com?remove_frontend=false
```

**Success (200):**

```json
{
  "ok": true,
  "site_name": "tenant3.example.com",
  "message": "Tenant deleted",
  "frontend_removed": true
}
```

**Error (400):**

```json
{"ok": false, "error": "drop-site failed: ..."}
```

---

## Example: Mystra admin service

**List tenants:**

```bash
curl -s "http://<erp-host>:9090/admin/tenant" \
  -H "X-Admin-API-Key: $ADMIN_API_KEY"
```

**Create tenant (with frontend on port 8085):**

```bash
curl -X POST "http://<erp-host>:9090/admin/tenant" \
  -H "X-Admin-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"site_name": "acme.example.com", "admin_password": "AdminPass123!", "port": 8085, "create_frontend": true}'
```

**Delete tenant:**

```bash
curl -X DELETE "http://<erp-host>:9090/admin/tenant/acme.example.com" \
  -H "X-Admin-API-Key: $ADMIN_API_KEY"
```

---

## Security

- **Use HTTPS** in production. Put the admin API behind a reverse proxy (nginx, Caddy, Traefik) with TLS.
- **Restrict access** — firewall port 9090 to only the Mystra admin service IP(s).
- **Rotate `ADMIN_API_KEY`** periodically and update it in both `custom.env` and the Mystra admin service.
- **Do not expose** the admin API publicly without proper authentication and TLS.

---

## Firewall

To restrict access to the admin API (e.g. only from Mystra admin):

```bash
# Allow only from Mystra admin IP
sudo ufw allow from <mystra-admin-ip> to any port 9090
sudo ufw deny 9090
sudo ufw reload
```
