"""D37 database primitives. These do not themselves send mail or expose HTTP endpoints.

The caller owns the transaction and must authenticate the user and session before invoking them.
A returned token is transient: it must only be sent to the new address, never logged or stored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.auth import credentials
from app.auth.email import normalize_email
from app.auth.idp import IdpEmailState
from sqlalchemy import text
from sqlalchemy.orm import Session


def create_request(
    db: Session, *, user_id: UUID, session_id: UUID, new_email: str, now: datetime | None = None
) -> tuple[UUID, str]:
    """Replace a pending request while serializing all requests for the same user.

    The authenticated caller must handle uniqueness conflicts identically to ordinary requests
    when exposing this operation over HTTP. Transaction rollback restores an earlier request if
    the replacement cannot reserve its address.
    """
    normalized = normalize_email(new_email)
    moment = now or datetime.now(UTC)
    user = db.execute(
        text("SELECT email, email_normalized, status FROM users WHERE id=:u FOR UPDATE"),
        {"u": user_id},
    ).one_or_none()
    if user is None or user.status != "ACTIVE" or normalized == user.email_normalized:
        raise ValueError("cannot create email change")
    db.execute(
        text("""
            UPDATE email_change_operations SET status='CANCELLED', token_hash=NULL,
                token_issued_at=NULL, token_expires_at=NULL
            WHERE user_id=:u AND status='PENDING'
        """),
        {"u": user_id},
    )
    token, digest = credentials.new_credential()
    row = db.execute(
        text("""
            INSERT INTO email_change_operations
                (user_id, session_id, old_email, new_email, new_email_normalized,
                 token_hash, token_issued_at, token_expires_at)
            VALUES (:u, :s, :old, :new, :normalized, :hash, :issued, :expires)
            RETURNING id
        """),
        {
            "u": user_id,
            "s": session_id,
            "old": user.email,
            "new": new_email.strip(),
            "normalized": normalized,
            "hash": digest,
            "issued": moment,
            "expires": moment + timedelta(minutes=30),
        },
    ).scalar_one()
    return UUID(str(row)), token


def confirm_request(
    db: Session, *, user_id: UUID, operation_id: UUID, token: object, now: datetime | None = None
) -> bool:
    """Consume a user's unexpired token exactly once and durably queue reconciliation."""
    if not credentials.is_well_formed(token):
        return False
    row = db.execute(
        text("""
            SELECT token_hash, token_expires_at FROM email_change_operations
            WHERE id=:id AND user_id=:user AND status='PENDING' FOR UPDATE
        """),
        {"id": operation_id, "user": user_id},
    ).one_or_none()
    moment = now or datetime.now(UTC)
    if (
        row is None
        or row.token_expires_at <= moment
        or not credentials.equal(bytes(row.token_hash), credentials.hash_credential(token))
    ):
        return False
    db.execute(
        text("""
            UPDATE email_change_operations SET status='CONFIRMED', confirmed_at=:now,
                next_attempt_at=:now, token_hash=NULL, token_issued_at=NULL,
                token_expires_at=NULL WHERE id=:id
        """),
        {"now": moment, "id": operation_id},
    )
    return True


def claim_recovery(db: Session, *, now: datetime | None = None) -> tuple[UUID, UUID] | None:
    """Claim one eligible operation, with a fresh fencing value and bounded lease.

    Called under the worker role in a short transaction. External work must happen after commit;
    every later write must match both the returned lease id and an unexpired lease.
    """
    from uuid import uuid4

    moment = now or datetime.now(UTC)
    lease = uuid4()
    row = db.execute(
        text("""
            WITH candidate AS (
                SELECT id FROM email_change_operations
                WHERE status IN ('CONFIRMED', 'APPLYING')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= :now
                       OR confirmed_at <= :deadline OR attempts >= 10)
                  AND (lease_until IS NULL OR lease_until <= :now)
                ORDER BY coalesce(next_attempt_at, confirmed_at), id
                FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE email_change_operations AS o
            SET status = CASE
                    WHEN o.attempts >= 10 OR o.confirmed_at <= :deadline
                    THEN 'MANUAL_REVIEW' ELSE 'APPLYING' END,
                attempts = CASE
                    WHEN o.attempts >= 10 OR o.confirmed_at <= :deadline
                    THEN o.attempts ELSE o.attempts + 1 END,
                lease_id = CASE
                    WHEN o.attempts >= 10 OR o.confirmed_at <= :deadline
                    THEN NULL ELSE :lease END,
                lease_until = CASE
                    WHEN o.attempts >= 10 OR o.confirmed_at <= :deadline
                    THEN NULL ELSE :until END
            FROM candidate WHERE o.id = candidate.id
            RETURNING o.id, o.status
        """),
        {
            "now": moment,
            "deadline": moment - timedelta(hours=24),
            "lease": lease,
            "until": moment + timedelta(minutes=2),
        },
    ).one_or_none()
    if row is None or row.status == "MANUAL_REVIEW":
        return None
    return UUID(str(row.id)), lease


def release_recovery(
    db: Session,
    *,
    operation_id: UUID,
    lease_id: UUID,
    retry_at: datetime,
    now: datetime | None = None,
) -> bool:
    """Release only the live claim after a failed attempt; stale workers cannot write."""
    moment = now or datetime.now(UTC)
    row = db.execute(
        text("""
            UPDATE email_change_operations
            SET status = CASE WHEN attempts >= 10 OR confirmed_at <= :deadline
                    THEN 'MANUAL_REVIEW' ELSE status END,
                next_attempt_at = :retry, lease_id = NULL, lease_until = NULL
            WHERE id = :id AND status = 'APPLYING' AND lease_id = :lease AND lease_until > :now
            RETURNING id
        """),
        {
            "id": operation_id,
            "lease": lease_id,
            "now": moment,
            "retry": retry_at,
            "deadline": moment - timedelta(hours=24),
        },
    ).one_or_none()
    return row is not None


def classify_identity_state(
    *, subject: str, old_email: str, new_email: str, actual: IdpEmailState
) -> str:
    """Choose the only safe next action after reading Keycloak by immutable subject.

    The caller must re-read after an attempted update; an HTTP timeout is never interpreted as
    success or failure. A divergent state needs manual review, not an automatic overwrite.
    """
    if not isinstance(actual, IdpEmailState) or actual.subject != subject:
        return "MANUAL_REVIEW"
    try:
        actual_email = normalize_email(actual.email)
        username = normalize_email(actual.username)
        old = normalize_email(old_email)
        new = normalize_email(new_email)
    except ValueError:
        return "MANUAL_REVIEW"
    if actual.email_verified and actual_email == new and username == new:
        return "FINALIZE"
    if actual.email_verified and actual_email == old and username == old:
        return "APPLY"
    return "MANUAL_REVIEW"
