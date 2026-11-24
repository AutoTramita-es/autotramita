"""User identity service (F2-T04): first-login provisioning, e-mail sync and account status.

No HTTP here. The caller owns the transaction (``session_scope``) and the request context:

* sign-in runs as the *app* role with ``RequestContext(auth_subject=<sub>)`` (D17);
* status changes run as the *worker* (system) now, and as the platform role once its grants
  exist (F2-T10, F2-T11). The application role cannot change status at all.

Linking is by the identity-provider subject only; an e-mail that belongs to another identity
is a conflict, never a merge (D09).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record, record_independent
from app.auth.email import normalize_email
from app.auth.errors import (
    AccountConflict,
    AccountDisabled,
    EmailNotVerified,
    IdentityProviderUnavailable,
    InvalidStatusTransition,
)
from app.auth.users import repository
from app.auth.users.models import ALLOWED_TRANSITIONS, User, UserStatus
from app.core.db import RequestContext, apply_context
from app.core.errors import BadRequest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)
_EMAIL_KEY = "users_email_normalized_key"


class SessionRevoker(Protocol):
    """Implemented by the session service (F2-T05). Called inside the status transaction, so
    access ends in the same commit as the status change (D11)."""

    def revoke_all(self, session: Session, user_id: UUID, *, reason: str) -> int: ...


@dataclass(frozen=True, slots=True)
class Provisioned:
    user: User
    created: bool


def require_active(user: User) -> None:
    """Gate for routes that need a fully usable account (used by the request pipeline)."""
    if user.status is UserStatus.ACTIVE:
        return
    if user.status is UserStatus.PENDING_VERIFICATION:
        raise EmailNotVerified()
    raise AccountDisabled()


def _is_email_conflict(exc: IntegrityError) -> bool:
    diag: Any = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None) == _EMAIL_KEY


def _conflict(audit_factory: sessionmaker[Session] | None) -> AccountConflict:
    if audit_factory is not None:  # own transaction: the attempt is kept although the request fails
        record_independent(
            audit_factory,
            AuditEvent(
                action="identity.link.conflict",
                outcome=Outcome.DENIED,
                actor_type=ActorType.ANONYMOUS,
                reason_code="EMAIL_TAKEN",
            ),
        )
    return AccountConflict()


def provision_or_link(
    session: Session,
    *,
    subject: str,
    email: str,
    email_verified: bool,
    audit_factory: sessionmaker[Session] | None = None,
    token_issued_at: int | None = None,
    now: datetime | None = None,
) -> Provisioned:
    """Find the user of this Keycloak subject or create it on first sign-in.

    Takes a ``FOR SHARE`` lock on an existing row, so a concurrent deactivation (which takes
    ``FOR UPDATE``) is either finished before this reads the status or waits for it (D16).
    Afterwards the request context carries the user id, so audit inserts are attributable.
    """
    moment = now or datetime.now(UTC)
    try:
        normalized = normalize_email(email)
    except ValueError:
        raise BadRequest("The identity provider returned an invalid e-mail.",
                         code="INVALID_EMAIL") from None  # fmt: skip
    user = repository.get_by_subject(session, subject, lock="share")
    created = False
    if user is None:
        repository.lock_email(session, normalized)
        try:
            with session.begin_nested():
                user = repository.insert(
                    session,
                    subject=subject,
                    email=email.strip(),
                    email_normalized=normalized,
                    verified_at=moment if email_verified else None,
                    status=UserStatus.ACTIVE if email_verified else UserStatus.PENDING_VERIFICATION,
                )
        except IntegrityError as exc:
            if not _is_email_conflict(exc):
                raise
            # The same person signing in twice at once trips the e-mail key before the subject
            # key can say "already there"; if the winner's row is this subject, it is no conflict.
            user = repository.get_by_subject(session, subject, lock="share")
            if user is None:
                raise _conflict(audit_factory) from None
            created = False
        else:
            created = user is not None
        if user is None:  # lost a race for the same subject: read the winner's row
            user = repository.get_by_subject(session, subject, lock="share")
    if user is None:  # pragma: no cover - the row exists after a lost race
        raise RuntimeError("user row not found after provisioning")
    apply_context(session, RequestContext(user_id=user.id))
    if created:
        _audit(session, "identity.user.provisioned", user, {"status": user.status.value})
        return Provisioned(user, True)
    synced = _sync(
        session, user, email, normalized, email_verified, moment, audit_factory, token_issued_at
    )
    return Provisioned(synced, False)


def _sync(
    session: Session,
    user: User,
    email: str,
    normalized: str,
    email_verified: bool,
    moment: datetime,
    audit_factory: sessionmaker[Session] | None,
    token_issued_at: int | None,
) -> User:
    """Apply what the identity provider vouches for. An unverified change is ignored: the
    verified address stays until the new one is verified."""
    if not email_verified:
        return user
    if normalized != user.email_normalized:
        # D37 owns reconciliation once a verified change is in progress. A sign-in must not
        # bypass its session revocation, notifications or recovery after an uncertain IdP call.
        pending = session.execute(
            text("""
                SELECT EXISTS (SELECT 1 FROM email_change_operations WHERE user_id = :u
                    AND status IN ('PENDING', 'CONFIRMED', 'APPLYING', 'MANUAL_REVIEW'))
            """),
            {"u": user.id},
        ).scalar_one()
        if pending:
            raise IdentityProviderUnavailable()
        completed = session.execute(
            text(
                "SELECT max(completed_at) FROM email_change_operations "
                "WHERE user_id=:u AND status='COMPLETED'"
            ),
            {"u": user.id},
        ).scalar_one()
        # An old token can still carry the previous verified address after D37 completes.
        if completed is not None and (
            token_issued_at is None or token_issued_at <= completed.timestamp()
        ):
            raise IdentityProviderUnavailable()
        repository.lock_email(session, normalized)
        try:
            with session.begin_nested():
                repository.update_email(
                    session, user.id, email=email.strip(), email_normalized=normalized,
                    verified_at=moment,
                )  # fmt: skip
        except IntegrityError as exc:
            if _is_email_conflict(exc):
                raise _conflict(audit_factory) from None
            raise
        _audit(session, "identity.email.changed", user, {})
    elif user.email_verified_at is None:
        repository.mark_email_verified(session, user.id, moment)
        _audit(session, "identity.email.verified", user, {})
    else:
        return user
    refreshed = repository.get_by_id(session, user.id)
    return refreshed or user


def record_login(session: Session, user: User, *, now: datetime | None = None) -> None:
    repository.touch_login(session, user.id, now or datetime.now(UTC))


def change_status(
    session: Session,
    *,
    user_id: UUID,
    new_status: UserStatus,
    reason_code: str,
    revoker: SessionRevoker,
    actor_user_id: UUID | None = None,
    privileged: bool = False,
) -> User:
    """Move an account to ``new_status`` in one transaction: lock the row, check the transition,
    update, revoke every session when access ends, and write the audit record.

    ``privileged`` must be true to leave ``BLOCKED`` (platform operation, checked against the
    grant by the caller). The same status again is a no-op. ``actor_user_id`` None means a
    system actor."""
    user = repository.get_by_id(session, user_id, lock="update")
    if user is None:
        raise InvalidStatusTransition()  # invisible and missing rows look the same
    if user.status is new_status:
        return user
    if (user.status, new_status) not in ALLOWED_TRANSITIONS or (
        user.status is UserStatus.BLOCKED and not privileged
    ):
        raise InvalidStatusTransition()
    repository.set_status(
        session, user_id, new_status, reason=reason_code, changed_by=actor_user_id
    )
    if new_status in (UserStatus.DEACTIVATED, UserStatus.BLOCKED):
        revoker.revoke_all(
            session,
            user_id,
            reason="ACCOUNT_BLOCKED" if new_status is UserStatus.BLOCKED else "ACCOUNT_DEACTIVATED",
        )
    action = {
        UserStatus.DEACTIVATED: "identity.user.deactivated",
        UserStatus.BLOCKED: "identity.user.blocked",
        UserStatus.ACTIVE: "identity.user.reactivated",
    }[new_status]
    record(
        session,
        AuditEvent(
            action=action,
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER if actor_user_id else ActorType.SYSTEM,
            actor_user_id=actor_user_id,
            subject_user_id=user_id,
            reason_code=reason_code,
            details={"reason_code": reason_code},
        ),
    )
    updated = repository.get_by_id(session, user_id)
    if updated is None:  # pragma: no cover
        raise RuntimeError("user vanished during a status change")
    return updated


def _audit(session: Session, action: str, user: User, details: dict[str, Any]) -> None:
    record(
        session,
        AuditEvent(
            action=action,
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER,
            actor_user_id=user.id,
            subject_user_id=user.id,
            details=details,
        ),
    )
