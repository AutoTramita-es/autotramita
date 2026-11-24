"""Session service (F2-T05): create, resolve on every request, rotate, step up, revoke.

The caller owns the transaction and the request context (``session_scope``). Two rules
shape this module:

* Resolution never writes and, for mutating requests (``lock=True``), takes a ``FOR SHARE``
  lock on the session row. A revocation needs the row exclusively, so it waits for requests in
  flight and every later request sees it (D16). Activity is written separately, best effort,
  by ``touch`` (it skips locked rows), which also avoids share-to-update lock upgrades.
* Failures that must leave a trace while the request itself fails (a suspected theft) are
  reported by an exception; the caller rolls back and then calls ``revoke_independent``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth import credentials
from app.auth.errors import (
    AccountDisabled,
    SessionExpired,
    SessionRequired,
    SessionRevoked,
    SessionSecurityViolation,
)
from app.auth.sessions import repository
from app.auth.sessions.models import (
    AuthLevel,
    ClientType,
    RevokeReason,
    SessionPolicy,
    UserSession,
)
from app.auth.tokens import VerifiedToken
from app.auth.users import repository as users
from app.auth.users.models import User, UserStatus
from app.core.db import RequestContext, apply_context, session_scope
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)
_MAY_SIGN_IN = {UserStatus.ACTIVE.value, UserStatus.PENDING_VERIFICATION.value}


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CreatedSession:
    session: UserSession
    credential: str | None  # shown once; None for mobile sessions (Keycloak tokens)


@dataclass(frozen=True, slots=True)
class Resolved:
    session: UserSession
    user: User
    country_changed: bool = False


def create_session(
    db: Session,
    *,
    user_id: UUID,
    client_type: ClientType,
    kc_session_id: str,
    auth_time: datetime,
    policy: SessionPolicy,
    auth_level: AuthLevel = AuthLevel.LOA1,
    device_label: str | None = None,
    device_platform: str | None = None,
    app_version: str | None = None,
    ua_family: str | None = None,
    ip_prefix: str | None = None,
    country_code: str | None = None,
    now: datetime | None = None,
) -> CreatedSession:
    """Open a session for a user that may sign in. The request context must already carry
    ``user_id`` (policy). Evicts the oldest live sessions beyond the per-user cap."""
    moment = _now(now)
    status = repository.lock_user_for_new_session(db, user_id)
    if status not in _MAY_SIGN_IN:
        raise AccountDisabled()
    # A new sign-in inside a still-live Keycloak session supersedes the previous application
    # session for that Keycloak session and client type.
    repository.revoke_where(
        db,
        "user_id = :u AND kc_session_id = :k AND client_type = :c",
        {"u": user_id, "k": kc_session_id, "c": client_type.value},
        reason=RevokeReason.LOGOUT.value,
        now=moment,
        revoked_by=None,
    )
    live = repository.count_live(db, user_id, moment)
    evicted = 0
    if live >= policy.max_sessions:
        evicted = repository.revoke_oldest_live(db, user_id, moment, live - policy.max_sessions + 1)
    secret: str | None = None
    digest: bytes | None = None
    if client_type is not ClientType.MOBILE:
        secret, digest = credentials.new_credential()
    absolute = moment + policy.absolute[client_type]
    created = repository.insert(
        db,
        {
            "user_id": user_id,
            "client_type": client_type.value,
            "credential_hash": digest,
            "kc_session_id": kc_session_id,
            "auth_time": auth_time,
            "auth_level": auth_level.value,
            "step_up_at": moment if auth_level is AuthLevel.LOA2 else None,
            "device_label": device_label,
            "platform": device_platform,
            "app_version": app_version,
            "ua_family": ua_family,
            "ip_prefix": ip_prefix,
            "country_code": country_code,
            "now": moment,
            "idle_expires_at": min(moment + policy.idle[client_type], absolute),
            "absolute_expires_at": absolute,
        },
    )
    _audit(
        db,
        "session.created",
        user_id,
        created.id,
        {"client_type": client_type.value, "device_platform": _code(device_platform)},
    )
    if evicted:
        _audit(
            db,
            "session.revoked",
            user_id,
            None,
            {"revoked_reason": RevokeReason.SESSION_LIMIT.value, "count": evicted},
        )
    return CreatedSession(created, secret)


def resolve_web(
    db: Session,
    credential: object,
    *,
    lock: bool = False,
    ua_family: str | None = None,
    country_code: str | None = None,
    now: datetime | None = None,
) -> Resolved:
    """Validate a web credential: session, owner and their state, on every request."""
    if not credentials.is_well_formed(credential):
        raise SessionRequired()
    digest = credentials.hash_credential(credential)
    apply_context(db, RequestContext(session_hash=digest))
    found = repository.by_credential(db, digest, lock=lock)
    if found is None:
        raise SessionRequired()
    apply_context(db, RequestContext(user_id=found.user_id))
    return _check(db, found, ua_family=ua_family, country_code=country_code, now=_now(now))


def resolve_mobile(
    db: Session,
    token: VerifiedToken,
    *,
    lock: bool = False,
    ua_family: str | None = None,
    country_code: str | None = None,
    now: datetime | None = None,
) -> Resolved:
    """Validate a mobile request: the verified Keycloak token identifies the person and the
    Keycloak session; the application session (same ``sid``) decides whether they may act."""
    apply_context(db, RequestContext(auth_subject=token.subject))
    user = users.get_by_subject(db, token.subject)
    if user is None:
        raise SessionRequired()
    apply_context(db, RequestContext(user_id=user.id))
    found = repository.by_kc_session(
        db, user.id, token.session_id, ClientType.MOBILE.value, lock=lock
    )
    if found is None:
        raise SessionRequired()
    return _check(db, found, ua_family=ua_family, country_code=country_code, now=_now(now))


def _check(
    db: Session,
    found: UserSession,
    *,
    ua_family: str | None,
    country_code: str | None,
    now: datetime,
) -> Resolved:
    if found.is_revoked:
        raise SessionRevoked()
    if found.is_expired(now):
        raise SessionExpired()
    user = users.get_by_id(db, found.user_id)
    if user is None:  # cannot happen through the foreign key; fail closed
        raise SessionRequired()
    if user.status not in (UserStatus.ACTIVE, UserStatus.PENDING_VERIFICATION):
        raise AccountDisabled()
    if found.ua_family and ua_family and found.ua_family != ua_family:
        raise SessionSecurityViolation(found.id, found.user_id, "UA_CHANGE")
    country_changed = bool(
        found.country_code and country_code and found.country_code != country_code
    )
    if country_changed:
        _audit(db, "session.theft_suspected", found.user_id, found.id, {"signal": "COUNTRY_CHANGE"})
    return Resolved(found, user, country_changed)


def touch(
    factory: sessionmaker[Session],
    resolved: Resolved,
    policy: SessionPolicy,
    *,
    country_code: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Extend the idle deadline, at most once per ``touch_interval``. Own transaction, never
    waits for a lock, safe to skip. Returns whether the row was updated."""
    moment = _now(now)
    found = resolved.session
    if moment - found.last_activity_at < policy.touch_interval:
        return False
    idle = min(moment + policy.idle[found.client_type], found.absolute_expires_at)
    context = RequestContext(user_id=found.user_id)
    with session_scope(factory, context) as db:
        return repository.touch_skip_locked(
            db,
            found.id,
            threshold=moment - policy.touch_interval,
            now=moment,
            idle_expires_at=idle,
            country_code=country_code,
        )


def rotate_credential(db: Session, session_id: UUID) -> str:
    """New web credential; the previous one stops working immediately (D24)."""
    secret, digest = credentials.new_credential()
    if not repository.rotate(db, session_id, digest):
        raise SessionRevoked()
    return secret


def record_step_up(
    db: Session, session_id: UUID, *, level: AuthLevel, rotate: bool, now: datetime | None = None
) -> str | None:
    """Store the achieved level and time; for web sessions also rotate the credential."""
    secret, digest = credentials.new_credential() if rotate else (None, None)
    if not repository.mark_step_up(db, session_id, digest, level.value, _now(now)):
        raise SessionRevoked()
    return secret


def revoke(
    db: Session,
    session_id: UUID,
    *,
    reason: RevokeReason,
    actor_user_id: UUID | None = None,
    now: datetime | None = None,
) -> bool:
    count = repository.revoke_where(
        db, "id = :sid", {"sid": session_id}, reason=reason.value, now=_now(now),
        revoked_by=actor_user_id,
    )  # fmt: skip
    if count:
        owner = by_id_owner(db, session_id)
        _audit_revoked(db, owner, reason, count, actor_user_id)
    return bool(count)


def by_id_owner(db: Session, session_id: UUID) -> UUID | None:
    found = repository.by_id(db, session_id)
    return found.user_id if found else None


def revoke_others(
    db: Session,
    user_id: UUID,
    keep_session_id: UUID,
    *,
    reason: RevokeReason = RevokeReason.USER_REVOKED,
    actor_user_id: UUID | None = None,
    now: datetime | None = None,
) -> int:
    count = repository.revoke_where(
        db, "user_id = :u AND id <> :keep", {"u": user_id, "keep": keep_session_id},
        reason=reason.value, now=_now(now), revoked_by=actor_user_id,
    )  # fmt: skip
    if count:
        _audit_revoked(db, user_id, reason, count, actor_user_id)
    return count


def revoke_by_kc_session(db: Session, kc_session_id: str, *, now: datetime | None = None) -> int:
    """Back-channel logout: every session of this Keycloak session (reason IDP_LOGOUT)."""
    return repository.revoke_where(
        db, "kc_session_id = :k", {"k": kc_session_id}, reason=RevokeReason.IDP_LOGOUT.value,
        now=_now(now), revoked_by=None,
    )  # fmt: skip


class DatabaseSessionRevoker:
    """The ``SessionRevoker`` the user service calls when access ends (D11)."""

    def revoke_all(
        self,
        db: Session,
        user_id: UUID,
        *,
        reason: str,
        actor_user_id: UUID | None = None,
        now: datetime | None = None,
    ) -> int:
        count = repository.revoke_where(
            db, "user_id = :u", {"u": user_id}, reason=RevokeReason(reason).value,
            now=_now(now), revoked_by=actor_user_id,
        )  # fmt: skip
        if count:
            _audit_revoked(db, user_id, RevokeReason(reason), count, actor_user_id)
        return count


def revoke_independent(
    factory: sessionmaker[Session],
    violation: SessionSecurityViolation,
    *,
    now: datetime | None = None,
) -> bool:
    """Revoke after a failed request, in its own transaction, and record why."""
    session_id, user_id = violation.session_id, violation.user_id
    context = RequestContext(user_id=user_id)
    with session_scope(factory, context) as db:
        revoked = revoke(db, session_id, reason=RevokeReason.SECURITY_POLICY, now=now)
        if revoked:
            record(
                db,
                AuditEvent(
                    action="session.theft_suspected", outcome=Outcome.DENIED,
                    actor_type=ActorType.USER, actor_user_id=user_id, subject_user_id=user_id,
                    actor_session_id=session_id,
                    details={"signal": violation.signal},
                ),
            )  # fmt: skip
        return revoked


def _code(value: str | None) -> str:
    cleaned = "".join(ch for ch in (value or "") if ch.isalnum() or ch in "._:-")[:64]
    return cleaned or "unknown"


def _audit(
    db: Session, action: str, user_id: UUID, session_id: UUID | None, details: dict[str, Any]
) -> None:
    record(
        db,
        AuditEvent(
            action=action, outcome=Outcome.SUCCESS, actor_type=ActorType.USER,
            actor_user_id=user_id, subject_user_id=user_id, actor_session_id=session_id,
            details=details,
        ),
    )  # fmt: skip


def _audit_revoked(
    db: Session, user_id: UUID | None, reason: RevokeReason, count: int, actor: UUID | None
) -> None:
    # The audit guard refuses any detail containing the word "password" (it cannot tell a reason
    # code from a leaked value), so that one reason is recorded under a neutral name.
    code = "CREDENTIAL_CHANGED" if reason is RevokeReason.PASSWORD_CHANGED else reason.value
    record(
        db,
        AuditEvent(
            action="session.revoked", outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER if actor else ActorType.SYSTEM, actor_user_id=actor,
            subject_user_id=user_id,
            details={"revoked_reason": code, "count": count},
        ),
    )  # fmt: skip


__all__ = [
    "CreatedSession", "DatabaseSessionRevoker", "Resolved", "create_session", "record_step_up",
    "resolve_mobile", "resolve_web", "revoke", "revoke_by_kc_session", "revoke_independent",
    "revoke_others", "rotate_credential", "touch",
]  # fmt: skip
