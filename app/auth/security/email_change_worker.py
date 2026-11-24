"""Scoped D37 recovery. All identity changes are serialized by the operation row lock."""

from __future__ import annotations

import secrets
import smtplib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.idp import IdentityProviderAdmin, IdpAdminError, IdpConflict
from app.auth.security.email_change import classify_identity_state, release_recovery
from app.auth.security.notify import SmtpNotifier
from app.auth.sessions import service as sessions
from app.auth.sessions.models import RevokeReason
from app.auth.users.repository import lock_email, update_email
from app.core.db import RequestContext, session_scope
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker


class StaleLease(Exception):
    """The claim is no longer entitled to perform local changes."""


def _manual(db: Session, operation: UUID, lease: UUID) -> None:
    result = db.execute(
        text("""
        UPDATE email_change_operations SET status='MANUAL_REVIEW', lease_id=NULL,
            lease_until=NULL WHERE id=:id AND status='APPLYING' AND lease_id=:lease
            AND lease_until > clock_timestamp() RETURNING id
    """),
        {"id": operation, "lease": lease},
    ).one_or_none()
    if result is None:
        raise StaleLease()


def apply_claim(db: Session, admin: IdentityProviderAdmin, operation: UUID, lease: UUID) -> None:
    """Lock, reconcile and atomically finish a claimed operation; caller owns transaction.

    An external timeout raises and rolls the transaction back. A retry reads the provider again,
    including when an earlier update succeeded but its response was lost.
    """
    row = db.execute(
        text("""
        SELECT o.user_id, o.session_id, o.old_email, o.new_email, o.new_email_normalized,
               u.auth_subject, u.email AS local_email, u.status AS user_status
        FROM email_change_operations o JOIN users u ON u.id=o.user_id
        WHERE o.id=:id AND o.status='APPLYING' AND o.lease_id=:lease
          AND o.lease_until > clock_timestamp() FOR UPDATE OF o, u
    """),
        {"id": operation, "lease": lease},
    ).one_or_none()
    if row is None:
        raise StaleLease()
    if row.user_status != "ACTIVE" or row.local_email != row.old_email:
        _manual(db, operation, lease)
        return
    # The same transaction-scoped lock is used by first-login provisioning and provider sync.
    # It closes the race between the uniqueness check and the external/local update.
    lock_email(db, row.new_email_normalized)
    taken = db.execute(
        text("""
        SELECT EXISTS (SELECT 1 FROM users WHERE email_normalized=:email AND id<>:user)
    """),
        {"email": row.new_email_normalized, "user": row.user_id},
    ).scalar_one()
    if taken:
        _manual(db, operation, lease)
        return
    actual = admin.get_email_state(row.auth_subject)
    state = classify_identity_state(
        subject=row.auth_subject, old_email=row.old_email, new_email=row.new_email, actual=actual
    )
    if state == "MANUAL_REVIEW":
        _manual(db, operation, lease)
        return
    if state == "APPLY":
        owner = admin.find_user_by_email(row.new_email)
        if owner is not None and owner.subject != row.auth_subject:
            _manual(db, operation, lease)
            return
        try:
            admin.set_verified_email(row.auth_subject, row.new_email)
        except IdpConflict:
            _manual(db, operation, lease)
            return
        actual = admin.get_email_state(row.auth_subject)
        state = classify_identity_state(
            subject=row.auth_subject,
            old_email=row.old_email,
            new_email=row.new_email,
            actual=actual,
        )
        if state != "FINALIZE":
            _manual(db, operation, lease)
            return
    db.execute(
        text("SELECT set_config('app.email_change_lease', :lease, true)"), {"lease": str(lease)}
    )
    now = datetime.now(UTC)
    update_email(
        db,
        row.user_id,
        email=row.new_email,
        email_normalized=row.new_email_normalized,
        verified_at=now,
    )
    sessions.revoke_others(
        db,
        row.user_id,
        row.session_id,
        reason=RevokeReason.SECURITY_POLICY,
        actor_user_id=None,
        now=now,
    )
    record(
        db,
        AuditEvent(
            action="identity.email.changed",
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.SYSTEM,
            subject_user_id=row.user_id,
            details={},
        ),
    )
    done = db.execute(
        text("""
        UPDATE email_change_operations SET status='COMPLETED', completed_at=:now,
            old_email=NULL, new_email=NULL, new_email_normalized=NULL,
            lease_id=NULL, lease_until=NULL WHERE id=:id AND lease_id=:lease
            AND status='APPLYING' AND lease_until > clock_timestamp() RETURNING id
    """),
        {"id": operation, "lease": lease, "now": now},
    ).one_or_none()
    if done is None:
        raise StaleLease()
    for kind, recipient in (("OLD", row.old_email), ("NEW", row.new_email)):
        db.execute(
            text("""
            INSERT INTO email_change_notifications (operation_id, recipient_kind, recipient)
            VALUES (:id, :kind, :recipient)
        """),
            {"id": operation, "kind": kind, "recipient": recipient},
        )


def process_claim(
    factory: sessionmaker[Session], admin: IdentityProviderAdmin, operation: UUID, lease: UUID
) -> bool:
    """Attempt reconciliation; leave unknown outcomes durable for retry with bounded jitter."""
    try:
        with session_scope(factory, RequestContext()) as db:
            apply_claim(db, admin, operation, lease)
        return True
    except StaleLease:
        return False
    except IntegrityError:
        # A local uniqueness conflict is permanent; never attach identities by address.
        with session_scope(factory, RequestContext()) as db:
            try:
                _manual(db, operation, lease)
            except StaleLease:
                return False
        return False
    except IdpAdminError:
        with session_scope(factory, RequestContext()) as db:
            attempts = db.execute(
                text("""
                SELECT attempts FROM email_change_operations WHERE id=:id AND lease_id=:lease
            """),
                {"id": operation, "lease": lease},
            ).scalar_one_or_none()
            if attempts is None:
                return False
            ceiling = min(3600, 30 * 2 ** min(int(attempts), 7))
            delay = max(1, ceiling // 2 + secrets.randbelow(ceiling // 2 + 1))
            release_recovery(
                db,
                operation_id=operation,
                lease_id=lease,
                retry_at=datetime.now(UTC) + timedelta(seconds=delay),
            )
        return False


def claim_notification(db: Session, *, now: datetime | None = None) -> tuple[UUID, UUID] | None:
    """Claim one notification; disabled SMTP must never call this function."""
    from uuid import uuid4

    now = now or datetime.now(UTC)
    lease = uuid4()
    row = db.execute(
        text("""
        WITH candidate AS (
            SELECT id FROM email_change_notifications
            WHERE status='PENDING' AND (next_attempt_at IS NULL OR next_attempt_at <= :now
                 OR created_at <= :deadline OR attempts >= 10)
              AND (lease_until IS NULL OR lease_until <= :now)
            ORDER BY coalesce(next_attempt_at, created_at), id FOR UPDATE SKIP LOCKED LIMIT 1
        )
        UPDATE email_change_notifications n
        SET status = CASE WHEN n.attempts >= 10 OR n.created_at <= :deadline
                    THEN 'MANUAL_REVIEW' ELSE n.status END,
            attempts = CASE WHEN n.attempts >= 10 OR n.created_at <= :deadline
                    THEN n.attempts ELSE n.attempts + 1 END,
            lease_id = CASE WHEN n.attempts >= 10 OR n.created_at <= :deadline
                    THEN NULL ELSE :lease END,
            lease_until = CASE WHEN n.attempts >= 10 OR n.created_at <= :deadline
                    THEN NULL ELSE :until END
        FROM candidate WHERE n.id = candidate.id RETURNING n.id, n.status
    """),
        {
            "now": now,
            "deadline": now - timedelta(hours=24),
            "lease": lease,
            "until": now + timedelta(minutes=2),
        },
    ).one_or_none()
    if row is None or row.status == "MANUAL_REVIEW":
        return None
    return UUID(str(row.id)), lease


def deliver_notification(
    factory: sessionmaker[Session], notifier: SmtpNotifier, job: UUID, lease: UUID
) -> bool:
    """Deliver under a row lock; a crash may duplicate SMTP delivery but never loses the job."""
    from app.auth.security.notify import Notice, NoticeKind

    try:
        with session_scope(factory, RequestContext()) as db:
            row = db.execute(
                text("""
                SELECT recipient, created_at FROM email_change_notifications
                WHERE id=:id AND status='PENDING' AND lease_id=:lease
                AND lease_until > clock_timestamp() FOR UPDATE
            """),
                {"id": job, "lease": lease},
            ).one_or_none()
            if row is None:
                return False
            notifier.send_durable(
                Notice(NoticeKind.EMAIL_CHANGED, row.recipient, row.created_at), job
            )
            result = db.execute(
                text("""
                UPDATE email_change_notifications SET status='SENT', sent_at=clock_timestamp(),
                    updated_at=clock_timestamp(), recipient=NULL, lease_id=NULL, lease_until=NULL
                WHERE id=:id AND status='PENDING' AND lease_id=:lease
                  AND lease_until > clock_timestamp() RETURNING id
            """),
                {"id": job, "lease": lease},
            ).one_or_none()
            if result is None:
                raise StaleLease()
        return True
    except StaleLease:
        return False
    except (OSError, smtplib.SMTPException):
        with session_scope(factory, RequestContext()) as db:
            row = db.execute(
                text("""
                SELECT attempts, created_at FROM email_change_notifications
                WHERE id=:id AND status='PENDING' AND lease_id=:lease
                  AND lease_until > clock_timestamp() FOR UPDATE
            """),
                {"id": job, "lease": lease},
            ).one_or_none()
            if row is None:
                return False
            now = datetime.now(UTC)
            ceiling = min(3600, 30 * 2 ** min(int(row.attempts), 7))
            delay = max(1, ceiling // 2 + secrets.randbelow(ceiling // 2 + 1))
            status = (
                "MANUAL_REVIEW"
                if row.attempts >= 10 or row.created_at <= now - timedelta(hours=24)
                else "PENDING"
            )
            db.execute(
                text("""
                UPDATE email_change_notifications SET status=:status, lease_id=NULL,
                    lease_until=NULL, next_attempt_at=:retry, updated_at=:now
                WHERE id=:id AND lease_id=:lease AND lease_until > clock_timestamp()
            """),
                {
                    "id": job,
                    "lease": lease,
                    "status": status,
                    "now": now,
                    "retry": now + timedelta(seconds=delay),
                },
            )
        return False


def cleanup(db: Session) -> None:
    """Expire unconfirmed tokens and remove only resolved operational records after 30 days."""
    db.execute(
        text("""
        UPDATE email_change_operations SET status='EXPIRED', token_hash=NULL,
            token_issued_at=NULL, token_expires_at=NULL, old_email=NULL, new_email=NULL,
            new_email_normalized=NULL WHERE status='PENDING' AND token_expires_at <= now()
    """)
    )
    db.execute(
        text(
            "DELETE FROM email_change_notifications WHERE status='SENT' "
            "AND sent_at <= now() - interval '30 days'"
        )
    )
    db.execute(
        text("""
        DELETE FROM email_change_operations o WHERE o.status IN ('COMPLETED','CANCELLED','EXPIRED')
          AND o.updated_at <= now() - interval '30 days'
          AND NOT EXISTS (SELECT 1 FROM email_change_notifications n WHERE n.operation_id=o.id)
    """)
    )


def run_once(
    factory: sessionmaker[Session], admin: IdentityProviderAdmin, notifier: SmtpNotifier | None
) -> None:
    """Run a bounded recovery sweep, safe for simultaneous workers in other instances."""
    from app.auth.security.email_change import claim_recovery

    with session_scope(factory, RequestContext()) as db:
        cleanup(db)
    for _ in range(25):
        with session_scope(factory, RequestContext()) as db:
            operation = claim_recovery(db)
        if operation is None:
            break
        process_claim(factory, admin, *operation)
    if notifier is None:
        return  # O15 / disabled SMTP: jobs stay pending, with no attempt consumed
    for _ in range(50):
        with session_scope(factory, RequestContext()) as db:
            job = claim_notification(db)
        if job is None:
            break
        deliver_notification(factory, notifier, *job)
