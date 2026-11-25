"""Give an existing, active person the first PLATFORM_GRANT_ADMIN grant (F2-T10, decision D30).

DEV and test/CI only (ENVIRONMENT=dev or test); production is refused. Runs with the database
owner credentials from the environment (APP_DB_OWNER_USER / APP_DB_OWNER_PASSWORD and the usual
APP_DB_* connection settings) and the identity-provider admin client (AUTH_* settings, the
at-admin-svc secret): the person must already have a one-time code or passkey, and the account is
marked so that the second factor stays mandatory. Nothing is created at the identity provider.

    uv run python scripts/identity/bootstrap_platform_admin.py --email person@example.test [--days 90]

Prints the new grant id and its expiry; never an address, a secret or a token. Exit code 0 on
success, 2 when refused (nothing granted)."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta

from app.auth.idp_admin import KeycloakAdmin
from app.auth.settings import AuthSettings
from app.core.config import get_settings
from app.core.db import create_db_engine, create_session_factory
from app.platform.bootstrap import BootstrapRefused, bootstrap_platform_admin
from pydantic import ValidationError


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.environment == "prod":
        sys.stderr.write("refused: the bootstrap is allowed only in DEV and test/CI\n")
        return 2
    try:
        engine = create_db_engine(settings, role="owner")  # owner credentials, never another role
    except RuntimeError:
        sys.stderr.write("refused: the database owner credentials are not configured\n")
        return 2
    try:
        auth = AuthSettings()  # type: ignore[call-arg]
    except ValidationError:
        engine.dispose()
        sys.stderr.write("refused: the identity provider is not configured\n")
        return 2
    admin = KeycloakAdmin(auth) if auth.admin_client_secret else None
    try:
        done = bootstrap_platform_admin(
            create_session_factory(engine),
            admin,
            email=args.email,
            environment=settings.environment,
            now=datetime.now(UTC),
            lifetime=timedelta(days=args.days),
        )
    except BootstrapRefused as refused:
        sys.stderr.write(f"refused: {refused}\n")
        return 2
    finally:
        engine.dispose()
        if admin is not None:
            admin.close()
    sys.stdout.write(f"grant {done.grant_id} expires {done.expires_at.isoformat()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
