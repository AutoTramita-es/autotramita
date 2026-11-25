"""Managing platform grants (F2-T10; AT-02 8.2-8.3, decisions D22, D28, D29).

Every operation runs inside an ``Authority`` of ``PLATFORM_GRANT_ADMIN`` (one platform-role
transaction, the caller's grant share-locked, level two within five minutes) and records its
audit events in that transaction. The database checks the same rules again (0010).

Escalation rules:

* nobody grants to, approves for or rejects for themselves;
* ``PLATFORM_GRANT_ADMIN`` and ``PLATFORM_USER_ADMIN`` always wait for a second administrator,
  who is neither the requester nor the beneficiary (four eyes);
* any other type takes effect at once only if the requester holds that type; otherwise it waits
  for a second administrator too (no administrator creates a privilege they do not hold);
* a grant takes effect only for an active account that has a permanent second factor (one-time
  code or passkey) at the identity provider, and only after the provider marked the account
  ``at_mfa_mandatory``: from then on the factor cannot be switched off and the account never
  falls back to the password alone (D22, D44). Recovery codes alone are not enough;
* the last active grant administrator is never revoked (anti-lockout);
* one live grant per person and type: a repeated request, approval or revocation answers 409.

Identity-provider calls happen inside the transaction on purpose: either the grant takes effect
together with a confirmed factor and mark, or nothing is stored. A mark set before a failed
commit stays (the safe direction); T10 never removes a mark."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.errors import AuthNotConfigured, IdentityProviderUnavailable, NoSecondFactor
from app.auth.idp import PERMANENT_FACTOR_TYPES, IdentityProviderAdmin, IdpAdminError
from app.core.errors import NotFound, UnprocessableEntity
from app.platform import repository
from app.platform.authz import Authority, PlatformDenied
from app.platform.errors import GrantConflict, LastGrantAdmin
from app.platform.models import (
    CALLER_REVOKE_REASONS,
    FOUR_EYES,
    MAX_LIFETIME,
    SCOPED_TYPES,
    GrantStatus,
    GrantType,
    PlatformGrant,
    RevokeReason,
    ScopeKind,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _audit(
    authority: Authority,
    action: str,
    grant: PlatformGrant,
    *,
    ip_prefix: str | None,
    ua_family: str | None,
    reason_code: str | None = None,
    source_event_id: str | None = None,
) -> None:
    record(
        authority.db,
        AuditEvent(
            action=action,
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER,
            actor_user_id=authority.actor_id,
            actor_session_id=authority.actor_session_id,
            subject_user_id=grant.user_id,
            target_type="platform_grant",
            target_id=grant.id,
            ip_prefix=ip_prefix,
            ua_family=ua_family,
            reason_code=reason_code,
            source_event_id=source_event_id,
            details={"grant_type": grant.grant_type.value, "grant_id": grant.id},
        ),
    )


def expiry_event_id(grant_id: UUID) -> str:
    """Deduplication key of the one ``authz.platform_grant.expired`` record of a grant."""
    return f"grant-expired:{grant_id}"


def _require_administrator(authority: Authority) -> Session:
    if not authority.is_open or authority.grant.grant_type is not GrantType.PLATFORM_GRANT_ADMIN:
        raise PlatformDenied("PLATFORM_GRANT")
    return authority.db


def require_permanent_factor(admin: IdentityProviderAdmin | None, subject: str) -> None:
    """The beneficiary has a one-time code or passkey, the provider marks the account so that it
    must keep it, and the factor is still there afterwards. Fails closed."""
    if admin is None:
        raise AuthNotConfigured("Platform administration is not configured.")
    detail = "The person needs a one-time code or passkey before a platform grant takes effect."
    try:
        if not any(c.type in PERMANENT_FACTOR_TYPES for c in admin.list_credentials(subject)):
            raise NoSecondFactor(detail)
        admin.set_factor_mandatory(subject)
        if not any(c.type in PERMANENT_FACTOR_TYPES for c in admin.list_credentials(subject)):
            raise NoSecondFactor(detail)
    except IdpAdminError:
        raise IdentityProviderUnavailable() from None


def _active_beneficiary(db: Session, user_id: UUID) -> str:
    found = repository.beneficiary(db, user_id)
    if found is None or found[1] != "ACTIVE":
        raise GrantConflict("A platform grant needs an active account.")
    return found[0]


def _validate(
    grant_type: GrantType,
    expires_at: datetime,
    scope_kind: ScopeKind,
    scope_tenant_ids: Sequence[UUID] | None,
    queue: str | None,
    now: datetime,
) -> None:
    if expires_at.tzinfo is None or expires_at <= now:
        raise UnprocessableEntity("expires_at must be a future UTC time.")
    if expires_at - now > MAX_LIFETIME[grant_type]:
        raise UnprocessableEntity("expires_at is beyond the longest lifetime of this grant type.")
    if scope_kind is ScopeKind.ALL:
        ok = not scope_tenant_ids and queue is None
    elif scope_kind is ScopeKind.TENANTS:
        ok = grant_type in SCOPED_TYPES and bool(scope_tenant_ids) and queue is None
    else:
        ok = grant_type in SCOPED_TYPES and queue is not None and not scope_tenant_ids
    if not ok:
        raise UnprocessableEntity("Only the verification reviewer has a narrower scope.")


def request_grant(
    authority: Authority,
    admin: IdentityProviderAdmin | None,
    *,
    user_id: UUID,
    grant_type: GrantType,
    expires_at: datetime,
    reason: str,
    scope_kind: ScopeKind,
    scope_tenant_ids: Sequence[UUID] | None,
    queue: str | None,
    now: datetime,
    ip_prefix: str | None = None,
    ua_family: str | None = None,
) -> PlatformGrant:
    db = _require_administrator(authority)
    if user_id == authority.actor_id:
        raise PlatformDenied("SELF_GRANT")
    _validate(grant_type, expires_at, scope_kind, scope_tenant_ids, queue, now)
    facts = {"ip_prefix": ip_prefix, "ua_family": ua_family}
    existing = repository.live_for(db, user_id, grant_type)
    if existing is not None:
        if existing.expires_at > now:
            raise GrantConflict("A live grant of this type exists for this person.")
        closed = repository.revoke(db, existing.id, authority.actor_id, RevokeReason.EXPIRED)
        _audit(
            authority,
            "authz.platform_grant.expired",
            closed,
            source_event_id=expiry_event_id(closed.id),
            **facts,
        )
    at_once = grant_type not in FOUR_EYES and repository.holds(db, grant_type)
    try:
        with db.begin_nested():
            grant = repository.insert(
                db,
                user_id=user_id,
                grant_type=grant_type,
                scope_kind=scope_kind,
                scope_tenant_ids=scope_tenant_ids,
                queue=queue,
                status=GrantStatus.ACTIVE if at_once else GrantStatus.PENDING_APPROVAL,
                expires_at=expires_at,
                granted_by=authority.actor_id,
                reason=reason,
            )
    except IntegrityError:
        # A concurrent request won, or the person does not exist or is not active.
        raise GrantConflict("This grant cannot be requested now.") from None
    _audit(authority, "authz.platform_grant.requested", grant, **facts)
    if grant.status is GrantStatus.ACTIVE:
        require_permanent_factor(admin, _active_beneficiary(db, user_id))
        _audit(authority, "authz.platform_grant.activated", grant, **facts)
    return grant


def _decidable(db: Session, grant_id: UUID, now: datetime) -> PlatformGrant:
    grant = repository.lock(db, grant_id)
    if grant is None:
        raise NotFound()
    if grant.status is not GrantStatus.PENDING_APPROVAL or grant.expires_at <= now:
        raise GrantConflict("This request is not waiting for a decision.")
    return grant


def _holds(db: Session, user_id: UUID | None, grant_type: GrantType) -> bool:
    if user_id is None:
        return False
    return bool(
        db.execute(
            text(
                "SELECT EXISTS (SELECT 1 FROM platform_grants WHERE user_id = :u "
                "AND grant_type = :t AND status = 'ACTIVE' AND expires_at > now())"
            ),
            {"u": user_id, "t": grant_type.value},
        ).scalar_one()
    )


def approve(
    authority: Authority,
    admin: IdentityProviderAdmin | None,
    grant_id: UUID,
    *,
    now: datetime,
    ip_prefix: str | None = None,
    ua_family: str | None = None,
) -> PlatformGrant:
    db = _require_administrator(authority)
    grant = _decidable(db, grant_id, now)
    if authority.actor_id in (grant.granted_by, grant.user_id):
        raise PlatformDenied("FOUR_EYES")
    if not _holds(db, grant.granted_by, GrantType.PLATFORM_GRANT_ADMIN):
        raise GrantConflict("The requester no longer administers grants.")
    require_permanent_factor(admin, _active_beneficiary(db, grant.user_id))
    approved = repository.approve(db, grant.id, authority.actor_id)
    facts = {"ip_prefix": ip_prefix, "ua_family": ua_family}
    _audit(authority, "authz.platform_grant.approved", approved, **facts)
    _audit(authority, "authz.platform_grant.activated", approved, **facts)
    return approved


def reject(
    authority: Authority,
    grant_id: UUID,
    *,
    now: datetime,
    ip_prefix: str | None = None,
    ua_family: str | None = None,
) -> PlatformGrant:
    db = _require_administrator(authority)
    grant = _decidable(db, grant_id, now)
    if authority.actor_id in (grant.granted_by, grant.user_id):
        raise PlatformDenied("FOUR_EYES")
    rejected = repository.revoke(db, grant.id, authority.actor_id, RevokeReason.REJECTED)
    _audit(
        authority,
        "authz.platform_grant.rejected",
        rejected,
        ip_prefix=ip_prefix,
        ua_family=ua_family,
    )
    return rejected


def revoke(
    authority: Authority,
    grant_id: UUID,
    reason: RevokeReason,
    *,
    now: datetime,
    ip_prefix: str | None = None,
    ua_family: str | None = None,
) -> PlatformGrant:
    """Any grant administrator ends any pending or active grant at once (removing a privilege
    never needs four eyes), except the last active grant administrator."""
    db = _require_administrator(authority)
    if reason not in CALLER_REVOKE_REASONS:
        raise UnprocessableEntity("This revocation reason cannot be chosen.")
    grant = repository.lock(db, grant_id)
    if grant is None:
        raise NotFound()
    if grant.status is GrantStatus.REVOKED:
        raise GrantConflict("This grant has already ended.")
    if grant.grant_type is GrantType.PLATFORM_GRANT_ADMIN and grant.active_at(now):
        repository.lock_administrators(db)
        if repository.other_administrators(db, grant.user_id) == 0:
            raise LastGrantAdmin()
    revoked = repository.revoke(db, grant.id, authority.actor_id, reason)
    _audit(
        authority,
        "authz.platform_grant.revoked",
        revoked,
        reason_code=reason.value,
        ip_prefix=ip_prefix,
        ua_family=ua_family,
    )
    return revoked


def notice_address(authority: Authority, user_id: UUID) -> str | None:
    """E-mail of the person a grant names, for the notice after the commit (D27)."""
    row = authority.db.execute(
        text("SELECT email FROM users WHERE id = :u"), {"u": user_id}
    ).one_or_none()
    return str(row.email) if row else None
