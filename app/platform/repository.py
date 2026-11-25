"""SQL of platform grants (F2-T10). Every statement runs in a transaction of the *platform*
database role with the person in ``app.user_id``; row-level security decides what exists."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from app.platform.models import GrantStatus, GrantType, PlatformGrant, ScopeKind
from sqlalchemy import text
from sqlalchemy.orm import Session

COLUMNS = (
    "id, user_id, grant_type, scope_kind, scope_tenant_ids, queue, status, expires_at, "
    "granted_by, approved_by, created_at, activated_at, revoked_at, revoked_by, revoke_reason, "
    "version"
)


def _grant(row: Any) -> PlatformGrant:
    return PlatformGrant(
        id=row.id,
        user_id=row.user_id,
        grant_type=GrantType(row.grant_type),
        scope_kind=ScopeKind(row.scope_kind),
        scope_tenant_ids=tuple(row.scope_tenant_ids) if row.scope_tenant_ids else None,
        queue=row.queue,
        status=GrantStatus(row.status),
        expires_at=row.expires_at,
        granted_by=row.granted_by,
        approved_by=row.approved_by,
        created_at=row.created_at,
        activated_at=row.activated_at,
        revoked_at=row.revoked_at,
        revoked_by=row.revoked_by,
        revoke_reason=row.revoke_reason,
        version=row.version,
    )


def hold_own(db: Session, user_id: UUID, grant_type: GrantType) -> PlatformGrant | None:
    """The caller's own active, unexpired grant of this type, share-locked for the rest of the
    transaction: a revocation waits until this transaction ends (TOCTOU, AT-02 8.3)."""
    row = db.execute(
        text(
            f"SELECT {COLUMNS} FROM platform_grants WHERE user_id = :u AND grant_type = :t "  # noqa: S608
            "AND status = 'ACTIVE' AND expires_at > now() FOR SHARE"
        ),
        {"u": user_id, "t": grant_type.value},
    ).one_or_none()
    return _grant(row) if row else None


def own_expired(db: Session, user_id: UUID, grant_type: GrantType) -> PlatformGrant | None:
    """The caller's own grant of this type that is still marked active but has expired."""
    row = db.execute(
        text(
            f"SELECT {COLUMNS} FROM platform_grants WHERE user_id = :u AND grant_type = :t "  # noqa: S608
            "AND status = 'ACTIVE' AND expires_at <= now()"
        ),
        {"u": user_id, "t": grant_type.value},
    ).one_or_none()
    return _grant(row) if row else None


def holds(db: Session, grant_type: GrantType) -> bool:
    """Whether the person of ``app.user_id`` holds an active grant of this type (the database
    function the policies use)."""
    return bool(
        db.execute(text("SELECT platform_has_grant(:t)"), {"t": grant_type.value}).scalar_one()
    )


def set_authority(db: Session, grant_id: UUID) -> None:
    """Second step of the platform context: name the caller's verified, share-locked grant
    administrator grant. Only ``app.platform.authz`` calls this."""
    db.execute(text("SELECT set_config('app.grant_authority', :g, true)"), {"g": str(grant_id)})


def lock(db: Session, grant_id: UUID) -> PlatformGrant | None:
    row = db.execute(
        text(f"SELECT {COLUMNS} FROM platform_grants WHERE id = :i FOR UPDATE"),  # noqa: S608
        {"i": grant_id},
    ).one_or_none()
    return _grant(row) if row else None


def live_for(db: Session, user_id: UUID, grant_type: GrantType) -> PlatformGrant | None:
    """The pending or active row of this person and type, locked (at most one exists)."""
    row = db.execute(
        text(
            f"SELECT {COLUMNS} FROM platform_grants WHERE user_id = :u AND grant_type = :t "  # noqa: S608
            "AND status IN ('PENDING_APPROVAL','ACTIVE') FOR UPDATE"
        ),
        {"u": user_id, "t": grant_type.value},
    ).one_or_none()
    return _grant(row) if row else None


def insert(
    db: Session,
    *,
    user_id: UUID,
    grant_type: GrantType,
    scope_kind: ScopeKind,
    scope_tenant_ids: Sequence[UUID] | None,
    queue: str | None,
    status: GrantStatus,
    expires_at: datetime,
    granted_by: UUID,
    reason: str,
) -> PlatformGrant:
    row = db.execute(
        text(
            "INSERT INTO platform_grants (user_id, grant_type, scope_kind, scope_tenant_ids, "  # noqa: S608 - constant column list
            "queue, status, expires_at, granted_by, reason) VALUES (:u, :t, :sk, "
            "CAST(:st AS uuid[]), :q, :s, :e, :g, :r) "
            f"RETURNING {COLUMNS}"
        ),
        {
            "u": user_id,
            "t": grant_type.value,
            "sk": scope_kind.value,
            "st": [str(t) for t in scope_tenant_ids] if scope_tenant_ids else None,
            "q": queue,
            "s": status.value,
            "e": expires_at,
            "g": granted_by,
            "r": reason,
        },
    ).one()
    return _grant(row)


def approve(db: Session, grant_id: UUID, approver: UUID) -> PlatformGrant:
    row = db.execute(
        text(
            "UPDATE platform_grants SET status = 'ACTIVE', approved_by = :a "  # noqa: S608 - constant column list
            f"WHERE id = :i AND status = 'PENDING_APPROVAL' RETURNING {COLUMNS}"
        ),
        {"i": grant_id, "a": approver},
    ).one()
    return _grant(row)


def revoke(db: Session, grant_id: UUID, actor: UUID, reason: str) -> PlatformGrant:
    row = db.execute(
        text(
            "UPDATE platform_grants SET status = 'REVOKED', revoked_by = :a, revoke_reason = :r "  # noqa: S608 - constant column list
            f"WHERE id = :i AND status IN ('PENDING_APPROVAL','ACTIVE') RETURNING {COLUMNS}"
        ),
        {"i": grant_id, "a": actor, "r": reason},
    ).one()
    return _grant(row)


def lock_administrators(db: Session) -> None:
    """Serialise every revocation of an active grant administrator grant (the trigger takes the
    same lock; taking it first keeps the lock order and therefore avoids deadlocks)."""
    db.execute(text("SELECT pg_advisory_xact_lock(7100010)"))


def other_administrators(db: Session, user_id: UUID) -> int:
    return int(
        db.execute(
            text(
                "SELECT count(DISTINCT user_id) FROM platform_grants "
                "WHERE grant_type = 'PLATFORM_GRANT_ADMIN' AND status = 'ACTIVE' "
                "AND expires_at > now() AND user_id <> :u"
            ),
            {"u": user_id},
        ).scalar_one()
    )


def beneficiary(db: Session, user_id: UUID) -> tuple[str, str] | None:
    """Subject and status of the person a grant names (visible to grant administrators only
    once a grant row names them)."""
    row = db.execute(
        text("SELECT auth_subject, status FROM users WHERE id = :u"), {"u": user_id}
    ).one_or_none()
    return (str(row.auth_subject), str(row.status)) if row else None


def page(
    db: Session,
    *,
    limit: int,
    after: tuple[datetime, UUID] | None,
    user_id: UUID | None,
    grant_type: GrantType | None,
    status: GrantStatus | None,
) -> list[PlatformGrant]:
    """Newest first, ``limit + 1`` rows (the extra one proves a next page)."""
    clauses: list[str] = ["true"]
    params: dict[str, Any] = {"n": limit + 1}
    if after is not None:
        clauses.append("(created_at, id) < (:ac, :ai)")
        params |= {"ac": after[0], "ai": after[1]}
    if user_id is not None:
        clauses.append("user_id = :u")
        params["u"] = user_id
    if grant_type is not None:
        clauses.append("grant_type = :t")
        params["t"] = grant_type.value
    if status is not None:
        clauses.append("status = :s")
        params["s"] = status.value
    rows = db.execute(
        text(
            f"SELECT {COLUMNS} FROM platform_grants WHERE {' AND '.join(clauses)} "  # noqa: S608
            "ORDER BY created_at DESC, id DESC LIMIT :n"
        ),
        params,
    ).all()
    return [_grant(r) for r in rows]
