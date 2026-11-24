"""Transactions of the web sign-in (F2-T06) that use the authentication bootstrap context.

They live in the auth module on purpose: only this package may build a ``RequestContext`` from
an identity-provider subject (D17); the HTTP layer just calls them."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.runtime import AuthRuntime
from app.auth.security import email_change
from app.auth.sessions import repository as session_repository
from app.auth.sessions import service as sessions
from app.auth.sessions.models import ClientType, RevokeReason
from app.auth.tokens import VerifiedIdToken, VerifiedLogout
from app.auth.users import repository as user_repository
from app.auth.users import service as users
from app.auth.users.models import UserStatus
from app.auth.web.stepup import level_from_acr
from app.core.db import RequestContext, apply_context, session_scope


@dataclass(frozen=True, slots=True)
class LoginOutcome:
    secret: str
    absolute_expires_at: datetime
    disabled_user_id: UUID | None = None
    user_id: UUID | None = None
    session_id: UUID | None = None
    email: str | None = None
    reauthenticate: bool = False  # the provider session predates a security change


def complete_login(
    rt: AuthRuntime,
    identity: VerifiedIdToken,
    client_type: ClientType,
    *,
    email: str,
    ip_prefix: str | None,
    ua_family: str | None,
) -> LoginOutcome:
    """Provision or find the user and, if the account may sign in, open the web session."""
    with session_scope(rt.factory, RequestContext(auth_subject=identity.subject)) as db:
        user = users.provision_or_link(
            db,
            subject=identity.subject,
            email=email,
            email_verified=bool(identity.email_verified),
            audit_factory=rt.factory,
            token_issued_at=identity.issued_at,
        ).user
        if user.status not in (UserStatus.ACTIVE, UserStatus.PENDING_VERIFICATION):
            return LoginOutcome("", datetime.now(UTC), disabled_user_id=user.id)
        if email_change.requires_fresh_authentication(
            db,
            user_id=user.id,
            kc_session_id=identity.session_id,
            auth_time=identity.auth_time,
            leeway_seconds=rt.settings.leeway_seconds,
        ):
            return LoginOutcome("", datetime.now(UTC), reauthenticate=True)
        level = level_from_acr(identity.acr)
        created = sessions.create_session(
            db,
            user_id=user.id,
            client_type=client_type,
            kc_session_id=identity.session_id,
            auth_time=datetime.fromtimestamp(identity.auth_time or rt.clock(), tz=UTC),
            policy=rt.policy,
            auth_level=level,
            ua_family=ua_family,
            ip_prefix=ip_prefix,
        )
        users.record_login(db, user)
        record(
            db,
            AuditEvent(
                action="auth.login.succeeded",
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.USER,
                actor_user_id=user.id,
                subject_user_id=user.id,
                actor_session_id=created.session.id,
                ip_prefix=ip_prefix,
                ua_family=ua_family,
                details={"client_type": client_type.value, "auth_level": level.value},
            ),
        )
        return LoginOutcome(
            created.credential or "",
            created.session.absolute_expires_at,
            user_id=user.id,
            session_id=created.session.id,
            email=user.email,
        )


def revoke_for_logout(rt: AuthRuntime, verified: VerifiedLogout) -> None:
    """Back-channel logout: end the named Keycloak session (or all sessions of the person when
    the token names none). An unknown person changes nothing and is not revealed."""
    with session_scope(rt.factory, RequestContext(auth_subject=verified.subject)) as db:
        user = user_repository.get_by_subject(db, verified.subject)
        if user is None:
            return
        apply_context(db, RequestContext(user_id=user.id))
        condition = "user_id = :u"
        params: dict[str, Any] = {"u": user.id}
        if verified.session_id:
            condition += " AND kc_session_id = :k"
            params["k"] = verified.session_id
        count = session_repository.revoke_where(
            db,
            condition,
            params,
            reason=RevokeReason.IDP_LOGOUT.value,
            now=datetime.now(UTC),
            revoked_by=None,
        )
        record(
            db,
            AuditEvent(
                action="session.revoked",
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.IDP,
                subject_user_id=user.id,
                details={"revoked_reason": RevokeReason.IDP_LOGOUT.value, "count": count},
            ),
        )
