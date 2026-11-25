"""Platform authorization (F2-T10; AT-02 8.1-8.4, decisions D28, D22, D23, I14, I17).

Deny by default. A platform action is allowed only inside a transaction of the platform
database role in which

1. the caller's own grant of the required type is read from the database and share-locked, so a
   revocation waits for this transaction and every later request sees it (TOCTOU, 8.3.6);
2. the caller proved a second factor recently enough (level two, ten minutes; five for grant
   changes), measured from the proof itself (F-2), checked by the route guard;
3. the use is written to ``audit_events`` in the same transaction (I14, AC-PLT-10).

Nothing here reads a token claim or a cookie for authority, and nothing is cached. The
``Authority`` object exists only while that transaction is open; the authorities that other
packages need (F-4 review, controlled recovery) are derived from it and fail closed."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.idp import IdentityProviderAdmin, IdpAdminError
from app.auth.security.email_change_review import ReviewDecision
from app.core.errors import Forbidden
from app.platform import repository
from app.platform.models import GRANT_CHANGE_STEP_UP_SECONDS, GrantType, PlatformGrant
from sqlalchemy.orm import Session


class PlatformDenied(Forbidden):
    """403 FORBIDDEN without detail. ``reason`` is recorded in the audit trail only."""

    def __init__(self, reason: str, *, expired_grant: PlatformGrant | None = None) -> None:
        super().__init__()
        self.reason = reason
        self.expired_grant = expired_grant


@dataclass
class Authority:
    """A verified, share-locked grant of the caller inside an open platform transaction."""

    db: Session
    actor_id: UUID
    actor_session_id: UUID
    grant: PlatformGrant
    second_factor_at: datetime  # when the caller's second factor was proven (level two)
    _open: list[bool] = field(default_factory=lambda: [True], repr=False)

    @property
    def is_open(self) -> bool:
        return self._open[0]

    def close(self) -> None:
        self._open[0] = False

    def still_holds(self, grant_type: GrantType) -> bool:
        """Open, of this type and still active in the database (asked again, not cached)."""
        return (
            self.is_open
            and self.grant.grant_type is grant_type
            and repository.holds(self.db, grant_type)
        )

    def fresh(self, now: datetime, seconds: int) -> bool:
        return timedelta(0) <= now - self.second_factor_at <= timedelta(seconds=seconds)


def acquire(db: Session, actor_id: UUID, grant_type: GrantType) -> PlatformGrant:
    """Step 1: the caller's own active grant of ``grant_type``, share-locked, or ``PlatformDenied``
    (with the expired grant, if that is why)."""
    held = repository.hold_own(db, actor_id, grant_type)
    if held is None:
        raise PlatformDenied(
            "PLATFORM_GRANT", expired_grant=repository.own_expired(db, actor_id, grant_type)
        )
    return held


def establish(
    db: Session,
    *,
    held: PlatformGrant,
    actor_id: UUID,
    actor_session_id: UUID,
    second_factor_at: datetime,
    ip_prefix: str | None,
    ua_family: str | None,
) -> Authority:
    """Step 2, after the step-up check: a grant administrator may now see the grants of others
    (``app.grant_authority``), and the use of the grant is recorded in this transaction."""
    if held.grant_type is GrantType.PLATFORM_GRANT_ADMIN:
        repository.set_authority(db, held.id)
    record(
        db,
        AuditEvent(
            action="authz.platform_grant.used",
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER,
            actor_user_id=actor_id,
            actor_session_id=actor_session_id,
            subject_user_id=actor_id,
            target_type="platform_grant",
            target_id=held.id,
            ip_prefix=ip_prefix,
            ua_family=ua_family,
            details={"grant_type": held.grant_type.value, "grant_id": held.id},
        ),
    )
    return Authority(db, actor_id, actor_session_id, held, second_factor_at)


# --- authorities for other packages ------------------------------------------------------------
class GrantReviewAuthority:
    """F-4 (D37 ``MANUAL_REVIEW``) authority of the ``ReviewAuthority`` port: a person holding
    ``PLATFORM_USER_ADMIN`` with level two proven within five minutes, inside the open platform
    transaction that share-locks that grant. The privileged interface is F2-T11; nothing calls
    this before it."""

    def __init__(self, authority: Authority, now: datetime) -> None:
        self._authority, self._now = authority, now

    def permits(self, db: Session, operation_id: UUID, decision: ReviewDecision) -> bool:
        return self._authority.fresh(
            self._now, GRANT_CHANGE_STEP_UP_SECONDS
        ) and self._authority.still_holds(GrantType.PLATFORM_USER_ADMIN)


def authorize_account_recovery(
    authority: Authority,
    admin: IdentityProviderAdmin | None,
    *,
    target_user_id: UUID,
    target_subject: str,
    now: datetime,
) -> None:
    """Authority for the controlled recovery of a locked account (an obliged account without a
    usable factor, D41/D44). What the recovery does is the T11 interface; this only decides who
    may start it, and refuses by default:

    * the caller holds ``PLATFORM_ACCOUNT_RECOVERY`` (database, share-locked) with level two
      proven within five minutes, and is not the person to recover;
    * the account is not one whose second factor is mandatory (platform-grant holders, present
      or former): recovering it could hand a platform privilege to whoever recovers it;
    * the identity provider can answer (otherwise nothing is allowed)."""
    if (
        target_user_id == authority.actor_id
        or not authority.fresh(now, GRANT_CHANGE_STEP_UP_SECONDS)
        or not authority.still_holds(GrantType.PLATFORM_ACCOUNT_RECOVERY)
    ):
        raise PlatformDenied("ACCOUNT_RECOVERY")
    if admin is None:
        raise PlatformDenied("ACCOUNT_RECOVERY")
    try:
        mandatory = admin.is_factor_mandatory(target_subject)
    except IdpAdminError:
        raise PlatformDenied("ACCOUNT_RECOVERY") from None
    if mandatory:
        raise PlatformDenied("ACCOUNT_RECOVERY")
