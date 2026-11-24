"""Application-initiated security actions (F2-T09, D23/D37): password change and second-factor
enrolment run on Keycloak's own pages (``kc_action``), started from a fresh authentication.

The browser only comes back with ``kc_action_status=success``, which anybody could type, so the
application never trusts it: it asks the identity provider for the credential and requires one
that was created after the flow started. Only then sessions are ended, the audit record is
written and the notice is sent."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, NoReturn
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.idp import SECOND_FACTOR_TYPES, IdpAdminError, IdpCredential
from app.auth.runtime import AuthRuntime
from app.auth.security.notify import Notice, NoticeKind, send_quietly
from app.auth.security.recovery import latest_password
from app.auth.sessions import service as sessions
from app.auth.sessions.models import RevokeReason
from app.core.db import RequestContext, session_scope


class SecurityAction(StrEnum):
    PASSWORD_CHANGE = "PASSWORD_CHANGE"  # noqa: S105 - an action name, not a password
    MFA_TOTP = "MFA_TOTP"
    MFA_RECOVERY_CODES = "MFA_RECOVERY_CODES"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    kc_action: str
    credential_types: frozenset[str]
    factor: str | None  # audit code of the second factor, None for the password


SPECS: dict[SecurityAction, ActionSpec] = {
    SecurityAction.PASSWORD_CHANGE: ActionSpec("UPDATE_PASSWORD", frozenset({"password"}), None),
    SecurityAction.MFA_TOTP: ActionSpec("CONFIGURE_TOTP", frozenset({"otp"}), "TOTP"),
    SecurityAction.MFA_RECOVERY_CODES: ActionSpec(
        "CONFIGURE_RECOVERY_AUTHN_CODES", frozenset({"recovery-authn-codes"}), "RECOVERY_CODES"
    ),
}


@dataclass(frozen=True, slots=True)
class ActionResult:
    succeeded: bool
    secret: str = ""
    absolute_expires_at: datetime | None = None


def _created_since(credentials: list[IdpCredential], types: frozenset[str], since: float) -> bool:
    return any(
        c.type in types and c.created_ms is not None and c.created_ms / 1000 >= since
        for c in credentials
    )


def complete_action(
    rt: AuthRuntime,
    *,
    credential: str,
    flow: dict[str, Any],
    subject: str,
    kc_status: str | None,
    reject: Callable[[str], NoReturn],
) -> ActionResult:
    action = SecurityAction(str(flow["security_action"]))
    spec = SPECS[action]
    with session_scope(rt.factory, RequestContext()) as db:
        try:
            resolved = sessions.resolve_web(db, credential, lock=True)
        except Exception:
            reject("ACTION_SESSION")
        if (
            str(resolved.session.id) != flow.get("session_id")
            or resolved.user.auth_subject != subject
            or flow.get("subject") != subject
        ):
            reject("ACTION_SUBJECT")
        verified = False
        found: list[IdpCredential] = []
        if kc_status == "success" and rt.admin is not None:
            try:
                found = rt.admin.list_credentials(subject)
            except IdpAdminError:
                found = []
            since = float(flow["created"]) - rt.settings.leeway_seconds
            verified = _created_since(found, spec.credential_types, since)
        user: UUID = resolved.user.id
        if not verified:
            return ActionResult(False)
        secret = ""
        if action is SecurityAction.PASSWORD_CHANGE:
            sessions.revoke_others(
                db, user, resolved.session.id, reason=RevokeReason.PASSWORD_CHANGED,
                actor_user_id=user,
            )  # fmt: skip
            secret = sessions.rotate_credential(db, resolved.session.id)
            audit = AuditEvent(
                action="security.password.changed",
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.USER,
                actor_user_id=user,
                subject_user_id=user,
                actor_session_id=resolved.session.id,
                details={},
            )
            kind = NoticeKind.PASSWORD_CHANGED
        else:
            audit = AuditEvent(
                action="security.mfa.enrolled",
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.USER,
                actor_user_id=user,
                subject_user_id=user,
                actor_session_id=resolved.session.id,
                details={"factor": spec.factor},
            )
            kind = NoticeKind.MFA_ENROLLED
        record(db, audit)
        email, absolute = resolved.user.email, resolved.session.absolute_expires_at
    changed = latest_password(found)
    if action is SecurityAction.PASSWORD_CHANGE and rt.markers is not None and changed:
        # Another browser still signed in at the provider must authenticate again.
        rt.markers.record_change(subject, changed)
    send_quietly(rt.notifier, Notice(kind, email, datetime.now(UTC)))
    return ActionResult(True, secret, absolute)


def remove_second_factor(
    rt: AuthRuntime, db: Any, *, user_id: UUID, session_id: UUID, subject: str, credential_id: str
) -> str | None:
    """Delete one second factor of this person. Returns the audit code of the factor, or
    ``None`` when the person has no such factor (their credentials are the only ones looked at)."""
    if rt.admin is None:
        raise IdpAdminError("admin client is not configured")
    owned = [c for c in rt.admin.list_credentials(subject) if c.id == credential_id]
    if not owned or owned[0].type not in SECOND_FACTOR_TYPES:
        return None
    factor = {
        "otp": "TOTP",
        "webauthn": "WEBAUTHN",
        "webauthn-passwordless": "WEBAUTHN",
        "recovery-authn-codes": "RECOVERY_CODES",
    }[owned[0].type]
    rt.admin.delete_credential(subject, credential_id)
    record(
        db,
        AuditEvent(
            action="security.mfa.removed",
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER,
            actor_user_id=user_id,
            subject_user_id=user_id,
            actor_session_id=session_id,
            details={"factor": factor},
        ),
    )
    return factor
