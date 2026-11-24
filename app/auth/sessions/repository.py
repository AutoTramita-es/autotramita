"""SQL for ``user_sessions`` (F2-T05). Functions take the caller's ``Session``."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app.auth.sessions.models import UserSession
from sqlalchemy import text
from sqlalchemy.orm import Session

COLUMNS = (
    "id, user_id, client_type, kc_session_id, active_tenant_id, active_branch_id, "
    "active_membership_id, context_version, auth_time, auth_level, step_up_at, device_label, "
    "platform, app_version, ua_family, country_code, created_at, last_activity_at, "
    "idle_expires_at, absolute_expires_at, revoked_at, revoked_reason, version"
)


def _one(db: Session, sql: str, params: dict[str, Any]) -> UserSession | None:
    row = db.execute(text(sql), params).one_or_none()
    return UserSession.from_row(row) if row else None


def by_credential(db: Session, digest: bytes, *, lock: bool) -> UserSession | None:
    suffix = " FOR SHARE" if lock else ""
    return _one(
        db,
        f"SELECT {COLUMNS} FROM user_sessions WHERE credential_hash = :h{suffix}",  # noqa: S608
        {"h": digest},
    )


def by_kc_session(
    db: Session, user_id: UUID, kc_session_id: str, client_type: str, *, lock: bool
) -> UserSession | None:
    suffix = " FOR SHARE" if lock else ""
    return _one(
        db,
        f"SELECT {COLUMNS} FROM user_sessions "  # noqa: S608
        "WHERE user_id = :u AND kc_session_id = :k AND client_type = :c "
        f"ORDER BY created_at DESC, id LIMIT 1{suffix}",
        {"u": user_id, "k": kc_session_id, "c": client_type},
    )


def list_live(db: Session, user_id: UUID, now: datetime) -> list[UserSession]:
    rows = db.execute(
        text(
            f"SELECT {COLUMNS} FROM user_sessions WHERE user_id = :u AND revoked_at IS NULL "  # noqa: S608
            "AND idle_expires_at > :n AND absolute_expires_at > :n ORDER BY created_at DESC, id"
        ),
        {"u": user_id, "n": now},
    ).all()
    return [UserSession.from_row(row) for row in rows]


def by_id(db: Session, session_id: UUID) -> UserSession | None:
    return _one(
        db,
        f"SELECT {COLUMNS} FROM user_sessions WHERE id = :i",  # noqa: S608
        {"i": session_id},
    )


def lock_user_for_new_session(db: Session, user_id: UUID) -> str | None:
    """Serialise session creation per user (advisory lock, released at commit) and return the
    user's status read under a share lock, so a concurrent deactivation is seen or waited for."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(CAST(:u AS text), 0))"),
        {"u": str(user_id)},
    )
    row = db.execute(text("SELECT status FROM users WHERE id = :u FOR SHARE"), {"u": user_id})
    found = row.one_or_none()
    return str(found[0]) if found else None


def count_live(db: Session, user_id: UUID, now: datetime) -> int:
    return int(
        db.execute(
            text(
                "SELECT count(*) FROM user_sessions WHERE user_id = :u AND revoked_at IS NULL "
                "AND idle_expires_at > :n AND absolute_expires_at > :n"
            ),
            {"u": user_id, "n": now},
        ).scalar_one()
    )


def revoke_oldest_live(db: Session, user_id: UUID, now: datetime, how_many: int) -> int:
    # The victims are chosen once (MATERIALIZED): a subselect inside the UPDATE could be
    # evaluated again while rows change and take more rows than asked for.
    rows = db.execute(
        text(
            "WITH victims AS MATERIALIZED (SELECT id FROM user_sessions WHERE user_id = :u "
            "AND revoked_at IS NULL AND idle_expires_at > :n AND absolute_expires_at > :n "
            "ORDER BY created_at, id LIMIT :k FOR UPDATE) "
            "UPDATE user_sessions SET revoked_at = :n, revoked_reason = 'SESSION_LIMIT', "
            "version = version + 1 WHERE id IN (SELECT id FROM victims) RETURNING id"
        ),
        {"u": user_id, "n": now, "k": how_many},
    ).all()
    return len(rows)


def insert(db: Session, values: dict[str, Any]) -> UserSession:
    row = db.execute(
        text(
            "INSERT INTO user_sessions (user_id, client_type, credential_hash, kc_session_id, "  # noqa: S608
            "auth_time, auth_level, step_up_at, device_label, platform, app_version, ua_family, "
            "ip_prefix, country_code, created_at, last_activity_at, idle_expires_at, "
            "absolute_expires_at) VALUES (:user_id, :client_type, :credential_hash, "
            ":kc_session_id, :auth_time, :auth_level, :step_up_at, :device_label, :platform, "
            ":app_version, :ua_family, CAST(:ip_prefix AS cidr), :country_code, :now, :now, "
            f":idle_expires_at, :absolute_expires_at) RETURNING {COLUMNS}"
        ),
        values,
    ).one()
    return UserSession.from_row(row)


def revoke_where(
    db: Session,
    condition: str,
    params: dict[str, Any],
    *,
    reason: str,
    now: datetime,
    revoked_by: UUID | None,
) -> int:
    """Revoke live rows matching a fixed, caller-written ``condition`` (never user input).
    Rows are locked in id order so concurrent revocations cannot deadlock."""
    rows = db.execute(
        text(
            "WITH victims AS MATERIALIZED (SELECT id FROM user_sessions "  # noqa: S608
            f"WHERE revoked_at IS NULL AND {condition} ORDER BY id FOR UPDATE) "
            "UPDATE user_sessions SET revoked_at = :now, revoked_reason = :reason, "
            "revoked_by = :by, version = version + 1 "
            "WHERE id IN (SELECT id FROM victims) RETURNING id"
        ),
        {**params, "now": now, "reason": reason, "by": revoked_by},
    ).all()
    return len(rows)


def rotate(db: Session, session_id: UUID, digest: bytes) -> bool:
    result: Any = db.execute(
        text(
            "UPDATE user_sessions SET credential_hash = :h, version = version + 1 "
            "WHERE id = :i AND revoked_at IS NULL"
        ),
        {"h": digest, "i": session_id},
    )
    return bool(result.rowcount)


def mark_step_up(
    db: Session, session_id: UUID, digest: bytes | None, level: str, now: datetime
) -> bool:
    result: Any = db.execute(
        text(
            "UPDATE user_sessions SET auth_level = :l, step_up_at = :n, "
            "credential_hash = coalesce(:h, credential_hash), version = version + 1 "
            "WHERE id = :i AND revoked_at IS NULL"
        ),
        {"l": level, "n": now, "h": digest, "i": session_id},
    )
    return bool(result.rowcount)


def touch_skip_locked(
    db: Session,
    session_id: UUID,
    *,
    threshold: datetime,
    now: datetime,
    idle_expires_at: datetime,
    country_code: str | None,
) -> bool:
    """Best-effort activity update that never waits: a row locked by a request in flight (or
    by a revocation) is skipped and tried again on a later request."""
    result: Any = db.execute(
        text(
            "UPDATE user_sessions SET last_activity_at = :n, idle_expires_at = :idle, "
            "country_code = coalesce(:cc, country_code), version = version + 1 "
            "WHERE id IN (SELECT id FROM user_sessions WHERE id = :i AND revoked_at IS NULL "
            "AND last_activity_at <= :t FOR NO KEY UPDATE SKIP LOCKED)"
        ),
        {"n": now, "idle": idle_expires_at, "cc": country_code, "i": session_id, "t": threshold},
    )
    return bool(result.rowcount)


def set_workspace(
    db: Session,
    session_id: UUID,
    *,
    tenant_id: UUID,
    branch_id: UUID | None,
    membership_id: UUID,
    expected_version: int,
) -> bool:
    """Switch the active workspace if the context version is still the one the caller saw and
    the session is live. One statement: of two parallel switches exactly one matches."""
    result: Any = db.execute(
        text(
            "UPDATE user_sessions SET active_tenant_id = :t, active_branch_id = :b, "
            "active_membership_id = :m, context_version = context_version + 1, "
            "version = version + 1 WHERE id = :i AND context_version = :v "
            "AND revoked_at IS NULL"
        ),
        {
            "t": tenant_id,
            "b": branch_id,
            "m": membership_id,
            "i": session_id,
            "v": expected_version,
        },
    )
    return bool(result.rowcount)
