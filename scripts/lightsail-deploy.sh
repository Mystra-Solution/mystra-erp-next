#!/usr/bin/env bash
#
# Deploy ERPNext Docker stack on AWS Lightsail.
#
# Usage:
#   Option 1 - Create instance and deploy (run from your laptop with AWS CLI):
#     export AWS_REGION=us-east-1
#     export LIGHTSAIL_INSTANCE_NAME=erpnext
#     export LIGHTSAIL_KEY_PATH=~/.ssh/LightsailDefaultKey-us-east-1.pem
#     export DB_PASSWORD='your-db-password'
#     export ADMIN_PASSWORD='your-admin-password'
#     export SITE_NAME=erp.example.com
#     ./scripts/lightsail-deploy.sh create
#
#   Option 2 - Deploy only (run on the Lightsail instance after SSH):
#     export DB_PASSWORD='your-db-password'
#     export ADMIN_PASSWORD='your-admin-password'
#     export SITE_NAME=erp.example.com
#     curl -sSL https://raw.githubusercontent.com/frappe/frappe_docker/main/scripts/lightsail-deploy.sh | bash
#     # or: ./scripts/lightsail-deploy.sh bootstrap
#
# MariaDB and Redis run as containers on the same instance (no separate Lightsail DB).
#
set -euo pipefail

# --- Config (override with env) ---
AWS_REGION="${AWS_REGION:-us-east-1}"
LIGHTSAIL_INSTANCE_NAME="${LIGHTSAIL_INSTANCE_NAME:-erpnext}"
LIGHTSAIL_STATIC_IP_NAME="${LIGHTSAIL_STATIC_IP_NAME:-${LIGHTSAIL_INSTANCE_NAME}-ip}"
LIGHTSAIL_KEY_PATH="${LIGHTSAIL_KEY_PATH:-}"
LIGHTSAIL_BLUEPRINT_ID="${LIGHTSAIL_BLUEPRINT_ID:-ubuntu_22_04}"
LIGHTSAIL_BUNDLE_ID="${LIGHTSAIL_BUNDLE_ID:-medium_2_0}"
REPO_URL="${REPO_URL:-https://github.com/frappe/frappe_docker.git}"
SKIP_BUILD="${SKIP_BUILD:-0}"
DB_PASSWORD="${DB_PASSWORD:-}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
SITE_NAME="${SITE_NAME:-}"
FRAPPE_SITE_NAME_HEADER="${FRAPPE_SITE_NAME_HEADER:-}"
# Default user: ubuntu (Ubuntu), ec2-user (Amazon Linux). Override with LIGHTSAIL_SSH_USER for Amazon Linux 2023.
LIGHTSAIL_SSH_USER="${LIGHTSAIL_SSH_USER:-ubuntu}"
DEPLOY_DIR="${DEPLOY_DIR:-/home/${LIGHTSAIL_SSH_USER}/frappe_docker}"

# --- Helpers ---
log() { echo "[$(date +%FT%T)] $*"; }
die() { log "ERROR: $*"; exit 1; }

# --- Create Lightsail instance, static IP, open ports ---
create_lightsail_resources() {
  command -v aws >/dev/null 2>&1 || die "AWS CLI required. Install and run: aws configure"
  log "Creating Lightsail instance: $LIGHTSAIL_INSTANCE_NAME (region: $AWS_REGION)"
  aws lightsail create-instances \
    --region "$AWS_REGION" \
    --instance-names "$LIGHTSAIL_INSTANCE_NAME" \
    --availability-zone "${AWS_REGION}a" \
    --blueprint-id "$LIGHTSAIL_BLUEPRINT_ID" \
    --bundle-id "$LIGHTSAIL_BUNDLE_ID" \
    --output text
  log "Allocating static IP: $LIGHTSAIL_STATIC_IP_NAME"
  aws lightsail allocate-static-ip \
    --region "$AWS_REGION" \
    --static-ip-name "$LIGHTSAIL_STATIC_IP_NAME" \
    --output text
  log "Attaching static IP to instance"
  aws lightsail attach-static-ip-to-instance \
    --region "$AWS_REGION" \
    --static-ip-name "$LIGHTSAIL_STATIC_IP_NAME" \
    --instance-name "$LIGHTSAIL_INSTANCE_NAME" \
    --output text
  log "Opening firewall ports (22, 80, 443, 8080)"
  aws lightsail open-instance-public-ports \
    --region "$AWS_REGION" \
    --instance-name "$LIGHTSAIL_INSTANCE_NAME" \
    --port-info \
      fromPort=22,toPort=22,protocol=TCP \
      fromPort=80,toPort=80,protocol=TCP \
      fromPort=443,toPort=443,protocol=TCP \
      fromPort=8080,toPort=8080,protocol=TCP \
    --output text
  log "Waiting for instance to be running (this may take 1–2 minutes)"
  aws lightsail wait instance-running --region "$AWS_REGION" --instance-name "$LIGHTSAIL_INSTANCE_NAME"
  log "Lightsail resources created."
}

get_instance_ip() {
  aws lightsail get-instance --region "$AWS_REGION" --instance-name "$LIGHTSAIL_INSTANCE_NAME" \
    --query 'instance.publicIpAddress' --output text
}

# --- Bootstrap: run on the Lightsail instance ---
run_bootstrap() {
  if [[ -z "$DB_PASSWORD" || -z "$ADMIN_PASSWORD" || -z "$SITE_NAME" ]]; then
    die "Set DB_PASSWORD, ADMIN_PASSWORD, and SITE_NAME (e.g. export SITE_NAME=erp.example.com)"
  fi
  FRAPPE_SITE_NAME_HEADER="${FRAPPE_SITE_NAME_HEADER:-$SITE_NAME}"

  # Detect OS for Docker install (Ubuntu vs Amazon Linux 2023)
  if [[ -f /etc/os-release ]]; then
    . /etc/os-release
    OS_ID="${ID:-}"
  else
    OS_ID=""
  fi

  log "Installing Docker and Docker Compose (detected: ${OS_ID:-unknown})"
  if [[ "$OS_ID" == "amzn" ]] || grep -q "Amazon Linux" /etc/os-release 2>/dev/null; then
    # Amazon Linux 2023
    sudo dnf update -y -q
    sudo dnf install -y -q dnf-plugins-core
    sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo 2>/dev/null || true
    if [[ -f /etc/yum.repos.d/docker-ce.repo ]]; then
      sudo sed -i 's/$releasever/9/g' /etc/yum.repos.d/docker-ce.repo
    fi
    sudo dnf install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin 2>/dev/null || \
      ( sudo dnf install -y -q docker && sudo systemctl enable --now docker )
    sudo systemctl enable --now docker 2>/dev/null || true
    sudo usermod -aG docker "$USER" 2>/dev/null || true
  else
    # Ubuntu / Debian
    sudo apt-get update -qq
    sudo apt-get install -y -qq ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release 2>/dev/null && echo "${VERSION_CODENAME:-jammy}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER" || true
  fi
  export PATH="$PATH:/usr/bin"
  if ! docker info >/dev/null 2>&1; then
    log "Docker may require a new login to run without sudo. Running with sudo for this session."
    DOCKER="sudo docker"
  else
    DOCKER="docker"
  fi

  log "Cloning repository"
  sudo mkdir -p "$(dirname "$DEPLOY_DIR")"
  if [[ -d "$DEPLOY_DIR/.git" ]]; then
    (cd "$DEPLOY_DIR" && sudo git pull)
  else
    sudo git clone "$REPO_URL" "$DEPLOY_DIR"
  fi
  sudo chown -R "$USER:$USER" "$DEPLOY_DIR"
  cd "$DEPLOY_DIR"

  log "Creating apps.json"
  cat > apps.json << 'APPS_EOF'
[
  { "url": "https://github.com/frappe/erpnext", "branch": "version-15" }
]
APPS_EOF

  if [[ "$SKIP_BUILD" != "1" ]]; then
    log "Encoding apps.json and building Docker image (this can take 15–30+ minutes)"
    APPS_JSON_BASE64=$(base64 -w 0 apps.json 2>/dev/null || base64 -i apps.json | tr -d '\n')
    $DOCKER build \
      --build-arg FRAPPE_PATH=https://github.com/frappe/frappe \
      --build-arg FRAPPE_BRANCH=version-15 \
      --build-arg APPS_JSON_BASE64="$APPS_JSON_BASE64" \
      -t custom:15 \
      -f images/layered/Containerfile .
  else
    log "SKIP_BUILD=1: skipping image build. Set CUSTOM_IMAGE/CUSTOM_TAG and PULL_POLICY=always in custom.env if pulling."
  fi

  log "Creating custom.env"
  cp -n example.env custom.env 2>/dev/null || true
  # Ensure required vars (sed-friendly)
  for line in \
    "DB_PASSWORD=$DB_PASSWORD" \
    "CUSTOM_IMAGE=custom" \
    "CUSTOM_TAG=15" \
    "PULL_POLICY=never" \
    "FRAPPE_SITE_NAME_HEADER=$FRAPPE_SITE_NAME_HEADER"; do
    key="${line%%=*}"
    if grep -q "^${key}=" custom.env 2>/dev/null; then
      sed -i "s|^${key}=.*|${line}|" custom.env
    else
      echo "$line" >> custom.env
    fi
  done

  log "Generating compose.custom.yaml"
  $DOCKER compose --env-file custom.env \
    -f compose.yaml \
    -f overrides/compose.mariadb.yaml \
    -f overrides/compose.redis.yaml \
    -f overrides/compose.noproxy.yaml \
    config > compose.custom.yaml

  log "Starting stack (docker compose up -d)"
  $DOCKER compose -p frappe -f compose.custom.yaml up -d

  log "Waiting for database and configurator (up to 90s)"
  for i in $(seq 1 18); do
    if $DOCKER compose -p frappe -f compose.custom.yaml exec -T backend test -f sites/apps.txt 2>/dev/null; then
      break
    fi
    sleep 5
  done
  sleep 10

  log "Creating site: $SITE_NAME"
  $DOCKER compose -p frappe -f compose.custom.yaml exec -T backend bench new-site "$SITE_NAME" \
    --mariadb-user-host-login-scope='172.%.%.%' \
    --db-root-password "$DB_PASSWORD" \
    --admin-password "$ADMIN_PASSWORD"

  log "Installing ERPNext on site: $SITE_NAME"
  $DOCKER compose -p frappe -f compose.custom.yaml exec -T backend bench --site "$SITE_NAME" install-app erpnext

  log "Done. ERPNext is running. Access the UI at http://<instance-ip>:8080 (user: Administrator, password: your admin password)."
}

# --- Main ---
main() {
  case "${1:-}" in
    create)
      create_lightsail_resources
      INSTANCE_IP=$(get_instance_ip)
      log "Instance IP: $INSTANCE_IP"
      if [[ -z "$LIGHTSAIL_KEY_PATH" ]]; then
        log "Set LIGHTSAIL_KEY_PATH to your .pem key and run the bootstrap on the instance:"
        log "  ssh -i \$LIGHTSAIL_KEY_PATH ${LIGHTSAIL_SSH_USER}@$INSTANCE_IP"
        log "  Then on the instance: export DB_PASSWORD=... ADMIN_PASSWORD=... SITE_NAME=... && curl -sSL .../scripts/lightsail-deploy.sh | bash -s bootstrap"
        exit 0
      fi
      LIGHTSAIL_KEY_PATH="${LIGHTSAIL_KEY_PATH/#\~/$HOME}"
      [[ -f "$LIGHTSAIL_KEY_PATH" ]] || die "Key not found: $LIGHTSAIL_KEY_PATH"
      chmod 600 "$LIGHTSAIL_KEY_PATH"
      log "Running bootstrap on instance via SSH (this may take 20–40 minutes if building image)"
      ssh -o StrictHostKeyChecking=accept-new -i "$LIGHTSAIL_KEY_PATH" "${LIGHTSAIL_SSH_USER}@$INSTANCE_IP" \
        "DB_PASSWORD='$DB_PASSWORD' ADMIN_PASSWORD='$ADMIN_PASSWORD' SITE_NAME='$SITE_NAME' FRAPPE_SITE_NAME_HEADER='$FRAPPE_SITE_NAME_HEADER' SKIP_BUILD='$SKIP_BUILD' REPO_URL='$REPO_URL' DEPLOY_DIR='$DEPLOY_DIR' bash -s" < <(declare -f run_bootstrap; echo "run_bootstrap")
      log "Deploy complete. UI: http://$INSTANCE_IP:8080"
      ;;
    bootstrap)
      run_bootstrap
      ;;
    *)
      echo "Usage: $0 create | bootstrap"
      echo "  create   - Create Lightsail instance (optional: static IP, firewall) and run bootstrap via SSH"
      echo "  bootstrap - Run on the instance: install Docker, clone, build, compose up, create site"
      echo "Set DB_PASSWORD, ADMIN_PASSWORD, SITE_NAME. For 'create' set LIGHTSAIL_KEY_PATH and optionally AWS_REGION, LIGHTSAIL_INSTANCE_NAME."
      exit 1
      ;;
  esac
}

main "$@"
