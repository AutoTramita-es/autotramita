"""Password recovery and the security effects around it (F2-T09; D20, D22, D23, D26, D27).

Recovery is owned by the application because Keycloak cannot limit reset e-mails per account:
the endpoint always answers the same ``202`` after the same amount of synchronous work (one
Redis check); everything that depends on the account — the look-up, the e-mail, the audit
record — happens after the response. Accounts that cannot sign in receive nothing."""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.errors import AuthNotConfigured
from app.auth.idp import IdpAdminError
from app.auth.runtime import AuthRuntime
from app.auth.security.notify import Notice, NoticeKind, send_quietly
from app.auth.sessions import service as sessions
from app.auth.sessions.models import RevokeReason
from app.auth.users import repository as user_repository
from app.auth.users.models import UserStatus
from app.core.db import RequestContext, session_scope
from app.core.errors import ServiceUnavailable
from app.core.ratelimit import Policy, RateLimiter
from fastapi import Request

log = logging.getLogger(__name__)
RECOVERY_ACTIONS = ("UPDATE_PASSWORD",)
VERIFY_ACTIONS = ("VERIFY_EMAIL",)


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


def after_sign_in(
    rt: AuthRuntime, *, subject: str, user_id: UUID, email: str, keep_session_id: UUID
) -> None:
    """If a recovery was started for this person and the password really changed since, end
    every other session and say so (D20). Best effort: a provider outage only postpones it —
    the marker stays, so the next sign-in tries again."""
    if rt.admin is None or rt.markers is None:
        return
    requested = rt.markers.get(subject)
    if requested is None:
        return
    try:
        passwords = [c for c in rt.admin.list_credentials(subject) if c.type == "password"]
    except IdpAdminError:
        log.warning("password change check postponed")
        return
    changed = any(c.created_ms is not None and c.created_ms / 1000 >= requested for c in passwords)
    if not changed:
        return
    with session_scope(rt.factory, RequestContext(user_id=user_id)) as db:
        sessions.revoke_others(
            db, user_id, keep_session_id, reason=RevokeReason.PASSWORD_CHANGED, actor_user_id=None
        )
        record(
            db,
            AuditEvent(
                action="security.password.changed",
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.USER,
                actor_user_id=user_id,
                subject_user_id=user_id,
                actor_session_id=keep_session_id,
                details={},
            ),
        )
    rt.markers.clear(subject)
    send_quietly(
        rt.notifier,
        Notice(NoticeKind.PASSWORD_RESET_COMPLETED, email, datetime.now(UTC)),
    )
