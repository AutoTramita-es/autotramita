"""Mobile sessions (F2-T07, D04, model A): the app keeps Keycloak tokens, the application keeps
the session. ``open_session`` ties a verified access token to an application session.

* Idempotent: the same Keycloak session returns the same live application session.
* A revoked session is never reopened by the token that outlived it (it stays valid for a few
  minutes): the person must authenticate again. Revocation therefore cannot be undone by a
  device that still holds a token.
* No refresh token ever reaches the server; the device refreshes directly with Keycloak.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.errors import SessionRevoked
from app.auth.runtime import AuthRuntime
from app.auth.sessions import repository as session_repository
from app.auth.sessions import service as sessions
from app.auth.sessions.models import ClientType, UserSession
from app.auth.tokens import VerifiedToken
from app.auth.users import repository as user_repository
from app.auth.users import service as users
from app.auth.users.models import User, UserStatus
from app.auth.web.stepup import level_from_acr
from app.core.db import RequestContext, apply_context, session_scope
from app.core.errors import BadRequest
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)
_LIVE_KEY = "user_sessions_kc_session_live"


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    label: str | None = None
    platform: str | None = None
    app_version: str | None = None


@dataclass(frozen=True, slots=True)
class MobileOutcome:
    session: UserSession | None
    user: User | None
    created: bool
    disabled_user_id: UUID | None = None


def open_session(
    rt: AuthRuntime,
    token: VerifiedToken,
    device: DeviceInfo,
    *,
    ip_prefix: str | None,
    now: datetime | None = None,
) -> MobileOutcome:
    moment = now or datetime.now(UTC)
    with session_scope(rt.factory, RequestContext(auth_subject=token.subject)) as db:
        if token.email:
            user = users.provision_or_link(
                db,
                subject=token.subject,
                email=token.email,
                email_verified=bool(token.email_verified),
                audit_factory=rt.factory,
                now=moment,
            ).user
        else:
            found = user_repository.get_by_subject(db, token.subject, lock="share")
            if found is None:
                raise BadRequest("The token carries no e-mail address.", code="INVALID_EMAIL")
            apply_context(db, RequestContext(user_id=found.id, auth_subject=token.subject))
            user = found
        if user.status not in (UserStatus.ACTIVE, UserStatus.PENDING_VERIFICATION):
            return MobileOutcome(None, None, False, disabled_user_id=user.id)
        # Serialise per user: a second concurrent request waits, then finds the first one's session.
        session_repository.lock_user_for_new_session(db, user.id)
        latest = session_repository.by_kc_session(
            db, user.id, token.session_id, ClientType.MOBILE.value, lock=False
        )
        if latest is not None and latest.is_revoked:
            raise SessionRevoked()
        if latest is not None and latest.is_live(moment):
            return MobileOutcome(latest, user, False)
        level = level_from_acr(token.acr)
        try:
            with db.begin_nested():
                created = sessions.create_session(
                    db,
                    user_id=user.id,
                    client_type=ClientType.MOBILE,
                    kc_session_id=token.session_id,
                    auth_time=datetime.fromtimestamp(token.auth_time or token.issued_at, tz=UTC),
                    policy=rt.policy,
                    auth_level=level,
                    device_label=device.label,
                    device_platform=device.platform,
                    app_version=device.app_version,
                    ip_prefix=ip_prefix,
                    now=moment,
                )
        except IntegrityError as exc:
            diag = getattr(exc.orig, "diag", None)
            if getattr(diag, "constraint_name", None) != _LIVE_KEY:
                raise
            existing = session_repository.by_kc_session(
                db, user.id, token.session_id, ClientType.MOBILE.value, lock=False
            )
            if existing is None:  # pragma: no cover - the live row exists after the conflict
                raise
            return MobileOutcome(existing, user, False)
        users.record_login(db, user, now=moment)
        record(
            db,
            AuditEvent(
                action="auth.login.succeeded",
                outcome=Outcome.SUCCESS,
                actor_type=ActorType.USER,
                actor_user_id=user.id,
                subject_user_id=user.id,
                actor_session_id=created.session.id,
                ip_prefix=ip_prefix,
                details={"client_type": ClientType.MOBILE.value, "auth_level": level.value},
            ),
        )
        return MobileOutcome(created.session, user, True)
