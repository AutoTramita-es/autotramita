"""Resolving a D37 e-mail change that waits in ``MANUAL_REVIEW`` (F2-T09-REC F-4).

This is the domain mechanism only. No route, command or scheduled task calls it: the privileged
interface belongs to F2-T11 and its authorisation to the platform grants of F2-T10. Until then
the only authority wired anywhere refuses everything (``DenyAllReview``).

An operator can choose between two things, and the facts decide whether the choice is allowed.
The facts are read again, under the operation row lock, at the moment of the decision:

* ``RETRY`` hands the operation back to the recovery worker, which reconciles it as usual. Only
  when the identity provider holds a state the worker understands (still the old address, or
  already the confirmed one) and nothing local stands in the way.
* ``CANCEL`` ends the operation and frees the address. Only when the provider proves, for the
  immutable subject, that the change was never made there.

Nothing here writes an address anywhere. A provider state that is neither of the two is first
corrected at the provider by a person; this mechanism never overwrites it. Every decision and
every refusal is audited, without addresses or tokens, and nothing identifying is logged."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.idp import IdentityProviderAdmin, IdpAdminError
from app.auth.security.email_change import classify_identity_state
from app.auth.users.repository import lock_email
from app.core.db import RequestContext, session_scope
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker


class ReviewDecision(StrEnum):
    RETRY = "RETRY"
    CANCEL = "CANCEL"


class ProviderState(StrEnum):
    NOT_APPLIED = "NOT_APPLIED"  # the old address and login, verified
    APPLIED = "APPLIED"  # the confirmed address and login, verified
    DIVERGENT = "DIVERGENT"  # anything else, including another or unverified identity
    UNAVAILABLE = "UNAVAILABLE"  # the provider did not answer


class Blocker(StrEnum):
    ACCOUNT_NOT_ACTIVE = "ACCOUNT_NOT_ACTIVE"
    LOCAL_ADDRESS_CHANGED = "LOCAL_ADDRESS_CHANGED"
    ADDRESS_TAKEN_LOCALLY = "ADDRESS_TAKEN_LOCALLY"
    ADDRESS_TAKEN_AT_PROVIDER = "ADDRESS_TAKEN_AT_PROVIDER"
    PROVIDER_DIVERGENT = "PROVIDER_DIVERGENT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    CHANGE_ALREADY_APPLIED = "CHANGE_ALREADY_APPLIED"


class ReviewResult(StrEnum):
    RETRY_QUEUED = "RETRY_QUEUED"
    CANCELLED = "CANCELLED"
    ALREADY_RESOLVED = "ALREADY_RESOLVED"  # the same decision was carried out before
    REFUSED = "REFUSED"  # the facts do not allow it; see the blockers
    NOT_IN_REVIEW = "NOT_IN_REVIEW"  # unknown, or not (or no longer) waiting for a decision


class ReviewForbidden(Exception):
    """The authority did not allow this decision."""


class ReviewAuthority(Protocol):
    """Who may decide. F2-T10 implements this with platform grants (level two, five minutes);
    it runs inside the resolving transaction, so a revoked grant is seen."""

    def permits(self, db: Session, operation_id: UUID, decision: ReviewDecision) -> bool: ...


class DenyAllReview:
    def permits(self, db: Session, operation_id: UUID, decision: ReviewDecision) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class Inspection:
    """What is true now. Codes only: no address, subject or provider message."""

    provider: ProviderState
    retry_blockers: tuple[Blocker, ...]
    cancel_blockers: tuple[Blocker, ...]


@dataclass(frozen=True, slots=True)
class Resolution:
    result: ReviewResult
    inspection: Inspection | None = None


def _inspect(db: Session, admin: IdentityProviderAdmin, row: Any) -> Inspection:
    """Compare the held operation with the local account and with the provider (by subject).
    Local facts matter for a retry; a cancellation writes nothing and needs only the proof that
    the provider never changed."""
    retry: list[Blocker] = []
    cancel: list[Blocker] = []
    if row.user_status != "ACTIVE":
        retry.append(Blocker.ACCOUNT_NOT_ACTIVE)
    if row.local_email != row.old_email:
        retry.append(Blocker.LOCAL_ADDRESS_CHANGED)
    # The lock of first sign-in and provider sync: nobody takes the address while we look.
    lock_email(db, row.new_email_normalized)
    if db.execute(
        text("SELECT EXISTS (SELECT 1 FROM users WHERE email_normalized = :e AND id <> :u)"),
        {"e": row.new_email_normalized, "u": row.user_id},
    ).scalar_one():
        retry.append(Blocker.ADDRESS_TAKEN_LOCALLY)
    provider = ProviderState.UNAVAILABLE
    owner_elsewhere = False
    try:
        actual = admin.get_email_state(row.auth_subject)
        state = classify_identity_state(
            subject=row.auth_subject,
            old_email=row.old_email,
            new_email=row.new_email,
            actual=actual,
        )
        if state == "APPLY":
            owner = admin.find_user_by_email(row.new_email)
            owner_elsewhere = owner is not None and owner.subject != row.auth_subject
        provider = {
            "APPLY": ProviderState.NOT_APPLIED,
            "FINALIZE": ProviderState.APPLIED,
        }.get(state, ProviderState.DIVERGENT)
    except IdpAdminError:
        pass
    if provider is ProviderState.UNAVAILABLE:
        retry.append(Blocker.PROVIDER_UNAVAILABLE)
        cancel.append(Blocker.PROVIDER_UNAVAILABLE)
    elif provider is ProviderState.DIVERGENT:
        retry.append(Blocker.PROVIDER_DIVERGENT)
        cancel.append(Blocker.PROVIDER_DIVERGENT)
    elif provider is ProviderState.APPLIED:
        cancel.append(Blocker.CHANGE_ALREADY_APPLIED)
    elif owner_elsewhere:
        retry.append(Blocker.ADDRESS_TAKEN_AT_PROVIDER)
    return Inspection(provider, tuple(retry), tuple(cancel))


def resolve_review(
    factory: sessionmaker[Session],
    admin: IdentityProviderAdmin,
    operation_id: UUID,
    decision: ReviewDecision,
    *,
    authority: ReviewAuthority | None = None,
    now: datetime | None = None,
) -> Resolution:
    """Carry out one decision in one transaction under the worker database role. Repeating it
    changes nothing; two callers are serialised by the row lock. Raises ``ReviewForbidden``."""
    allowed = authority or DenyAllReview()
    with session_scope(factory, RequestContext()) as db:
        if allowed.permits(db, operation_id, decision):
            return _resolve(db, admin, operation_id, decision, now or datetime.now(UTC))
        _audit(db, None, decision, "FORBIDDEN", Outcome.DENIED)
    raise ReviewForbidden("this review decision is not permitted")


def _resolve(
    db: Session,
    admin: IdentityProviderAdmin,
    operation_id: UUID,
    decision: ReviewDecision,
    now: datetime,
) -> Resolution:
    row = db.execute(
        text("""
        SELECT o.status, o.user_id, o.old_email, o.new_email, o.new_email_normalized,
               u.auth_subject, u.email AS local_email, u.status AS user_status
        FROM email_change_operations o JOIN users u ON u.id = o.user_id
        WHERE o.id = :id FOR UPDATE OF o, u
    """),
        {"id": operation_id},
    ).one_or_none()
    if row is None:
        return Resolution(ReviewResult.NOT_IN_REVIEW)
    if row.status != "MANUAL_REVIEW":
        done = {
            ReviewDecision.RETRY: ("APPLYING", "COMPLETED"),
            ReviewDecision.CANCEL: ("CANCELLED",),
        }[decision]
        repeated = row.status in done
        return Resolution(ReviewResult.ALREADY_RESOLVED if repeated else ReviewResult.NOT_IN_REVIEW)
    inspection = _inspect(db, admin, row)
    blockers = (
        inspection.retry_blockers
        if decision is ReviewDecision.RETRY
        else inspection.cancel_blockers
    )
    if blockers:
        _audit(db, row.user_id, decision, blockers[0].value, Outcome.FAILURE)
        return Resolution(ReviewResult.REFUSED, inspection)
    db.execute(
        text("SELECT set_config('app.email_change_review', :id, true)"), {"id": str(operation_id)}
    )
    if decision is ReviewDecision.RETRY:
        # A new, bounded series of attempts: ten, within 24 hours from now.
        statement = """
            UPDATE email_change_operations SET status='APPLYING', attempts=0, confirmed_at=:now,
                next_attempt_at=:now, lease_id=NULL, lease_until=NULL
            WHERE id=:id AND status='MANUAL_REVIEW' RETURNING id
        """
        parameters: dict[str, object] = {"id": operation_id, "now": now}
        result = ReviewResult.RETRY_QUEUED
    else:
        statement = """
            UPDATE email_change_operations SET status='CANCELLED', old_email=NULL,
                new_email=NULL, new_email_normalized=NULL, next_attempt_at=NULL,
                lease_id=NULL, lease_until=NULL
            WHERE id=:id AND status='MANUAL_REVIEW' RETURNING id
        """
        parameters = {"id": operation_id}
        result = ReviewResult.CANCELLED
    db.execute(text(statement), parameters).one()
    _audit(db, row.user_id, decision, result.value, Outcome.SUCCESS)
    return Resolution(result, inspection)


def _audit(
    db: Session,
    subject_user_id: UUID | None,
    decision: ReviewDecision,
    result: str,
    outcome: Outcome,
) -> None:
    record(
        db,
        AuditEvent(
            action="identity.email.change_reviewed",
            outcome=outcome,
            actor_type=ActorType.SYSTEM,  # the operator's identity arrives with T10
            subject_user_id=subject_user_id,
            details={"decision": decision.value, "result": result},
        ),
    )
