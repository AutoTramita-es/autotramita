# AutoTramita.es — Development guide (phase F1)

Scope: the F1 foundation only (toolchain, configuration, database layer, migrations, RLS tests, API conventions, rate limiting, health, OpenAPI, CI). There are no business tables, no authentication and no deployment. See [G6-EXECUTION-ORDER.md](G6-EXECUTION-ORDER.md) for what F1 may and may not touch.

## Prerequisites
Use Python **3.12.16** and uv **0.13.9**. Install uv from the versioned official release, then install the pinned Python:

```sh
curl --proto '=https' --tlsv1.2 -LsSf https://releases.astral.sh/github/uv/releases/download/0.13.9/uv-installer.sh | sh
uv --version                 # must report 0.13.9
uv python install 3.12.16
```

`pyproject.toml` enforces uv 0.13.9; commands fail rather than silently using another version. `.python-version` selects Python 3.12.16. Runtime requirements and the `dev` dependency group remain separate; `uv.lock` fixes the resolved versions. OpenTelemetry API and SDK are runtime dependencies for the future integration point; no instrumentation or exporter is configured in F1.

The locked direct runtime versions include Alembic 1.20.1, FastAPI 0.165.0, OpenTelemetry API/SDK 1.45.2, psycopg 3.3.9, Pydantic 2.14.4, pydantic-settings 2.16.3, redis client 8.2.0 and SQLAlchemy 2.1.9. The dev group locks HTTPX 0.28.1, mypy 2.4.1, pytest 9.2.0 and Ruff 0.17.6.

Also install Docker (disposable test containers, client generation) and Node 20 (TypeScript client check).

```sh
uv sync --locked          # create .venv from uv.lock
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
```

## Test infrastructure (disposable, never the shared server)
Integration tests need their own PostgreSQL 16 and Redis. Use throwaway containers bound to localhost with a random password; **do not point tests at the shared `postgres` container**.

```sh
PW=$(openssl rand -hex 16)
docker run -d --rm --name at-f1-pg -e POSTGRES_PASSWORD=$PW -p 127.0.0.1:55432:5432 \
  --tmpfs /var/lib/postgresql/data postgres:16-bookworm
docker run -d --rm --name at-f1-redis -p 127.0.0.1:56379:6379 redis:7.4-alpine
export TEST_PG_ADMIN_URL=postgresql://postgres:$PW@127.0.0.1:55432/postgres
export TEST_REDIS_URL=redis://127.0.0.1:56379/15
uv run pytest -q
```

Without these variables integration tests are skipped locally; when `CI` is set a missing variable fails the run. Tests create and drop their own databases and roles.

## Checks run in CI
`.github/workflows/ci.yml`: Ruff, mypy, pytest on PostgreSQL 16 and Redis service containers (migrations up/down, RLS negative tests, rate limiting), OpenAPI drift check, TypeScript and Dart client generation (`openapi/check-clients.sh`), gitleaks over full history, `pip-audit` on the locked dependencies.

## Layout
- `app/core/` configuration, database layer and request context, role model, errors, pagination, idempotency, versioning, rate limiting, logging.
- `app/api/` application factory, error handlers, middleware, OpenAPI, `v1/` routers (health only in F1). ASGI entry: `app.api.main:app`.
- `migrations/` Alembic, run as the **owner** role only; migration state lives in the `schema_migrations` schema, which runtime roles cannot read.
- `scripts/db/harden.sql` schema hardening applied after roles are created.
- `openapi/openapi.json` committed contract; regenerate with `uv run python -m app.api.export_openapi`.

## Conventions
- **Database roles** (per environment): `owner` owns objects and runs migrations; `app` (API), `worker` (Celery) and `platform` (cross-tenant review, no access by default) never own tables and never have `BYPASSRLS`. Tenant tables use `ENABLE` plus `FORCE ROW LEVEL SECURITY`, policies with `USING` and `WITH CHECK`, and composite `(tenant_id, id)` keys.
- **Settings** (`app/core/config.py`): four separate PostgreSQL role configurations, never derived from one another. `app` (API runtime) is `POSTGRES_USER`/`POSTGRES_PASSWORD` and is the only required role; `owner` (migrations only) is `APP_DB_OWNER_USER`/`APP_DB_OWNER_PASSWORD`; `worker` is `APP_DB_WORKER_USER`/`APP_DB_WORKER_PASSWORD`; `platform` is `APP_DB_PLATFORM_USER`/`APP_DB_PLATFORM_PASSWORD`. Shared: `ENVIRONMENT` (`dev`, `prod` or `test`, required), `POSTGRES_HOST`, `POSTGRES_PORT` (default 5432), `POSTGRES_DB`, `REDIS_URL`. A user without a password (or the reverse), an empty value, or two roles with the same user name or password is rejected; an unconfigured role raises `RuntimeError` instead of falling back. `Settings.database_url(role)` returns an escaped URL as `SecretStr`; engines belong to the DB layer. The Redis URL, passwords and URLs are `SecretStr`, validation errors carry no input, and `Settings.redis_url` returns the clear string only for creating the client. No `.env` or secrets file is read and nothing connects at import. In the existing compose file the worker container still receives its role through `POSTGRES_USER`/`POSTGRES_PASSWORD`; that contract is unchanged.
- **Request context**: always `session_scope(engine, RequestContext(...))`; it writes `app.user_id`, `app.tenant_id` and `app.branch_ids` with transaction-local `set_config`. A commit inside the block drops the context (fail closed). Policies read it through `app_tenant_id()`, `app_user_id()` and `app_branch_ids()`.
- **Errors** are `application/problem+json` with a stable `code`; validation errors never echo input. Use `AppError` subclasses.
- **Pagination** is cursor based (`limit` 1 to 100, opaque `cursor`, no totals). Cursor values must be bound as parameters.
- **Writes**: `Idempotency-Key` on consequential POST (24 h, tenant scoped) and `If-Match: "<version>"` on updates.
- **Rate limits** come from `RATE_LIMIT_*` environment variables (defaults: public 60/min per IP, authenticated 300/min per user, tenant 3000/min, upload 30/min, export 5/min); health endpoints are exempt. If Redis is down, requests are allowed and logged unless `RATE_LIMIT_FAIL_OPEN=false` (known deviation from O02, fail closed; resolved in F1-T07). The Keycloak and password-recovery values are reserved for F2. `TRUSTED_PROXY_HOPS` must be set to the number of proxies in front of the API before `X-Forwarded-For` is honored.
- **Never** put secrets, personal data or real documents in the repository, fixtures or logs.

## Known limits of F1
The in-database context is set by the application; code that can run arbitrary SQL as a runtime role could set another tenant's context, so SQL is always parameterized and runtime roles have no DDL rights. `scripts/provision-postgres.py` has its own copy of the hardening statements and is not run by F1; it should be aligned with `scripts/db/harden.sql` before first use. Keycloak, authentication, tenant tables, documents and deployment belong to later phases.
