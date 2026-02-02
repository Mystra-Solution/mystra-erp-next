# Admin API — Tenant Management

Secured HTTP API for creating and deleting ERPNext tenants. Intended to be called from the **Mystra admin service**.

## Setup

1. **Add the admin-api override** when generating your compose file:

   ```bash
   docker compose -f compose.yaml -f overrides/compose.mariadb.yaml -f overrides/compose.redis.yaml \
     -f overrides/compose.admin-api.yaml -f overrides/compose.noproxy.yaml \
     --env-file custom.env config > compose.custom.yaml
   ```

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
  "admin_password": "SecurePass123!"
}
```

**Success (201):**

```json
{
  "ok": true,
  "site_name": "tenant3.example.com",
  "credentials": {
    "username": "Administrator",
    "password": "SecurePass123!",
    "api_key": "xxxxxxxxxxxx",
    "api_secret": "xxxxxxxxxxxx",
    "token": "token api_key:api_secret"
  }
}
```

**Error (400):**

```json
{"ok": false, "error": "site_name and admin_password required"}
```

---

### Delete tenant

```
DELETE /admin/tenant/<site_name>
X-Admin-API-Key: <your-key>
```

**Query params:**

- `no_backup` — `true` (default) to skip backup before deletion; `false` to create a backup

**Example:**

```
DELETE /admin/tenant/tenant3.example.com
DELETE /admin/tenant/tenant3.example.com?no_backup=false
```

**Success (200):**

```json
{
  "ok": true,
  "site_name": "tenant3.example.com",
  "message": "Tenant deleted"
}
```

**Error (400):**

```json
{"ok": false, "error": "drop-site failed: ..."}
```

---

## Example: Mystra admin service

**Create tenant:**

```bash
curl -X POST "http://<erp-host>:9090/admin/tenant" \
  -H "X-Admin-API-Key: $ADMIN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"site_name": "acme.example.com", "admin_password": "AdminPass123!"}'
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
