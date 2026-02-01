# Deploying Frappe/ERPNext on Railway

## Why "docker could not be found" happens

Railway runs your app **inside a single container**. That container does **not** have Docker or Docker Compose installed. If your start command is `docker compose ...`, you get:

```text
The executable `docker` could not be found.
```

So you **cannot** run `docker compose up` (or any `docker` command) on Railway. Railway itself builds and runs containers; your start command must run the **application process** (e.g. gunicorn, nginx), not Docker.

---

## What’s in this repo vs Railway

- **`railway.toml`** was pointing at the **bench** image and a start command that ran `docker compose`. The bench image is a CLI/dev image (bench, git, etc.) and does not include Docker. That combination caused the error.
- **Fix applied:** `railway.toml` no longer runs `docker` or `docker compose`. The start command is a placeholder so the container stays up until you switch to a proper app deploy (see below).

---

## How to deploy the full stack on Railway

Railway runs **one container per service**. Your current setup is a **multi-container** stack (backend, frontend, db, redis, queue, scheduler, websocket). To run that on Railway you have to map it to **multiple Railway services**.

### 1. Build the app image

Build the **layered** image (the one that contains Frappe + your apps and runs gunicorn), not the bench image. Do this in CI (e.g. GitHub Actions) or locally, then push to a registry Railway can pull from (e.g. Docker Hub, GitHub Container Registry, or Railway’s own registry if you use a Dockerfile that builds this image).

Example (same as in [SETUP.md](../SETUP.md)):

```bash
export APPS_JSON_BASE64=$(base64 -i apps.json | tr -d '\n')   # macOS
docker build \
  --build-arg=FRAPPE_PATH=https://github.com/frappe/frappe \
  --build-arg=FRAPPE_BRANCH=version-15 \
  --build-arg=APPS_JSON_BASE64=$APPS_JSON_BASE64 \
  --tag=your-registry/custom:15 \
  --file=images/layered/Containerfile .
docker push your-registry/custom:15
```

### 2. Database and Redis

- Use **Railway PostgreSQL** (or another Postgres/MariaDB) and configure your app for it, **or**
- Use an **external** MariaDB/Postgres and Redis (e.g. Railway Redis, Upstash, or your own).

Set `DB_HOST`, `DB_PORT`, `REDIS_CACHE`, `REDIS_QUEUE` (and any other env vars) in Railway for each service that needs them.

### 3. One Railway service per process

Create separate Railway **services** that all use the same app image (or the same Dockerfile if Railway builds it):

| Railway service | Image / build | Start command / role |
|-----------------|---------------|------------------------|
| **backend**     | Layered image | Default CMD (gunicorn) — see `images/layered/Containerfile` |
| **frontend**    | Same image    | `nginx-entrypoint.sh` (and env: BACKEND, SOCKETIO, FRAPPE_SITE_NAME_HEADER, etc.) |
| **queue-short** | Same image    | `bench worker --queue short,default` |
| **queue-long**  | Same image    | `bench worker --queue long,default,short` |
| **scheduler**   | Same image    | `bench schedule` |
| **websocket**   | Same image    | `node …/socketio.js` |

Do **not** run `docker compose` inside any of these; set each service’s start command to the single process it should run (gunicorn, nginx, worker, etc.).

### 4. Shared volume (sites)

In Docker Compose you use a shared `sites` volume. On Railway, you don’t have the same volume model. Options:

- Use a **persistent volume** (if Railway supports it) and attach it to backend, frontend, and workers so they all see the same `sites` directory, **or**
- Run **one** service that handles both web and workers (simplified but not ideal for scaling).

### 5. `railway.toml` for a single service

If you want Railway to **build** the layered image from this repo (one service at a time), point `railway.toml` at the layered Containerfile and set a valid start command for that service, for example:

```toml
[build]
builder = "dockerfile"
dockerfilePath = "images/layered/Containerfile"

[deploy]
# Example for backend only; override with env or Railway UI per service
startCommand = "/home/frappe/frappe-bench/env/bin/gunicorn --chdir=/home/frappe/frappe-bench/sites --bind=0.0.0.0:8000 ..."
```

You’d still need to build with `APPS_JSON_BASE64` (e.g. via build args in Railway if supported, or in CI and push the image).

---

## Summary

- **Error:** `docker could not be found` → your start command was running `docker`/`docker compose` inside a container that has no Docker.
- **Fix:** Never run Docker inside the container. Use a start command that runs the app (gunicorn, nginx, bench worker, etc.).
- **Full stack:** Build the layered image, use DB + Redis (Railway or external), and deploy one Railway service per process (backend, frontend, workers, scheduler, websocket), each with the correct start command and env (see [SETUP.md](../SETUP.md) and [02-setup/04-env-variables.md](02-setup/04-env-variables.md)).
