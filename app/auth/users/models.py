"""User model and status rules (F2-T04, D10). The transition table here is mirrored by the
trigger in migration 0004; a test keeps both in step."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"
    BLOCKED = "BLOCKED"


S = UserStatus
ALLOWED_TRANSITIONS: frozenset[tuple[UserStatus, UserStatus]] = frozenset(
    {
        (S.PENDING_VERIFICATION, S.ACTIVE),
        (S.PENDING_VERIFICATION, S.BLOCKED),
        (S.ACTIVE, S.DEACTIVATED),
        (S.ACTIVE, S.BLOCKED),
        (S.DEACTIVATED, S.ACTIVE),
        (S.DEACTIVATED, S.BLOCKED),
        (S.BLOCKED, S.ACTIVE),
        (S.BLOCKED, S.DEACTIVATED),
    }
)


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    auth_subject: str
    email: str
    email_normalized: str
    email_verified_at: datetime | None
    status: UserStatus
    status_reason: str | None
    status_changed_at: datetime
    status_changed_by: UUID | None
    display_name: str | None
    preferred_language: str
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int

    @classmethod
    def from_row(cls, row: Any) -> User:
        data = dict(row._mapping)
        data["status"] = UserStatus(data["status"])
        return cls(**data)
