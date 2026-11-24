"""SQL for ``users`` (F2-T04). Functions take the caller's ``Session``; the caller owns the
transaction and the request context (row-level security decides what is visible)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.auth.users.models import User, UserStatus
from sqlalchemy import text
from sqlalchemy.orm import Session

Lock = Literal["share", "update"] | None
_LOCKS = {None: "", "share": " FOR SHARE", "update": " FOR UPDATE"}
COLUMNS = (
    "id, auth_subject, email, email_normalized, email_verified_at, status, status_reason, "
    "status_changed_at, status_changed_by, display_name, preferred_language, last_login_at, "
    "created_at, updated_at, version"
)


def get_by_subject(session: Session, subject: str, *, lock: Lock = None) -> User | None:
    row = session.execute(
        # COLUMNS and the lock clause are module constants, never caller input
        text(f"SELECT {COLUMNS} FROM users WHERE auth_subject = :s{_LOCKS[lock]}"),  # noqa: S608
        {"s": subject},
    ).one_or_none()
    return User.from_row(row) if row else None


def get_by_id(session: Session, user_id: UUID, *, lock: Lock = None) -> User | None:
    row = session.execute(
        text(f"SELECT {COLUMNS} FROM users WHERE id = :i{_LOCKS[lock]}"),  # noqa: S608
        {"i": user_id},
    ).one_or_none()
    return User.from_row(row) if row else None


def insert(
    session: Session,
    *,
    subject: str,
    email: str,
    email_normalized: str,
    verified_at: datetime | None,
    status: UserStatus,
) -> User | None:
    """Insert a first-login row. ``None`` means another transaction already created this
    subject (the caller reads it). A different identity holding the same e-mail raises
    ``IntegrityError`` on ``users_email_normalized_key``."""
    row = session.execute(
        text(
            "INSERT INTO users (auth_subject, email, email_normalized, email_verified_at, "  # noqa: S608
            "status) VALUES (:s, :e, :n, :v, :st) ON CONFLICT (auth_subject) DO NOTHING "
            f"RETURNING {COLUMNS}"
        ),
        {"s": subject, "e": email, "n": email_normalized, "v": verified_at, "st": status.value},
    ).one_or_none()
    return User.from_row(row) if row else None


def update_email(
    session: Session, user_id: UUID, *, email: str, email_normalized: str, verified_at: datetime
) -> None:
    session.execute(
        text(
            "UPDATE users SET email = :e, email_normalized = :n, email_verified_at = :v, "
            "version = version + 1 WHERE id = :i"
        ),
        {"e": email, "n": email_normalized, "v": verified_at, "i": user_id},
    )


def mark_email_verified(session: Session, user_id: UUID, verified_at: datetime) -> None:
    """The database activates a pending user when this is set (trigger ``users_guard``)."""
    session.execute(
        text("UPDATE users SET email_verified_at = :v, version = version + 1 WHERE id = :i"),
        {"v": verified_at, "i": user_id},
    )


def touch_login(session: Session, user_id: UUID, at: datetime) -> None:
    session.execute(
        text("UPDATE users SET last_login_at = :t, version = version + 1 WHERE id = :i"),
        {"t": at, "i": user_id},
    )


def set_status(
    session: Session,
    user_id: UUID,
    status: UserStatus,
    *,
    reason: str | None,
    changed_by: UUID | None,
) -> None:
    session.execute(
        text(
            "UPDATE users SET status = :s, status_reason = :r, status_changed_by = :b, "
            "version = version + 1 WHERE id = :i"
        ),
        {"s": status.value, "r": reason, "b": changed_by, "i": user_id},
    )


def update_profile(
    session: Session,
    user_id: UUID,
    *,
    display_name: str | None,
    preferred_language: str,
    expected_version: int,
) -> bool:
    """Write the profile if the version is still the one the caller saw (If-Match)."""
    result: Any = session.execute(
        text(
            "UPDATE users SET display_name = :d, preferred_language = :l, "
            "version = version + 1 WHERE id = :i AND version = :v"
        ),
        {"d": display_name, "l": preferred_language, "i": user_id, "v": expected_version},
    )
    return bool(result.rowcount)
