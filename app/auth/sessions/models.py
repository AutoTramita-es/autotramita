"""Session model and policy (F2-T05)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.auth.settings import AuthSettings


class ClientType(StrEnum):
    WEB = "WEB"
    ADMIN_WEB = "ADMIN_WEB"
    MOBILE = "MOBILE"


class AuthLevel(StrEnum):
    LOA1 = "LOA1"
    LOA2 = "LOA2"


class RevokeReason(StrEnum):
    LOGOUT = "LOGOUT"
    USER_REVOKED = "USER_REVOKED"
    IDLE_TIMEOUT = "IDLE_TIMEOUT"
    ABSOLUTE_TIMEOUT = "ABSOLUTE_TIMEOUT"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105 - a reason code, not a password
    ACCOUNT_DEACTIVATED = "ACCOUNT_DEACTIVATED"
    ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"
    ADMIN_REVOKED = "ADMIN_REVOKED"
    IDP_LOGOUT = "IDP_LOGOUT"
    MEMBERSHIP_REVOKED = "MEMBERSHIP_REVOKED"
    SECURITY_POLICY = "SECURITY_POLICY"
    REPLAY_DETECTED = "REPLAY_DETECTED"
    REFRESH_REUSE = "REFRESH_REUSE"
    SESSION_LIMIT = "SESSION_LIMIT"


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    """Lifetimes by client type (D15), the session cap and the activity write throttle."""

    idle: dict[ClientType, timedelta]
    absolute: dict[ClientType, timedelta]
    max_sessions: int
    touch_interval: timedelta = timedelta(seconds=60)

    @classmethod
    def from_settings(cls, s: AuthSettings) -> SessionPolicy:
        return cls(
            idle={
                ClientType.WEB: timedelta(minutes=s.web_idle_minutes),
                ClientType.ADMIN_WEB: timedelta(minutes=s.admin_idle_minutes),
                ClientType.MOBILE: timedelta(days=s.mobile_idle_days),
            },
            absolute={
                ClientType.WEB: timedelta(hours=s.web_absolute_hours),
                ClientType.ADMIN_WEB: timedelta(hours=s.admin_absolute_hours),
                ClientType.MOBILE: timedelta(days=s.mobile_absolute_days),
            },
            max_sessions=s.max_sessions_per_user,
        )


@dataclass(frozen=True, slots=True)
class UserSession:
    id: UUID
    user_id: UUID
    client_type: ClientType
    kc_session_id: str
    active_tenant_id: UUID | None
    active_branch_id: UUID | None
    active_membership_id: UUID | None
    context_version: int
    auth_time: datetime
    auth_level: AuthLevel
    step_up_at: datetime | None
    device_label: str | None
    platform: str | None
    app_version: str | None
    ua_family: str | None
    country_code: str | None
    created_at: datetime
    last_activity_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None
    revoked_reason: str | None
    version: int

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired(self, now: datetime) -> bool:
        return now >= self.idle_expires_at or now >= self.absolute_expires_at

    def is_live(self, now: datetime) -> bool:
        return not self.is_revoked and not self.is_expired(now)

    @classmethod
    def from_row(cls, row: Any) -> UserSession:
        data = dict(row._mapping)
        data["client_type"] = ClientType(data["client_type"])
        data["auth_level"] = AuthLevel(data["auth_level"])
        return cls(**data)
