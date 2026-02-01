# Frappe Docker — Full Setup Guide

Step-by-step guide to build and run this project with a custom image (Frappe + ERPNext) using Docker Compose.

---

## Prerequisites

- **git**
- **Docker** and **Docker Compose v2**
- (Optional) **Podman** and **podman-compose** instead of Docker

Install from official documentation. Avoid package managers when not recommended.

---

## 1. Clone the repository

```bash
git clone https://github.com/frappe/frappe_docker
cd frappe_docker
```

---

## 2. Define apps to include in the image

Create `apps.json` in the repository root. Only these apps will be available to install on sites. Example with ERPNext:

```bash
cat > apps.json << 'EOF'
[
  {
    "url": "https://github.com/frappe/erpnext",
    "branch": "version-15"
  }
]
EOF
```

You can add more apps (e.g. HRMS, Helpdesk). Skip this file only if you want a Frappe-only image (no ERPNext).

---

## 3. Encode apps.json for the build

**Linux (GNU base64):**

```bash
export APPS_JSON_BASE64=$(base64 -w 0 apps.json)
```

**macOS:**

```bash
export APPS_JSON_BASE64=$(base64 -i apps.json | tr -d '\n')
```

---

## 4. Build the Docker image

Build the layered image with your apps. This can take a long time (tens of minutes).

```bash
docker build \
  --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
  --build-arg=FRAPPE_BRANCH=version-15 \
  --build-arg=APPS_JSON_BASE64=$APPS_JSON_BASE64 \
  --tag=custom:15 \
  --file=images/layered/Containerfile .
```

**Podman:**

```bash
podman build \
  --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
  --build-arg=FRAPPE_BRANCH=version-15 \
  --build-arg=APPS_JSON_BASE64=$APPS_JSON_BASE64 \
  --tag=custom:15 \
  --file=images/layered/Containerfile .
```

Verify the image exists:

```bash
docker images custom
```

You should see `custom` with tag `15`.

---

## 5. Create environment file

```bash
cp example.env custom.env
```

Edit `custom.env`. Set at least:

| Variable | Value | Purpose |
|----------|--------|---------|
| `DB_PASSWORD` | A strong password | MariaDB root password (use when creating sites) |
| `CUSTOM_IMAGE` | `custom` | Image name used in compose |
| `CUSTOM_TAG` | `15` | Image tag |
| `PULL_POLICY` | `never` | Use only local image (do not pull) |
| `FRAPPE_SITE_NAME_HEADER` | Your site name (e.g. `erp.example.com`) | Required when accessing UI via `localhost` or `127.0.0.1` |

Example minimal addition:

```txt
CUSTOM_IMAGE=custom
CUSTOM_TAG=15
PULL_POLICY=never
DB_PASSWORD=your_secure_db_password
FRAPPE_SITE_NAME_HEADER=erp.example.com
```

For more options (external DB, Redis, HTTPS, etc.) see `docs/02-setup/04-env-variables.md`.

---

## 6. Generate the Compose file

Merge base compose and overrides into a single file:

```bash
docker compose --env-file custom.env \
  -f compose.yaml \
  -f overrides/compose.mariadb.yaml \
  -f overrides/compose.redis.yaml \
  -f overrides/compose.noproxy.yaml \
  config > compose.custom.yaml
```

This creates `compose.custom.yaml`. If you use a **Mac (e.g. Apple Silicon)** and get “image does not provide the specified platform (linux/amd64)”, remove any `platform: linux/amd64` from the services that use the custom image in `compose.custom.yaml` so they use your machine’s architecture.

---

## 7. Start the stack

```bash
docker compose -p frappe -f compose.custom.yaml up -d
```

**Podman:**

```bash
podman-compose --in-pod=1 --project-name frappe -f compose.custom.yaml up -d
```

Wait about 10 seconds for `db` to be healthy and `configurator` to finish.

Check services:

```bash
docker compose -p frappe -f compose.custom.yaml ps
```

---

## 8. Create a site and install the app

Replace `<sitename>` with your site name (e.g. `erp.example.com`). It should match `FRAPPE_SITE_NAME_HEADER` if you access the UI via localhost.

**Create site (you will be prompted for MySQL root password and Administrator password):**

```bash
docker compose -p frappe -f compose.custom.yaml exec backend bench new-site <sitename> --mariadb-user-host-login-scope='172.%.%.%'
```

**Install ERPNext on the site:**

```bash
docker compose -p frappe -f compose.custom.yaml exec backend bench --site <sitename> install-app erpnext
```

**Or create site and install app in one step:**

```bash
docker compose -p frappe -f compose.custom.yaml exec backend bench new-site <sitename> \
  --mariadb-user-host-login-scope='172.%.%.%' \
  --db-root-password YOUR_DB_PASSWORD \
  --admin-password YOUR_ADMIN_PASSWORD \
  --install-app erpnext
```

To see which apps are available in the image:

```bash
docker compose -p frappe -f compose.custom.yaml exec backend ls apps
```

---

## 9. Access the UI

- **URL:** http://localhost:8080 (or http://127.0.0.1:8080)
- **Username:** `Administrator`
- **Password:** The Administrator password you set when creating the site (no default).

**Reset Administrator password if needed:**

```bash
docker compose -p frappe -f compose.custom.yaml exec backend bench --site <sitename> set-admin-password NEW_PASSWORD
```

---

## 10. Check if APIs are working

ERPNext/Frappe exposes REST and RPC APIs on the same host and port as the UI (port **8080**). Use these to verify the backend is responding.

### No-auth health check (ping)

```bash
curl -s http://localhost:8080/api/method/ping
```

Expected: JSON with a `"message"` field (e.g. `{"message":"pong"}` or similar).

If you access via a different host (e.g. `erp.example.com`), set the Host header so the proxy routes to your site:

```bash
curl -s -H "Host: erp.kynolabs.dev" http://localhost:8080/api/method/ping
```

### Authenticated API call (token)

1. **Generate API keys** in ERPNext:
   - Log in to the UI → **User** list → open your user (e.g. Administrator) → **Settings** tab → **API Access** → **Generate Keys**. Copy the **API Key** and **API Secret**.

2. **Call an API** with the token (replace `<api_key>`, `<api_secret>`, and `<sitename>`):

```bash
curl -s -H "Authorization: token <api_key>:<api_secret>" \
  http://localhost:8080/api/method/frappe.auth.get_logged_user
```

Expected: JSON with the logged-in user (e.g. `{"message":"Administrator"}`).

3. **REST resource example** (list a DocType, e.g. Customer):

```bash
curl -s -H "Authorization: token <api_key>:<api_secret>" \
  "http://localhost:8080/api/resource/Customer?limit_page_length=5"
```

Expected: JSON with a `"data"` array (may be empty if no records).

---

## 11. Useful commands

| Action | Command |
|--------|--------|
| Stop all services | `docker compose -p frappe -f compose.custom.yaml down` |
| View logs | `docker compose -p frappe -f compose.custom.yaml logs -f` |
| Restart frontend (e.g. after env change) | `docker compose -p frappe -f compose.custom.yaml up -d --force-recreate frontend` |
| Shell in backend | `docker compose -p frappe -f compose.custom.yaml exec backend bash` |
| List sites | `docker compose -p frappe -f compose.custom.yaml exec backend bench --site all list-apps` |

---

## Troubleshooting

| Issue | What to do |
|-------|------------|
| **pull access denied for custom** | Image not built or not tagged `custom:15`. Build the image (step 4) and use `PULL_POLICY=never` in `custom.env`. |
| **image does not provide the specified platform (linux/amd64)** | You built on Mac (e.g. arm64). Remove `platform: linux/amd64` from custom-image services in `compose.custom.yaml`, or build with `--platform linux/amd64` if you need amd64. |
| **No module named 'erpnext'** | App was not in the image. Add it to `apps.json`, set `APPS_JSON_BASE64`, rebuild the image, then `down` and `up -d` again. |
| **Blank page or “site not found” in browser** | You access via `localhost` but the site has another name. Set `FRAPPE_SITE_NAME_HEADER` to your site name in `custom.env`, regenerate `compose.custom.yaml`, and run `docker compose -p frappe -f compose.custom.yaml up -d --force-recreate frontend`. |
| **WARN Using compose.yaml** | You have both `compose.yaml` and `docker-compose.yml`. Always pass `-f compose.custom.yaml` so the correct file is used. |

---

## Reference

- **Deploy on AWS Lightsail:** [docs/DEPLOY-LIGHTSAIL.md](docs/DEPLOY-LIGHTSAIL.md) (steps + `scripts/lightsail-deploy.sh`)
- **API reference (inventory, purchase, GRN):** [docs/API-REFERENCE.md](docs/API-REFERENCE.md)
- **Env variables:** `docs/02-setup/04-env-variables.md`
- **Build setup:** `docs/02-setup/02-build-setup.md`
- **Start / site setup:** `docs/02-setup/03-start-setup.md`
- **Site operations:** `docs/04-operations/01-site-operations.md`
- **Create new tenant:** `scripts/create-tenant.sh` (new site + DB on same MariaDB, same Redis) — see [site operations](docs/04-operations/01-site-operations.md#create-new-tenant-multi-tenancy)
