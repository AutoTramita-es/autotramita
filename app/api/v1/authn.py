"""Shared authentication plumbing of the API routes (F2-T06/T07): the models every session
answer uses, the request facts recorded in audit, and ``authenticated`` - one transaction in
which a cookie (web) or bearer (mobile) session is validated and the handler works."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import ip_prefix, record_independent, ua_family
from app.auth.errors import (
    AmbiguousCredentials,
    AuthRequired,
    CsrfInvalid,
    SessionSecurityViolation,
    TokenInvalid,
)
from app.auth.runtime import AuthRuntime
from app.auth.sessions import service as sessions
from app.auth.tokens import VerifiedToken
from app.auth.web.csrf import SAFE_METHODS, csrf_token, verify_csrf
from app.core.db import RequestContext, session_scope
from app.core.ratelimit import client_ip
from fastapi import Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)
BEARER = "bearer "


class UserSummary(BaseModel):
    id: UUID
    email: str
    email_verified: bool
    status: str
    display_name: str | None
    preferred_language: str


class WorkspaceInfo(BaseModel):
    tenant_id: UUID | None
    branch_id: UUID | None
    context_version: int


class SessionInfo(BaseModel):
    session_id: UUID
    client_type: str
    user: UserSummary
    auth_level: str
    step_up_expires_at: datetime | None = Field(
        description="When the last step-up stops counting as fresh (null: none recorded)"
    )
    expires_at: datetime = Field(description="Absolute end of the session")
    idle_expires_at: datetime
    workspace: WorkspaceInfo | None
    csrf_token: str | None = Field(
        description="Cookie sessions: X-CSRF-Token for unsafe requests (null for bearer)"
    )


def request_facts(request: Request, rt: AuthRuntime) -> tuple[str | None, str | None]:
    peer = client_ip(request, rt.trusted_proxies)
    return ip_prefix(peer), ua_family(request.headers.get("user-agent"))


@dataclass(frozen=True, slots=True)
class AuthContext:
    """What a handler gets: the open transaction, the validated session and how the caller
    proved it (``credential`` for cookies, ``token`` for bearer requests)."""

    db: Session
    resolved: sessions.Resolved
    credential: str | None
    token: VerifiedToken | None


def bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header[: len(BEARER)].lower() == BEARER:
        return header[len(BEARER) :].strip()
    return None


def validate_bearer(request: Request, rt: AuthRuntime, raw: str) -> VerifiedToken:
    """Validate an access token. A refused one is recorded (AT-02 4.3) by its reason only,
    never the token; the record is best effort so the answer stays the same 401."""
    try:
        return rt.access_validator.validate(raw)
    except TokenInvalid as rejected:
        prefix, family = request_facts(request, rt)
        record_attempt(
            rt,
            AuditEvent(
                action="auth.token.invalid",
                outcome=Outcome.DENIED,
                actor_type=ActorType.ANONYMOUS,
                ip_prefix=prefix,
                ua_family=family,
                details={"reason": rejected.reason.value},
            ),
        )
        raise


def record_attempt(
    rt: AuthRuntime, event: AuditEvent, context: RequestContext | None = None
) -> None:
    """Record a refused attempt in its own transaction. The refusal stands even when the audit
    store cannot take the record; that is logged without any identifier."""
    try:
        record_independent(rt.factory, event, context or RequestContext())
    except SQLAlchemyError:
        log.warning("a refused attempt could not be recorded")


@contextmanager
def authenticated(
    request: Request, rt: AuthRuntime, *, lock: bool, touch: bool = True
) -> Iterator[AuthContext]:
    """One transaction in which the caller's session is validated and the handler works.

    A session cookie is checked together with the CSRF token for unsafe methods; a bearer token
    is validated as an access token and then matched to the application session of the same
    Keycloak session. Cookie and bearer together are refused. A theft signal revokes the session
    in its own transaction after this one has rolled back."""
    cookie = request.cookies.get(rt.settings.cookie_name)
    authorization = request.headers.get("authorization")
    if cookie and authorization:
        raise AmbiguousCredentials()
    if not cookie and not authorization:
        raise AuthRequired()
    token: VerifiedToken | None = None
    if cookie:
        if request.method not in SAFE_METHODS:
            try:
                verify_csrf(request, cookie, rt.origins)
            except CsrfInvalid:
                prefix, family = request_facts(request, rt)
                record_independent(
                    rt.factory,
                    AuditEvent(
                        action="authz.denied",
                        outcome=Outcome.DENIED,
                        actor_type=ActorType.ANONYMOUS,
                        ip_prefix=prefix,
                        ua_family=family,
                        details={"reason": "CSRF", "resource_type": "session"},
                    ),
                    RequestContext(),
                )
                raise
    else:
        raw = bearer_token(request)
        if raw is None:
            raise AuthRequired()
        token = validate_bearer(request, rt, raw)
    resolved: sessions.Resolved | None = None
    try:
        with session_scope(rt.factory, RequestContext()) as db:
            if token is not None:
                resolved = sessions.resolve_mobile(db, token, lock=lock)
            elif cookie:
                resolved = sessions.resolve_web(
                    db,
                    cookie,
                    lock=lock,
                    ua_family=ua_family(request.headers.get("user-agent")),
                )
            else:  # pragma: no cover - excluded above
                raise AuthRequired()
            yield AuthContext(db, resolved, cookie, token)
    except SessionSecurityViolation as violation:
        sessions.revoke_independent(rt.factory, violation)
        raise
    if touch and resolved is not None:
        sessions.touch(rt.factory, resolved, rt.policy)


def session_info(
    rt: AuthRuntime, resolved: sessions.Resolved, credential: str | None
) -> SessionInfo:
    s, u = resolved.session, resolved.user
    window = timedelta(minutes=rt.settings.step_up_window_minutes)
    return SessionInfo(
        session_id=s.id,
        client_type=s.client_type.value,
        user=UserSummary(
            id=u.id,
            email=u.email,
            email_verified=u.email_verified_at is not None,
            status=u.status.value,
            display_name=u.display_name,
            preferred_language=u.preferred_language,
        ),
        auth_level=s.auth_level.value,
        step_up_expires_at=(s.step_up_at + window) if s.step_up_at else None,
        expires_at=s.absolute_expires_at,
        idle_expires_at=s.idle_expires_at,
        workspace=(
            WorkspaceInfo(
                tenant_id=s.active_tenant_id,
                branch_id=s.active_branch_id,
                context_version=s.context_version,
            )
            if s.active_tenant_id
            else None
        ),
        csrf_token=csrf_token(credential) if credential else None,
    )
