"""Mobile session opening and the session list and revocation endpoints (F2-T07).

``POST /auth/mobile/session`` is the one route that accepts a valid access token without an
application session; every other route needs the session behind it. Sessions of the signed-in
person only: another person's session is simply not there (404). The list has no cursor
because a person can hold at most ten sessions (D15)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from app.api.v1.authn import (
    AuthContext,
    SessionInfo,
    authenticated,
    bearer_token,
    request_facts,
    session_info,
)
from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record_independent
from app.auth.errors import AccountDisabled, AmbiguousCredentials, AuthRequired
from app.auth.mobile import service as mobile
from app.auth.mobile.service import DeviceInfo
from app.auth.runtime import AuthRuntime, runtime_of
from app.auth.sessions import repository
from app.auth.sessions import service as sessions
from app.auth.sessions.models import AuthLevel, RevokeReason, UserSession
from app.auth.settings import AuthLimitSettings
from app.auth.web import cookies
from app.auth.web.stepup import require_step_up, require_token_step_up
from app.core.db import RequestContext
from app.core.errors import NotFound, Problem
from app.core.pagination import CursorPage
from app.core.ratelimit import IPNetwork, Policy, by_ip, rate_limit
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Label = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f]{1,80}$")]
Platform = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._:-]{1,40}$")]
AppVersion = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._+-]{1,40}$")]


class DeviceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Label | None = None
    platform: Platform | None = None
    app_version: AppVersion | None = None


class MobileSessionRequest(BaseModel):
    """No refresh token (or any other token) is accepted here: unknown fields are refused."""

    model_config = ConfigDict(extra="forbid")

    device: DeviceBody = Field(default_factory=DeviceBody)


class SessionSummary(BaseModel):
    id: UUID
    client_type: str
    device_label: str | None
    platform: str | None
    country_code: str | None
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    current: bool


class Revoked(BaseModel):
    revoked: int


def _summary(item: UserSession, current: UUID) -> SessionSummary:
    return SessionSummary(
        id=item.id,
        client_type=item.client_type.value,
        device_label=item.device_label,
        platform=item.platform,
        country_code=item.country_code,
        created_at=item.created_at,
        last_activity_at=item.last_activity_at,
        expires_at=min(item.idle_expires_at, item.absolute_expires_at),
        current=item.id == current,
    )


def _step_up_for_all(rt: AuthRuntime, ctx: AuthContext) -> None:
    window = rt.settings.step_up_window_minutes * 60
    now = datetime.now(UTC)
    if ctx.token is not None:
        require_token_step_up(ctx.token, level=AuthLevel.LOA1, max_age_seconds=window, now=now)
    else:
        require_step_up(ctx.resolved.session, level=AuthLevel.LOA1, max_age_seconds=window, now=now)


def build_sessions_router(
    limits: AuthLimitSettings, trusted: Sequence[IPNetwork] = ()
) -> APIRouter:
    router = APIRouter(tags=["sessions"])
    open_limit = rate_limit(
        Policy("auth_mobile_session", limits.login_per_min_ip), by_ip(trusted), trusted
    )

    @router.post(
        "/auth/mobile/session",
        summary="Open (or return) the application session of a signed-in mobile app",
        response_model=SessionInfo,
        responses={
            200: {"description": "The existing live session"},
            201: {"description": "Created"},
        },
        dependencies=[Depends(open_limit)],
    )
    def open_mobile_session(
        request: Request, body: MobileSessionRequest, response: Response
    ) -> SessionInfo:
        rt = runtime_of(request)
        if request.cookies.get(rt.settings.cookie_name):
            raise AmbiguousCredentials()
        raw = bearer_token(request)
        if raw is None:
            raise AuthRequired()
        token = rt.access_validator.validate(raw)
        prefix, _family = request_facts(request, rt)
        device = DeviceInfo(body.device.label, body.device.platform, body.device.app_version)
        outcome = mobile.open_session(rt, token, device, ip_prefix=prefix)
        if outcome.disabled_user_id is not None:
            record_independent(
                rt.factory,
                AuditEvent(
                    action="auth.login.failed",
                    outcome=Outcome.DENIED,
                    actor_type=ActorType.ANONYMOUS,
                    subject_user_id=outcome.disabled_user_id,
                    ip_prefix=prefix,
                    details={"client_id": token.client_id, "error": "ACCOUNT_DISABLED"},
                ),
                RequestContext(),
            )
            raise AccountDisabled()
        assert outcome.session is not None and outcome.user is not None  # noqa: S101
        response.status_code = 201 if outcome.created else 200
        return session_info(rt, sessions.Resolved(outcome.session, outcome.user), None)

    @router.get(
        "/sessions",
        summary="My signed-in sessions",
        response_model=CursorPage[SessionSummary],
    )
    def list_sessions(request: Request) -> CursorPage[SessionSummary]:
        rt = runtime_of(request)
        with authenticated(request, rt, lock=False) as ctx:
            current = ctx.resolved.session.id
            live = repository.list_live(ctx.db, ctx.resolved.user.id, datetime.now(UTC))
            return CursorPage[SessionSummary](items=[_summary(s, current) for s in live])

    @router.delete(
        "/sessions/{session_id}",
        status_code=204,
        summary="Sign out one of my sessions",
        response_class=Response,
    )
    def revoke_one(request: Request, session_id: UUID) -> Response:
        rt = runtime_of(request)
        with authenticated(request, rt, lock=True, touch=False) as ctx:
            user = ctx.resolved.user
            own = session_id == ctx.resolved.session.id
            done = sessions.revoke(
                ctx.db,
                session_id,
                reason=RevokeReason.LOGOUT if own else RevokeReason.USER_REVOKED,
                actor_user_id=user.id,
            )
            if not done:
                raise NotFound()  # not mine, not live, or not there: indistinguishable
        response = Response(status_code=204)
        if own:
            cookies.clear_session_cookie(response, rt.settings)
        return response

    @router.post(
        "/sessions/revoke-others", summary="Sign out all my other sessions", response_model=Revoked
    )
    def revoke_others(request: Request) -> Revoked:
        rt = runtime_of(request)
        with authenticated(request, rt, lock=True) as ctx:
            count = sessions.revoke_others(
                ctx.db,
                ctx.resolved.user.id,
                ctx.resolved.session.id,
                actor_user_id=ctx.resolved.user.id,
            )
        return Revoked(revoked=count)

    @router.post(
        "/sessions/revoke-all",
        summary="Sign out all my sessions, this one included (needs a fresh authentication)",
        response_model=Revoked,
        responses={401: {"model": Problem, "description": "Step-up required (RFC 9470)"}},
    )
    def revoke_all(request: Request, response: Response) -> Revoked:
        rt = runtime_of(request)
        with authenticated(request, rt, lock=True, touch=False) as ctx:
            _step_up_for_all(rt, ctx)
            count = sessions.DatabaseSessionRevoker().revoke_all(
                ctx.db,
                ctx.resolved.user.id,
                reason=RevokeReason.USER_REVOKED.value,
                actor_user_id=ctx.resolved.user.id,
            )
            web = ctx.token is None
        if web:
            cookies.clear_session_cookie(response, rt.settings)
        return Revoked(revoked=count)

    return router
