# Deploy ERPNext Docker on AWS Lightsail

This guide walks you through deploying the ERPNext Docker stack on a **single AWS Lightsail instance**. MariaDB and Redis run as **containers on the same instance** (via Docker Compose), so you do not need separate Lightsail managed databases.

---

## Architecture

- **One Lightsail instance** (Ubuntu 22.04 or **Amazon Linux 2023**)
- **Docker Compose** on the instance runs:
  - **MariaDB** (container) — database
  - **Redis** (containers: cache + queue)
  - **ERPNext app** (backend, frontend, workers, scheduler, websocket) from your custom image

All resources (SQL, Redis, app) are created and run on the Lightsail instance.

**You do not create Redis or MariaDB separately.** They are defined in the Compose overrides (`compose.mariadb.yaml`, `compose.redis.yaml`) and run as containers on the same instance. The configurator is set to use the in-container `db` and `redis-cache` / `redis-queue`; that comes from the overrides, not from `custom.env`.

**If your `custom.env` has external DB/Redis (e.g. Railway):** When you generate the Compose file with the mariadb and redis overrides (as in the steps below), the **overrides win** — the generated `compose.custom.yaml` will use `DB_HOST: db`, `REDIS_CACHE: redis-cache:6379`, etc. So the Railway (or any external) credentials in `custom.env` are **not** used for the app on Lightsail; the stack uses the DB and Redis inside Docker. You only need to set `DB_PASSWORD` in `custom.env` for the **in-container** MariaDB root password (used by the `db` service and when creating sites).

---

## Prerequisites

- **AWS account** with Lightsail access
- **AWS CLI** installed and configured (`aws configure`), with Lightsail permissions
- **SSH key** — use an existing key or let Lightsail create one (you’ll need the private key to SSH)
- **(Optional)** Domain pointed to the instance IP for production

---

## Amazon Linux 2023

**Yes, Amazon Linux 2023 is fine.** The stack runs the same way; only the OS and install steps differ:

| | Ubuntu 22.04 | Amazon Linux 2023 |
|---|--------------|-------------------|
| Default user | `ubuntu` | `ec2-user` |
| Package manager | `apt` | `dnf` |
| Docker install | Docker CE repo (Ubuntu) | `dnf install docker` or Docker CE repo (see below) |

If you use the **automated script** (`scripts/lightsail-deploy.sh`), set `LIGHTSAIL_SSH_USER=ec2-user` and `DEPLOY_DIR=/home/ec2-user/frappe_docker` when creating an Amazon Linux 2023 instance; the script detects the OS and installs Docker accordingly.

If you follow the **manual steps**, use the Docker install for Amazon Linux 2023 in Step 5 and SSH as `ec2-user@<IP>`.

---

## Overview of steps

1. Create a Lightsail instance (Ubuntu 22.04 or Amazon Linux 2023).
2. Allocate a static IP and attach it to the instance.
3. Open firewall ports (SSH 22, HTTP 80, HTTPS 443, app 8080).
4. Install Docker and Docker Compose on the instance.
5. Clone this repo (or copy files) onto the instance.
6. Build the ERPNext Docker image (or pull from a registry).
7. Create `custom.env` with DB password, site name, etc.
8. Generate `compose.custom.yaml` and start the stack.
9. Create the first site and install ERPNext.
10. Access the UI and (optional) set up HTTPS.

---

## Step 1: Create Lightsail instance

**From AWS Console**

1. Open [Lightsail](https://lightsail.aws.amazon.com/) → **Create instance**.
2. **Platform:** Linux/Unix.
3. **Blueprint:** Ubuntu 22.04 LTS.
4. **Instance plan:** e.g. **$10** (1 GB RAM) or **$20** (2 GB) — 1 GB is minimal; 2 GB is better for ERPNext.
5. **Name:** e.g. `erpnext`.
6. **Create instance**.

**From AWS CLI**

```bash
aws lightsail create-instances \
  --instance-names erpnext \
  --availability-zone us-east-1a \
  --blueprint-id ubuntu_22_04 \
  --bundle-id medium_2_0
```

Use your preferred region and `bundle-id` (e.g. `small_2_0`, `medium_2_0`).

---

## Step 2: Static IP (recommended)

So the instance IP doesn’t change after reboot:

**Console:** Instance → **Networking** → **Create static IP** → attach to this instance.

**CLI:**

```bash
aws lightsail allocate-static-ip --static-ip-name erpnext-ip
aws lightsail attach-static-ip-to-instance \
  --static-ip-name erpnext-ip \
  --instance-name erpnext
```

Get the IP:

```bash
aws lightsail get-static-ip --static-ip-name erpnext-ip --query 'staticIp.ipAddress' --output text
```

Use this IP for SSH and for your site (e.g. `http://<IP>:8080` or point a domain to it).

---

## Step 3: Open firewall ports

**Console:** Instance → **Networking** → **IPv4 firewall** → add:

- TCP 22 (SSH)
- TCP 80 (HTTP)
- TCP 443 (HTTPS)
- TCP 8080 (ERPNext; or use 80 with a reverse proxy later)

**CLI:**

```bash
aws lightsail open-instance-public-ports \
  --instance-name erpnext \
  --port-info fromPort=22,toPort=22,protocol=TCP fromPort=80,toPort=80,protocol=TCP fromPort=443,toPort=443,protocol=TCP fromPort=8080,toPort=8080,protocol=TCP
```

---

## Step 4: SSH into the instance

**Console:** Instance → **Connect** (browser SSH) or use your own SSH client.

**CLI (with default Lightsail key):**

Download the default key from the instance page (Account → SSH keys), then:

- **Ubuntu:** `ssh -i /path/to/key.pem ubuntu@<STATIC_IP>`
- **Amazon Linux 2023:** `ssh -i /path/to/key.pem ec2-user@<STATIC_IP>`

Replace `<STATIC_IP>` with the static IP from Step 2.

---

## Step 5: Install Docker and Docker Compose on the instance

On the instance (via SSH).

**Ubuntu 22.04:**

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker ubuntu
```

**Amazon Linux 2023** (use `dnf`, not `apt-get`):

```bash
sudo dnf update -y
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo sed -i 's/$releasever/9/g' /etc/yum.repos.d/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
```

If the Docker CE repo fails, use the built-in package (no Docker Compose plugin; you may need to install `docker-compose` separately):

```bash
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user
```

Log out and back in (or run `newgrp docker`) so `docker` works without `sudo`.

Verify (both OSes):

```bash
docker --version
docker compose version
```

---

## Step 6: Clone repo and prepare app list

On the instance:

```bash
cd ~
git clone https://github.com/frappe/frappe_docker.git
cd frappe_docker
```

Create `apps.json` (e.g. ERPNext only):

```bash
cat > apps.json << 'EOF'
[
  { "url": "https://github.com/frappe/erpnext", "branch": "version-15" }
]
EOF
```

Encode for the build (Linux):

```bash
export APPS_JSON_BASE64=$(base64 -w 0 apps.json)
```

---

## Step 7: Build the Docker image on the instance

On the instance (this can take 15–30+ minutes):

```bash
cd ~/frappe_docker
docker build \
  --build-arg FRAPPE_PATH=https://github.com/frappe/frappe \
  --build-arg FRAPPE_BRANCH=version-15 \
  --build-arg APPS_JSON_BASE64=$APPS_JSON_BASE64 \
  -t custom:15 \
  -f images/layered/Containerfile .
```

**Alternative:** Build the image on your laptop or in CI, push to Docker Hub or ECR, then on the instance set `CUSTOM_IMAGE`/`CUSTOM_TAG` and `PULL_POLICY=always` and skip this build.

---

## Step 8: Create environment file and generate Compose file

On the instance, create `custom.env`. Replace passwords and site name:

```bash
cd ~/frappe_docker
cp example.env custom.env
```

Edit `custom.env` (e.g. `nano custom.env`) and set at least:

- `DB_PASSWORD` — strong password for **in-container** MariaDB root (used by the `db` service and when creating sites)
- `CUSTOM_IMAGE=custom`
- `CUSTOM_TAG=15`
- `PULL_POLICY=never` (if you built the image on this instance)
- `FRAPPE_SITE_NAME_HEADER` — e.g. your domain or the instance public IP (e.g. `erp.example.com` or leave empty to use `$host`)

**On Lightsail:** Do **not** set `DB_HOST`, `DB_PORT`, `REDIS_CACHE`, or `REDIS_QUEUE` (or leave them empty). The mariadb and redis overrides set the app to use the in-container `db` and Redis; any external DB/Redis values in `custom.env` (e.g. Railway) are overridden in the generated compose and are not used.

Then generate the Compose file:

```bash
docker compose --env-file custom.env \
  -f compose.yaml \
  -f overrides/compose.mariadb.yaml \
  -f overrides/compose.redis.yaml \
  -f overrides/compose.noproxy.yaml \
  config > compose.custom.yaml
```

If you use a **custom domain**, set `FRAPPE_SITE_NAME_HEADER` to that domain so nginx routes correctly.

---

## Step 9: Start the stack

On the instance:

```bash
cd ~/frappe_docker
docker compose -p frappe -f compose.custom.yaml up -d
```

Wait ~30–60 seconds for the database and configurator. Check:

```bash
docker compose -p frappe -f compose.custom.yaml ps
```

---

## Step 10: Create site and install ERPNext

Replace `<sitename>` with your site (e.g. `erp.example.com` or the instance IP). Use the same value as `FRAPPE_SITE_NAME_HEADER` if you set it.

```bash
docker compose -p frappe -f compose.custom.yaml exec backend bench new-site <sitename> \
  --mariadb-user-host-login-scope='172.%.%.%' \
  --db-root-password YOUR_DB_PASSWORD \
  --admin-password YOUR_ADMIN_PASSWORD
```

Install ERPNext:

```bash
docker compose -p frappe -f compose.custom.yaml exec backend bench --site <sitename> install-app erpnext
```

Use the same `<sitename>` and `YOUR_DB_PASSWORD` from `custom.env`.

---

## Step 11: Access the UI

**You do not need a domain.** You can access by IP: `http://<STATIC_IP>:8080`.

**Important:** The site name and `FRAPPE_SITE_NAME_HEADER` must match:

- **Access by IP (e.g. http://3.108.189.33:8080):**  
  Either:
  1. **Create the site with the IP as the name** (e.g. `bench new-site 3.108.189.33 ...`), and set `FRAPPE_SITE_NAME_HEADER=3.108.189.33` in `custom.env`, then regenerate compose and recreate the frontend; **or**
  2. **Create the site with a name you prefer** (e.g. `erp.kynolabs.dev`) and set `FRAPPE_SITE_NAME_HEADER=erp.kynolabs.dev`. Then when you open `http://3.108.189.33:8080`, nginx will still serve that site (the header tells nginx which site to use, not the browser URL).

- **Access by domain:** Point DNS A record to `<STATIC_IP>`, set `FRAPPE_SITE_NAME_HEADER` to that domain, create the site with that same name, then open `http://yourdomain.com:8080` (or use a reverse proxy on 80/443).

If you see **"Not Found - erp.kynolabs.dev does not exist"** when opening `http://<IP>:8080`, it means `FRAPPE_SITE_NAME_HEADER` is set to `erp.kynolabs.dev` but no site with that name exists on this instance. Fix: create a site named `erp.kynolabs.dev` (Step 10), or change `FRAPPE_SITE_NAME_HEADER` to the site name you did create (e.g. the IP) and recreate the frontend.

Login: **Administrator** / password from `--admin-password`.

---

## Optional: HTTPS with Caddy

On the instance, install Caddy and proxy 80/443 to localhost:8080:

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

Create `/etc/caddy/Caddyfile` (replace `erp.example.com`):

```
erp.example.com {
  reverse_proxy localhost:8080
}
```

Then:

```bash
sudo systemctl reload caddy
```

---

## Access two (or more) tenants by static IP (different ports)

To access the **first tenant** and **tenant2** (or more) on the same static IP, use **different ports** (e.g. 8080 and 8081). Each port is served by a separate frontend container with its own `FRAPPE_SITE_NAME_HEADER`.

**1. Add the multi-tenant override when generating compose**

In `custom.env` set the second tenant’s site name (and optional port):

```bash
TENANT2_SITE_NAME=tenant2.kynolabs.dev
# TENANT2_HTTP_PORT=8081   # optional; default 8081
```

Regenerate the compose file **including** the multi-tenant override:

```bash
cd ~/frappe_docker
docker compose --env-file custom.env \
  -f compose.yaml \
  -f overrides/compose.mariadb.yaml \
  -f overrides/compose.redis.yaml \
  -f overrides/compose.noproxy.yaml \
  -f overrides/compose.multi-tenant-ports.yaml \
  config > compose.custom.yaml
```

**2. Open port 8081 on Lightsail**

In the Lightsail instance **Networking** tab, add a firewall rule: **TCP 8081**.

CLI:

```bash
aws lightsail open-instance-public-ports \
  --instance-name erpnext \
  --port-info fromPort=22,toPort=22,protocol=TCP fromPort=80,toPort=80,protocol=TCP fromPort=443,toPort=443,protocol=TCP fromPort=8080,toPort=8080,protocol=TCP fromPort=8081,toPort=8081,protocol=TCP
```

**3. Start (or recreate) the stack**

```bash
docker compose -p frappe -f compose.custom.yaml up -d
```

**4. Access by static IP**

- **First tenant (erp.kynolabs.dev):** `http://<STATIC_IP>:8080`
- **Second tenant (tenant2.kynolabs.dev):** `http://<STATIC_IP>:8081`

No DNS or domain is required; both use the same static IP. Ensure the site for each tenant exists (e.g. `bench new-site erp.kynolabs.dev ...` and `bench new-site tenant2.kynolabs.dev ...`, or use `scripts/create-tenant.sh` for the second).

---

## Automated script

Use **`scripts/lightsail-deploy.sh`** to create Lightsail resources and deploy in one go, or run only the on-instance steps.

### Option A: Create instance and deploy from your laptop (one command)

Requires: AWS CLI configured, SSH key (e.g. Lightsail default key).

```bash
cd frappe_docker

export AWS_REGION=us-east-1
export LIGHTSAIL_INSTANCE_NAME=erpnext
export LIGHTSAIL_KEY_PATH=~/.ssh/LightsailDefaultKey-us-east-1.pem
export DB_PASSWORD='your-secure-db-password'
export ADMIN_PASSWORD='your-admin-password'
export SITE_NAME=erp.example.com

chmod +x scripts/lightsail-deploy.sh
./scripts/lightsail-deploy.sh create
```

The script will:

1. Create the Lightsail instance (Ubuntu 22.04), allocate a static IP, open ports 22, 80, 443, 8080.
2. SSH into the instance and run the bootstrap: install Docker, clone repo, build image, create `custom.env`, generate compose, start stack, create site, install ERPNext.

Use the **static IP** shown at the end to open the UI: `http://<static-ip>:8080`. Login: **Administrator** / `ADMIN_PASSWORD`.

### Option B: Run only on the instance (after you created it and SSH’d in)

If you already have a Lightsail instance and want to run only the deploy steps on it:

```bash
export DB_PASSWORD='your-secure-db-password'
export ADMIN_PASSWORD='your-admin-password'
export SITE_NAME=erp.example.com

curl -sSL https://raw.githubusercontent.com/frappe/frappe_docker/main/scripts/lightsail-deploy.sh | bash -s bootstrap
```

Or clone the repo first and run:

```bash
git clone https://github.com/frappe/frappe_docker.git
cd frappe_docker
export DB_PASSWORD='...' ADMIN_PASSWORD='...' SITE_NAME='erp.example.com'
./scripts/lightsail-deploy.sh bootstrap
```

### Script env vars (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `us-east-1` | Lightsail region |
| `LIGHTSAIL_INSTANCE_NAME` | `erpnext` | Instance name |
| `LIGHTSAIL_STATIC_IP_NAME` | `{instance}-ip` | Static IP name |
| `LIGHTSAIL_KEY_PATH` | — | Path to .pem key (required for `create` + SSH deploy) |
| `LIGHTSAIL_SSH_USER` | `ubuntu` | SSH user: use `ec2-user` for **Amazon Linux 2023** |
| `LIGHTSAIL_BUNDLE_ID` | `medium_2_0` | Instance size (e.g. `small_2_0`, `medium_2_0`) |
| `REPO_URL` | frappe_docker repo | Git clone URL |
| `SKIP_BUILD` | `0` | Set `1` to skip image build (use pre-built image and set env in custom.env) |
| `FRAPPE_SITE_NAME_HEADER` | same as `SITE_NAME` | Site name for nginx (e.g. domain) |
| `DEPLOY_DIR` | `/home/ubuntu/frappe_docker` | Path on instance for repo |

---

## Troubleshooting

### "Not Found - erp.kynolabs.dev does not exist" when opening http://&lt;IP&gt;:8080

You **do not need a valid domain** to use the IP. This message means nginx is set to serve the site **erp.kynolabs.dev** (from `FRAPPE_SITE_NAME_HEADER`), but that site does not exist in the bench on this instance.

**Fix (choose one):**

1. **Create the site with that name** (if you want to keep using `erp.kynolabs.dev`):
   ```bash
   docker compose -p frappe -f compose.custom.yaml exec backend bench new-site erp.kynolabs.dev \
     --mariadb-user-host-login-scope='172.%.%.%' \
     --db-root-password YOUR_DB_PASSWORD \
     --admin-password YOUR_ADMIN_PASSWORD
   docker compose -p frappe -f compose.custom.yaml exec backend bench --site erp.kynolabs.dev install-app erpnext
   ```
   Then reload http://3.108.189.33:8080 — it will work (nginx serves that site regardless of the URL you type).

2. **Use the IP as the site name:** Create the site with the IP, set `FRAPPE_SITE_NAME_HEADER` to the IP, regenerate compose, and recreate the frontend:
   - In `custom.env`: `FRAPPE_SITE_NAME_HEADER=3.108.189.33`
   - Regenerate: `docker compose --env-file custom.env -f compose.yaml -f overrides/compose.mariadb.yaml -f overrides/compose.redis.yaml -f overrides/compose.noproxy.yaml config > compose.custom.yaml`
   - Recreate frontend: `docker compose -p frappe -f compose.custom.yaml up -d --force-recreate frontend`
   - Create site: `bench new-site 3.108.189.33 ...` (and install-app). Then open http://3.108.189.33:8080.

---

## Summary

| Item            | Where it runs        |
|-----------------|----------------------|
| MariaDB         | Container on instance |
| Redis (cache)   | Container on instance |
| Redis (queue)   | Container on instance |
| ERPNext app     | Containers on instance |
| All resources   | Single Lightsail instance |

No separate Lightsail managed database is required; SQL and Redis are created and run as containers on the same instance via Docker Compose.

cd ~/frappe_docker   # or wherever you deployed

# Create the site (use your actual DB_PASSWORD and admin password)
docker compose -p frappe -f compose.custom.yaml exec backend bench new-site erp.kynolabs.dev \
  --mariadb-user-host-login-scope='172.%.%.%' \
  --db-root-password YOUR_DB_PASSWORD \
  --admin-password YOUR_ADMIN_PASSWORD

# Install ERPNext on that site
docker compose -p frappe -f compose.custom.yaml exec backend bench --site erp.kynolabs.dev install-app erpnext