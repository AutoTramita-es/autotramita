"""The first grant administrator (F2-T10, decision D30): a command run by an infrastructure
administrator with the database *owner* credentials, outside the application.

Only in DEV and test/CI (``ENVIRONMENT`` = ``dev`` or ``test``); a production bootstrap and the
first production administrator need their own approval (D30) and this refuses ``prod``. It
creates no account, no password and no service account: it gives an existing, active person who
already has a one-time code or passkey a ``PLATFORM_GRANT_ADMIN`` grant for at most 90 days,
marks the account at the identity provider so that its second factor stays mandatory, and
records the activation with ``actor_type=SYSTEM``. Using the grant then needs level two like
every other grant. Four-eyes approvals need two such administrators, so DEV/CI bootstraps two."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.email import normalize_email
from app.auth.errors import AuthNotConfigured, IdentityProviderUnavailable, NoSecondFactor
from app.auth.idp import IdentityProviderAdmin
from app.core.config import Environment
from app.core.db import RequestContext, session_scope
from app.platform.models import BOOTSTRAP_LIFETIME
from app.platform.service import require_permanent_factor
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

ALLOWED_ENVIRONMENTS = frozenset({"dev", "test"})


class BootstrapRefused(Exception):
    """Nothing was granted. The message names the rule, never an address or identifier."""


@dataclass(frozen=True, slots=True)
class Bootstrapped:
    grant_id: UUID
    user_id: UUID
    expires_at: datetime


def _require_owner(db: Session) -> None:
    owns = db.execute(
        text(
            "SELECT pg_get_userbyid(c.relowner) = current_user AND session_user = current_user "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relname = 'platform_grants'"
        )
    ).scalar_one_or_none()
    if not owns:
        raise BootstrapRefused("the bootstrap runs only with the database owner credentials")


def bootstrap_platform_admin(
    owner_factory: sessionmaker[Session],
    admin: IdentityProviderAdmin | None,
    *,
    email: str,
    environment: Environment,
    now: datetime,
    lifetime: timedelta = BOOTSTRAP_LIFETIME,
) -> Bootstrapped:
    if environment not in ALLOWED_ENVIRONMENTS:
        raise BootstrapRefused("the bootstrap is allowed only in DEV and test/CI")
    if not timedelta(0) < lifetime <= BOOTSTRAP_LIFETIME:
        raise BootstrapRefused("a bootstrap grant lasts at most 90 days")
    try:
        normalized = normalize_email(email)
    except ValueError:
        raise BootstrapRefused("not a valid e-mail address") from None
    expires_at = now + lifetime
    with session_scope(owner_factory, RequestContext()) as db:
        _require_owner(db)
        db.execute(text("SELECT set_config('app.bootstrap_email', :e, true)"), {"e": normalized})
        person = db.execute(
            text("SELECT id, auth_subject, status FROM users WHERE email_normalized = :e"),
            {"e": normalized},
        ).one_or_none()
        if person is None or person.status != "ACTIVE":
            raise BootstrapRefused("no active account with this address")
        try:
            require_permanent_factor(admin, person.auth_subject)
        except NoSecondFactor:
            raise BootstrapRefused("the person has no one-time code or passkey") from None
        except (AuthNotConfigured, IdentityProviderUnavailable):
            raise BootstrapRefused("the identity provider is not reachable") from None
        try:
            with db.begin_nested():
                grant_id, stored_expiry = db.execute(
                    text(
                        "INSERT INTO platform_grants (user_id, grant_type, status, expires_at, "
                        "reason) VALUES (:u, 'PLATFORM_GRANT_ADMIN', 'ACTIVE', :x, 'bootstrap') "
                        "RETURNING id, expires_at"
                    ),
                    {"u": person.id, "x": expires_at},
                ).one()
        except IntegrityError:
            raise BootstrapRefused(
                "the person already holds a live grant administrator grant"
            ) from None
        record(
            db,
            AuditEvent(
                action="authz.platform_grant.activated",
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.SYSTEM,
                subject_user_id=person.id,
                target_type="platform_grant",
                target_id=grant_id,
                reason_code="BOOTSTRAP",
                details={"grant_type": "PLATFORM_GRANT_ADMIN", "grant_id": grant_id},
            ),
        )
    return Bootstrapped(grant_id, person.id, stored_expiry)
