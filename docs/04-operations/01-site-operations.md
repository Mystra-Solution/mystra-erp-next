# Site operations

> 💡 You should setup `--project-name` option in `docker-compose` commands if you have non-standard project name.

## Setup new site

Note:

- Wait for the `db` service to start and `configurator` to exit before trying to create a new site. Usually this takes up to 10 seconds.
- Also you have to pass `-p <project_name>` if `-p` passed previously eg. `docker-compose -p <project_name> exec (rest of the command)`.

```sh
docker-compose exec backend bench new-site --mariadb-user-host-login-scope=% --db-root-password <db-password> --admin-password <admin-password> <site-name>
```

If you need to install some app, specify `--install-app`. To see all options, just run `bench new-site --help`.

## Create new tenant (multi-tenancy)

For a new tenant you create a **new bench site** (and thus a **new MariaDB database** on the same MariaDB server). **Redis is shared** across all tenants — you do not create a new Redis.

- **MariaDB:** Same server; `bench new-site` creates a new database for this tenant.
- **Redis:** Same redis-cache and redis-queue for all sites.
- **Bench:** One bench; multiple sites (one site = one tenant).

Use the script from the repo root (with Docker Compose):

```sh
export DB_PASSWORD='your-db-root-password'
./scripts/create-tenant.sh tenant2.example.com 'AdminPasswordForTenant2'
```

Or run the commands manually:

```sh
docker compose -p frappe -f compose.custom.yaml exec backend bench new-site tenant2.example.com \
  --mariadb-user-host-login-scope='172.%.%.%' \
  --db-root-password <db-password> \
  --admin-password <admin-password>

docker compose -p frappe -f compose.custom.yaml exec backend bench --site tenant2.example.com install-app erpnext
```

To serve the new tenant **by static IP** (same server, no domain): use a **second frontend on a different port** (e.g. 8081). See [overrides/compose.multi-tenant-ports.yaml](../../overrides/compose.multi-tenant-ports.yaml) and the [Lightsail doc section “Access two (or more) tenants by static IP”](../DEPLOY-LIGHTSAIL.md#access-two-or-more-tenants-by-static-ip-different-ports): add the override when generating compose, set `TENANT2_SITE_NAME`, open port 8081, then access `http://<IP>:8080` and `http://<IP>:8081`.

To serve by domain, use a frontend that routes by host (e.g. set `FRAPPE_SITE_NAME_HEADER` per frontend or use [multi-tenancy](03-production/03-multi-tenancy.md) with one frontend per site/port).

---

To create Postgres site (assuming you already use [Postgres compose override](../02-setup/05-overrides.md)) you need have to do set `root_login` and `root_password` in common config before that:

```sh
docker-compose exec backend bench set-config -g root_login <root-login>
docker-compose exec backend bench set-config -g root_password <root-password>
```

Also command is slightly different:

```sh
docker-compose exec backend bench new-site --mariadb-user-host-login-scope=% --db-type postgres --admin-password <admin-password> <site-name>
```

## Push backup to S3 storage

We have the script that helps to push latest backup to S3.

```sh
docker-compose exec backend push_backup.py --site-name <site-name> --bucket <bucket> --region-name <region> --endpoint-url <endpoint-url> --aws-access-key-id <access-key> --aws-secret-access-key <secret-key>
```

Note that you can restore backup only manually.

## Edit configs

Editing config manually might be required in some cases,
one such case is to use Amazon RDS (or any other DBaaS).
For full instructions, refer to the [wiki](<https://github.com/frappe/frappe/wiki/Using-Frappe-with-Amazon-RDS-(or-any-other-DBaaS)>). Common question can be found in Issues and on forum.

`common_site_config.json` or `site_config.json` from `sites` volume has to be edited using following command:

```sh
docker run --rm -it \
    -v <project-name>_sites:/sites \
    alpine vi /sites/common_site_config.json
```

Instead of `alpine` use any image of your choice.

## Health check

For socketio and gunicorn service ping the hostname:port and that will be sufficient. For workers and scheduler, there is a command that needs to be executed.

```shell
docker-compose exec backend healthcheck.sh --ping-service mongodb:27017
```

Additional services can be pinged as part of health check with option `-p` or `--ping-service`.

This check ensures that given service should be connected along with services in common_site_config.json.
If connection to service(s) fails, the command fails with exit code 1.

---

For reference of commands like `backup`, `drop-site` or `migrate` check [official guide](https://frappeframework.com/docs/v13/user/en/bench/frappe-commands) or run:

```sh
docker-compose exec backend bench --help
```

## Migrate site

Note:

- Wait for the `db` service to start and `configurator` to exit before trying to migrate a site. Usually this takes up to 10 seconds.

```sh
docker-compose exec backend bench --site <site-name> migrate
```
