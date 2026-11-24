"""Password recovery and the security effects around it (F2-T09; D20, D22, D23, D26, D27).

Recovery is owned by the application because Keycloak cannot limit reset e-mails per account:
the endpoint always answers the same ``202`` after the same amount of synchronous work (one
Redis check); everything that depends on the account — the look-up, the e-mail, the audit
record — happens after the response. Accounts that cannot sign in receive nothing."""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.errors import AuthNotConfigured
from app.auth.idp import IdpAdminError, IdpCredential
from app.auth.runtime import AuthRuntime
from app.auth.security.markers import Marker
from app.auth.security.notify import Notice, NoticeKind, SecurityNotifier, send_quietly
from app.auth.sessions import service as sessions
from app.auth.sessions.models import RevokeReason
from app.auth.users import repository as user_repository
from app.auth.users.models import UserStatus
from app.core.db import RequestContext, session_scope
from app.core.errors import ServiceUnavailable
from app.core.ratelimit import Policy, RateLimiter
from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)
RECOVERY_ACTIONS = ("UPDATE_PASSWORD",)
VERIFY_ACTIONS = ("VERIFY_EMAIL",)
# Both times come from the identity provider; ``auth_time`` is truncated to whole seconds.
AUTH_TIME_TOLERANCE_SECONDS = 2
# After the recovery link expired, a password form opened with it can still be submitted for a
# while (Keycloak's own login timeouts, 30 minutes); the periodic check outlasts that.
PENDING_CHECK_MARGIN_SECONDS = 3600


def limiter_of(request: Request) -> RateLimiter:
    limiter: RateLimiter | None = request.app.state.rate_limiter
    if limiter is None:  # misconfiguration must never mean "unlimited"
        raise ServiceUnavailable(
            "Request limiting is temporarily unavailable.",
            code="RATE_LIMIT_UNAVAILABLE",
            headers={"Retry-After": "5"},
        )
    return limiter


def account_identity(rt: AuthRuntime, purpose: str, value: str) -> str:
    """HMAC of an account identifier: the limiter never holds an address in clear (D20)."""
    key = rt.settings.security_hmac_key
    if key is None:
        raise AuthNotConfigured("Security endpoints are not configured.")
    mac = hmac.new(key.get_secret_value().encode(), f"{purpose}:{value}".encode(), hashlib.sha256)
    return f"{purpose}:{mac.hexdigest()}"


def account_allowed(
    rt: AuthRuntime, limiter: RateLimiter, policy_name: str, limit: int, value: str
) -> bool:
    decision = limiter.check(
        Policy(policy_name, limit, 3600), account_identity(rt, policy_name, value)
    )
    return decision.allowed


def _redirect(rt: AuthRuntime) -> str:
    return f"{rt.settings.web_origin or ''}/"


def process_recovery(
    rt: AuthRuntime,
    email: str,
    *,
    allowed: bool,
    ip_prefix: str | None,
    ua_family: str | None,
) -> None:
    """Runs after the ``202`` was sent. Never raises (it has nobody to tell)."""
    try:
        _process_recovery(rt, email, allowed, ip_prefix, ua_family)
    except Exception:
        log.warning("password recovery processing failed")


def _process_recovery(
    rt: AuthRuntime, email: str, allowed: bool, ip_prefix: str | None, ua_family: str | None
) -> None:
    if rt.admin is None or rt.markers is None:
        return
    if not allowed:
        rt.record_anonymous(
            "security.password.recovery.limited", Outcome.DENIED, ip_prefix, ua_family,
            {"limit": "ACCOUNT"},
        )  # fmt: skip
        return
    found = rt.admin.find_user_by_email(email)
    if found is None or not found.enabled:
        rt.record_anonymous(
            "security.password.recovery.requested", Outcome.DENIED, ip_prefix, ua_family, {}
        )
        return
    with session_scope(rt.factory, RequestContext(auth_subject=found.subject)) as db:
        known = user_repository.get_by_subject(db, found.subject)
        if known is not None and known.status not in (
            UserStatus.ACTIVE,
            UserStatus.PENDING_VERIFICATION,
        ):
            record(
                db,
                AuditEvent(
                    action="security.password.recovery.requested",
                    outcome=Outcome.DENIED,
                    actor_type=ActorType.ANONYMOUS,
                    subject_user_id=known.id,
                    ip_prefix=ip_prefix,
                    ua_family=ua_family,
                    details={},
                ),
            )
            return
        sent_at = rt.clock()
        rt.admin.send_actions_email(
            found.subject,
            RECOVERY_ACTIONS,
            lifespan_seconds=rt.settings.recovery_link_minutes * 60,
            redirect_uri=_redirect(rt),
        )
        rt.markers.mark(found.subject, sent_at)
        record(
            db,
            AuditEvent(
                action="security.password.recovery.requested",
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.ANONYMOUS,
                subject_user_id=known.id if known else None,
                ip_prefix=ip_prefix,
                ua_family=ua_family,
                details={},
            ),
        )


def process_verification_resend(rt: AuthRuntime, user_id: UUID, subject: str) -> None:
    """Resend Keycloak's verification link to a person who has not verified yet."""
    try:
        if rt.admin is not None:
            rt.admin.send_actions_email(
                subject,
                VERIFY_ACTIONS,
                lifespan_seconds=rt.settings.recovery_link_minutes * 60,
                redirect_uri=_redirect(rt),
            )
    except Exception:
        log.warning("verification resend failed")


def _end_sessions_of_old_password(
    db: Session, user_id: UUID, changed: float, *, signed_in_session: UUID | None
) -> bool:
    """End the sessions that rest on an authentication older than the new password and record
    the change. ``True`` for whoever records this change first: the audit record carries a
    deduplication key of the change, so a sweep and a sign-in racing each other, or a repeated
    attempt, give one record and one notice."""
    sessions.revoke_authenticated_before(
        db,
        user_id,
        datetime.fromtimestamp(changed - AUTH_TIME_TOLERANCE_SECONDS, tz=UTC),
        reason=RevokeReason.PASSWORD_CHANGED,
    )
    change = hashlib.sha256(f"{user_id}/{round(changed * 1000)}".encode()).hexdigest()[:32]
    by_person = signed_in_session is not None
    return record(
        db,
        AuditEvent(
            action="security.password.changed",
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER if by_person else ActorType.SYSTEM,
            actor_user_id=user_id if by_person else None,
            subject_user_id=user_id,
            actor_session_id=signed_in_session,
            details={},
            source_event_id=f"pwc-{change}",
        ),
    )


def _unhandled(marker: Marker, changed: float | None) -> bool:
    return (
        changed is not None
        and changed >= marker.requested
        and (marker.handled is None or changed > marker.handled)
    )


def _send_reset_notice(notifier: SecurityNotifier, email: str) -> None:
    send_quietly(notifier, Notice(NoticeKind.PASSWORD_RESET_COMPLETED, email, datetime.now(UTC)))


def after_sign_in(
    rt: AuthRuntime,
    *,
    subject: str,
    user_id: UUID,
    email: str,
    keep_session_id: UUID,
    auth_time: int | None,
) -> bool:
    """React to a password change at sign-in (D20). ``False`` means this sign-in must not stand
    because the person authenticated *before* the password changed.

    If nobody has acted on the change yet, every session older than it ends and the person is
    told. A sign-in resting on an old authentication is ended in any case. Best effort: a
    provider outage only postpones the check, the marker stays and the next one tries again."""
    if rt.admin is None or rt.markers is None:
        return True
    marker = rt.markers.get(subject)
    if marker is None:
        return True
    try:
        changed = latest_password(rt.admin.list_credentials(subject))
    except IdpAdminError:
        log.warning("password change check postponed")
        return True
    if changed is None or changed < marker.requested:
        return True
    stale = auth_time is None or auth_time < changed - AUTH_TIME_TOLERANCE_SECONDS
    unhandled = _unhandled(marker, changed)
    if not unhandled and not stale:
        return True
    first = False
    with session_scope(rt.factory, RequestContext(user_id=user_id)) as db:
        if unhandled:
            first = _end_sessions_of_old_password(
                db, user_id, changed, signed_in_session=keep_session_id
            )
        if stale:
            sessions.revoke(db, keep_session_id, reason=RevokeReason.PASSWORD_CHANGED)
    rt.markers.record_change(subject, changed)
    if first:
        _send_reset_notice(rt.notifier, email)
    return not stale


def check_pending_password_changes(
    rt: AuthRuntime,
    factory: sessionmaker[Session],
    notifier: SecurityNotifier,
    *,
    should_stop: Callable[[], bool] = lambda: False,
) -> None:
    """The periodic check (F-0, run by the 60 s worker under the worker database role): for
    everybody with a recent recovery request, ask the provider whether the password changed and,
    if so, end the sessions of the old password without waiting for a sign-in.

    A person is looked at until the recovery link, and a form opened with it, can no longer
    change the password, and only dropped after a check made after that moment succeeded. One
    person's failure does not delay the others."""
    if rt.admin is None or rt.markers is None:
        return
    window = rt.settings.recovery_link_minutes * 60 + PENDING_CHECK_MARGIN_SECONDS
    failed = 0
    for subject, requested in rt.markers.pending():
        if should_stop():
            return
        try:
            checked_at = rt.clock()
            marker = rt.markers.read(subject)
            if marker is None:  # the marker expired: nothing is left to compare with
                rt.markers.forget_pending(subject, requested)
                continue
            _check_one(rt, factory, notifier, subject, marker)
            if checked_at > requested + window:
                rt.markers.forget_pending(subject, requested)
        except Exception:
            failed += 1  # stays pending; no identifier or provider message is logged
    if failed:
        log.warning("password change checks postponed", extra={"fields": {"count": failed}})


def _check_one(
    rt: AuthRuntime,
    factory: sessionmaker[Session],
    notifier: SecurityNotifier,
    subject: str,
    marker: Marker,
) -> None:
    assert rt.admin is not None and rt.markers is not None  # noqa: S101
    with session_scope(factory, RequestContext()) as db:
        user = user_repository.get_by_subject(db, subject)
    if user is None:  # never signed in here: no session to end
        return
    changed = latest_password(rt.admin.list_credentials(subject))
    if changed is None or not _unhandled(marker, changed):
        return
    with session_scope(factory, RequestContext()) as db:
        first = _end_sessions_of_old_password(db, user.id, changed, signed_in_session=None)
    rt.markers.record_change(subject, changed)
    if first:
        _send_reset_notice(notifier, user.email)


def latest_password(credentials: list[IdpCredential]) -> float | None:
    """Creation time (seconds) of the newest password credential the provider lists."""
    created = [
        c.created_ms for c in credentials if c.type == "password" and c.created_ms is not None
    ]
    return max(created) / 1000 if created else None
