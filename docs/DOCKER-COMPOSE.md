# AutoTramita Docker Compose

The shared `postgres`, `nextcloud`, `traefik`, `mailserver`, `snappymail` and `kuma` remain managed by their existing stacks. This Compose project does not recreate or modify them. `backend`, `proxy`, and for PROD `hetzner_net`, are existing shared networks and therefore trust boundaries shared with other stacks.

## Configuration

Use a different Compose project and secret file for each environment:

```sh
mkdir -p .secrets
chmod 700 .secrets
cp .env.prod.example .secrets/prod.env
cp .env.dev.example .secrets/dev.env
chmod 600 .secrets/prod.env .secrets/dev.env
```

Replace every `replace_...` value with distinct secrets. Generate each DB password with `openssl rand -hex 32`; `scripts/provision-postgres.py` accepts URL-safe passwords of at least 32 characters. Both environments use the existing Nextcloud at `https://cloud.autotramita.es`; create separate Nextcloud accounts, app passwords and `AutoTramita/PROD` and `AutoTramita/DEV` roots through the existing Nextcloud administration process. The names and environment variables for the future application are integration placeholders, not an implemented application contract.

Before starting Keycloak, create its database and the application database in the existing `postgres` container:

```sh
scripts/provision-postgres.py prod
scripts/provision-postgres.py dev
```

The script creates missing roles and databases, checks database ownership and verifies credentials on subsequent runs. It revokes PUBLIC connection permission on the AutoTramita databases and grants it to their owners; it does not alter existing roles or change their passwords. Shared PostgreSQL may permit these roles to connect to other databases via existing PUBLIC grants; fully isolating access requires a separately assessed cluster-wide policy. Run only with trusted root-owned environment files and a Docker administrator account. Back up the generated secrets securely. The shared PostgreSQL server is not restarted.

Validate without exposing credentials:

```sh
docker compose --env-file .secrets/prod.env -p autotramita-prod -f docker-compose.yml -f docker-compose.prod.yml config --quiet
docker compose --env-file .secrets/dev.env -p autotramita-dev -f docker-compose.yml -f docker-compose.dev.yml config --quiet
```

Once credentials and service accounts are ready, start each environment using the same arguments and `up -d`. DEV includes Mailpit, internally available at `mailpit:1025`; its UI is not publicly exposed. The wildcard resolves `mailpit.dev.autotramita.es`, but no Mailpit router is configured. DEV configuration directs application SMTP to Mailpit, but Docker network access alone does not prevent application code from connecting to other external mail servers; enforce outbound restrictions before relying on DEV for untrusted code.

`--profile application` additionally enables API, worker, scheduler and frontend. Their image tags, command paths, environment variables and ports are placeholders until application code exists. Do not start this profile until these contracts are implemented. The stack defines Keycloak routing on the shared Traefik; the existing tunnels still return 404 until separately configured. DEV hostnames now use direct DNS-only wildcard resolution and the shared Traefik; `app.dev.autotramita.es`, `api.dev.autotramita.es` and `auth.dev.autotramita.es` are the configured names. Hostnames beyond the API, frontend and authentication require their own future routers. The `www` redirect has not been implemented.

PROD email configuration points at the existing mailserver using `hetzner_net`; SMTP authentication, TLS, account provisioning and a transactional provider are not yet configured. DEV and PROD must use distinct Keycloak databases, credentials, Redis data, Nextcloud accounts and folders. Existing shared Nextcloud users and data must not be modified. Monitoring with existing Uptime Kuma, webmail integration and the optional PaddleOCR/PDF integrations are separate follow-up tasks.

The ClamAV image is included, but scanner integration, readiness, signature updates, quarantine and the documented upload limits must be tested in the application before accepting documents. No direct database ports are published by this project. No Cloudflare Access/Zero Trust component or new Traefik, PostgreSQL, Nextcloud, webmail or mailserver container is created.
