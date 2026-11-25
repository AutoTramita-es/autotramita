"""Platform grant model (F2-T10; AT-02 section 8.2, decisions D28 and D29). Plain data.

The catalog is closed: five types, no inheritance and no "super" type. A grant never follows
from a tenant role, and a tenant role never follows from a grant (ADR-003, AC-AUTHZ-03)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID


class GrantType(StrEnum):
    PLATFORM_GRANT_ADMIN = "PLATFORM_GRANT_ADMIN"  # grants, approvals, revocations
    PLATFORM_USER_ADMIN = "PLATFORM_USER_ADMIN"  # account status and sessions (routes: T11)
    PLATFORM_AUDIT_VIEW = "PLATFORM_AUDIT_VIEW"  # reading the audit trail (route: T11)
    PLATFORM_VERIFICATION_REVIEW = "PLATFORM_VERIFICATION_REVIEW"  # contract only; effect F3a
    PLATFORM_ACCOUNT_RECOVERY = "PLATFORM_ACCOUNT_RECOVERY"  # authority only; interface T11


class GrantStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"  # expiry is not a status: it follows from ``expires_at``


class ScopeKind(StrEnum):
    ALL = "ALL"
    TENANTS = "TENANTS"  # verification reviewer only
    QUEUE = "QUEUE"  # verification reviewer only


class RevokeReason(StrEnum):
    NO_LONGER_NEEDED = "NO_LONGER_NEEDED"
    ROLE_CHANGED = "ROLE_CHANGED"
    SECURITY_INCIDENT = "SECURITY_INCIDENT"
    WITHDRAWN = "WITHDRAWN"  # a pending request taken back
    # Set by the service, never chosen by a caller:
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"  # an expired live row closed so that a new grant can be made


CALLER_REVOKE_REASONS = frozenset(
    {
        RevokeReason.NO_LONGER_NEEDED,
        RevokeReason.ROLE_CHANGED,
        RevokeReason.SECURITY_INCIDENT,
        RevokeReason.WITHDRAWN,
    }
)

# A second grant administrator always approves these (four eyes, AT-02 8.2).
FOUR_EYES = frozenset({GrantType.PLATFORM_GRANT_ADMIN, GrantType.PLATFORM_USER_ADMIN})
MAX_LIFETIME = {t: timedelta(days=365) for t in GrantType} | {
    GrantType.PLATFORM_VERIFICATION_REVIEW: timedelta(days=90)
}
BOOTSTRAP_LIFETIME = timedelta(days=90)
SCOPED_TYPES = frozenset({GrantType.PLATFORM_VERIFICATION_REVIEW})

# Step-up windows (D23): every platform action within ten minutes of a proven second factor,
# every change of grants within five.
PLATFORM_STEP_UP_SECONDS = 600
GRANT_CHANGE_STEP_UP_SECONDS = 300


@dataclass(frozen=True, slots=True)
class PlatformGrant:
    id: UUID
    user_id: UUID
    grant_type: GrantType
    scope_kind: ScopeKind
    scope_tenant_ids: tuple[UUID, ...] | None
    queue: str | None
    status: GrantStatus
    expires_at: datetime
    granted_by: UUID | None
    approved_by: UUID | None
    created_at: datetime
    activated_at: datetime | None
    revoked_at: datetime | None
    revoked_by: UUID | None
    revoke_reason: str | None
    version: int

    def active_at(self, now: datetime) -> bool:
        return self.status is GrantStatus.ACTIVE and now < self.expires_at
