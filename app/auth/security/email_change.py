"""D37 database primitives. These do not themselves send mail or expose HTTP endpoints.

The caller owns the transaction and must authenticate the user and session before invoking them.
A returned token is transient: it must only be sent to the new address, never logged or stored.
"""

from __future__ import annotations

import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.auth import credentials
from app.auth.email import normalize_email
from app.auth.idp import IdpEmailState
from sqlalchemy import text
from sqlalchemy.orm import Session

TOKEN_LIFETIME = timedelta(minutes=30)
LEASE = timedelta(minutes=2)
MAX_ATTEMPTS = 10
MAX_UNRESOLVED = timedelta(hours=24)
# Characters that let a single string be read as a display name, a list or a quoted address by a
# mail library: the mailbox that receives the token must be exactly the one that is reserved.
_AMBIGUOUS = frozenset('"(),:;<>[]\\')


def prepare_new_address(value: str) -> tuple[str, str]:
    """Return ``(address, normalised)`` for a requested new address. ``address`` keeps its case
    and is what is mailed and later written to the provider. Raises ``ValueError``."""
    normalized = normalize_email(value)
    address = unicodedata.normalize("NFKC", value).strip()
    if address.count("@") != 1 or any(ch in _AMBIGUOUS for ch in address):
        raise ValueError("not a plain e-mail address")
    return address, normalized


def retry_delay(attempts: int) -> timedelta:
    """Exponential backoff (60 s doubling, capped at one hour) with jitter in the upper half."""
    ceiling = min(3600, 30 * 2 ** min(max(attempts, 0), 7))
    return timedelta(seconds=max(1, ceiling // 2 + secrets.randbelow(ceiling // 2 + 1)))


def create_request(
    db: Session, *, user_id: UUID, session_id: UUID, new_email: str, now: datetime | None = None
) -> tuple[UUID, str]:
    """Replace a pending request while serializing all requests for the same user.

    The authenticated caller must handle uniqueness conflicts identically to ordinary requests
    when exposing this operation over HTTP. Transaction rollback restores an earlier request if
    the replacement cannot reserve its address.
    """
    address, normalized = prepare_new_address(new_email)
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
            "new": address,
            "normalized": normalized,
            "hash": digest,
            "issued": moment,
            "expires": moment + TOKEN_LIFETIME,
        },
    ).scalar_one()
    return UUID(str(row)), token


def confirm_request(
    db: Session, *, user_id: UUID, operation_id: UUID, token: object, now: datetime | None = None
) -> bool:
    """Consume a user's unexpired token exactly once and durably queue reconciliation.

    A request dies with the session that made it when that session was ended for any reason other
    than an ordinary sign-out (or the session cap): "sign out everywhere", a password change or a
    security revocation must also stop what the ended session started.
    """
    if not credentials.is_well_formed(token):
        return False
    row = db.execute(
        text("""
            SELECT o.token_hash, o.token_expires_at FROM email_change_operations o
            JOIN user_sessions s ON s.id = o.session_id AND s.user_id = o.user_id
            WHERE o.id=:id AND o.user_id=:user AND o.status='PENDING'
              AND (s.revoked_at IS NULL OR s.revoked_reason IN ('LOGOUT', 'SESSION_LIMIT'))
            FOR UPDATE OF o
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


def requires_fresh_authentication(
    db: Session, *, user_id: UUID, kc_session_id: str, auth_time: int | None, leeway_seconds: int
) -> bool:
    """True when a sign-in rests on an authentication older than a completed e-mail change made
    from a *different* identity-provider session. The change ended the person's other application
    sessions; a surviving single sign-on session must not silently open them again."""
    moment = None
    if auth_time is not None:
        moment = datetime.fromtimestamp(auth_time + leeway_seconds, tz=UTC)
    return bool(
        db.execute(
            text("""
                SELECT EXISTS (SELECT 1 FROM email_change_operations o
                    JOIN user_sessions s ON s.id = o.session_id
                    WHERE o.user_id = :u AND o.status = 'COMPLETED'
                      AND s.kc_session_id <> :sid
                      AND (CAST(:moment AS timestamptz) IS NULL OR o.completed_at > :moment))
            """),
            {"u": user_id, "sid": kc_session_id, "moment": moment},
        ).scalar_one()
    )


def claim_recovery(db: Session, *, now: datetime | None = None) -> tuple[UUID, UUID] | None:
    """Claim one eligible operation, with a fresh fencing value and bounded lease.

    Operations past the attempt or age limit are first moved to ``MANUAL_REVIEW``; ``None``
    therefore means that nothing is eligible. Called under the worker role in a short
    transaction. External work must happen after commit; every later write must match both the
    returned lease id and an unexpired lease.
    """
    moment = now or datetime.now(UTC)
    limits = {"now": moment, "deadline": moment - MAX_UNRESOLVED, "max": MAX_ATTEMPTS}
    db.execute(
        text("""
            WITH exhausted AS (
                SELECT id FROM email_change_operations
                WHERE status IN ('CONFIRMED', 'APPLYING')
                  AND (attempts >= :max OR confirmed_at <= :deadline)
                  AND (lease_until IS NULL OR lease_until <= :now)
                FOR UPDATE SKIP LOCKED
            )
            UPDATE email_change_operations AS o
            SET status = 'MANUAL_REVIEW', lease_id = NULL, lease_until = NULL
            FROM exhausted WHERE o.id = exhausted.id
        """),
        limits,
    )
    lease = uuid4()
    row = db.execute(
        text("""
            WITH candidate AS (
                SELECT id FROM email_change_operations
                WHERE status IN ('CONFIRMED', 'APPLYING')
                  AND attempts < :max AND confirmed_at > :deadline
                  AND (next_attempt_at IS NULL OR next_attempt_at <= :now)
                  AND (lease_until IS NULL OR lease_until <= :now)
                ORDER BY coalesce(next_attempt_at, confirmed_at), id
                FOR UPDATE SKIP LOCKED LIMIT 1
            )
            UPDATE email_change_operations AS o
            SET status = 'APPLYING', attempts = o.attempts + 1,
                lease_id = :lease, lease_until = :until
            FROM candidate WHERE o.id = candidate.id
            RETURNING o.id
        """),
        {**limits, "lease": lease, "until": moment + LEASE},
    ).one_or_none()
    return None if row is None else (UUID(str(row.id)), lease)


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
            SET status = CASE WHEN attempts >= :max OR confirmed_at <= :deadline
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
            "deadline": moment - MAX_UNRESOLVED,
            "max": MAX_ATTEMPTS,
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
