# start Container

Ensure the image referenced in your compose file (e.g. `custom:15`) exists locally. Build it first using the [Build Setup](02-build-setup.md) steps if you have not already. You can confirm the image is present with:

```bash
docker images custom
```

Once your compose file is ready and the image is built, start all containers with a single command:

```bash
docker compose -p frappe -f compose.custom.yaml up -d
```

```bash
podman-compose --in-pod=1 --project-name frappe -f compose.custom.yaml up -d
```

The `-p` (or `--project-name`) flag names the project `frappe`, allowing you to easily reference and manage all containers together.

# Create a site and install apps

Frappe is now running, but it's not yet configured. You need to create a site and install your apps.

Only apps that were included in the image at build time (via `apps.json` and `APPS_JSON_BASE64`) can be installed. To see which apps are in your image:

```bash
docker compose -p frappe -f compose.custom.yaml exec backend ls apps
```

## Basic site creation

```bash
docker compose -p frappe -f compose.custom.yaml exec backend bench new-site <sitename> --mariadb-user-host-login-scope='172.%.%.%'
docker compose -p frappe -f compose.custom.yaml exec backend bench --site <sitename> install-app erpnext
```

> **Note:** If you get `No module named 'erpnext'`, the image was built without that app. Rebuild the image with `apps.json` containing the app and `APPS_JSON_BASE64` set (see [Build Setup](02-build-setup.md)), then start the stack again.

```bash
podman exec -ti erpnext_backend_1 /bin/bash
bench new-site <sitename> --mariadb-user-host-login-scope='172.%.%.%'
bench --site <sitename> install-app erpnext
```

Replace `<sitename>` with your desired site name.

## Create site with app installation

You can install apps during site creation:

```bash
docker compose -p frappe -f compose.custom.yaml exec backend bench new-site <sitename> \
  --mariadb-user-host-login-scope='%' \
  --db-root-password <db-password> \
  --admin-password <admin-password> \
  --install-app erpnext
```

> **Note:** Wait for the `db` service to start and `configurator` to exit before trying to create a new site. Usually this takes up to 10 seconds.

For more site operations, refer to [site operations](../04-operations/01-site-operations.md).

## Accessing the UI

The frontend is exposed on port **8080**. Open **http://localhost:8080** or **http://127.0.0.1:8080** in your browser.

If you see a blank page or "site not found", the nginx proxy is routing by the request hostname (default `$host`). Your site name (e.g. `erp.kynolabs.dev`) does not match `localhost` or `127.0.0.1`. Set `FRAPPE_SITE_NAME_HEADER` to your site name in `custom.env`, regenerate the compose file (or set it in the frontend service environment), then recreate the frontend container so nginx always serves that site. See [env variables](04-env-variables.md#site-configuration).

> ## Understanding the MariaDB User Scope
>
> The flag --mariadb-user-host-login-scope='172.%.%.%' allows database connections from any IP address within the 172.0.0.0/8 range. This includes all containers and virtual machines running on your machine.
>
> **Why is this necessary?** Docker and Podman assign dynamic IP addresses to containers. If you set a fixed IP address instead, database connections will fail when the container restarts and receives a new IP. The wildcard pattern ensures connections always work, regardless of IP changes.
>
> **Security note:** This scope is sufficient because only the backend container accesses the database. If you need external database access, adjust the scope accordingly, but be cautious with overly permissive settings.

---

**Back:** [Build Setup →](02-build-setup.md)

**Next:** [Setup Examples →](06-setup-examples.md)
