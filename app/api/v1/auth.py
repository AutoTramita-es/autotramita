"""Web sign-in endpoints (F2-T06): OIDC login and callback, logout, back-channel logout,
session information and step-up. Cookie sessions only; bearer sessions arrive with F2-T07.

Every response here is ``Cache-Control: no-store``. Failures of the sign-in return answer with
one generic error (``AUTH_CALLBACK_REJECTED``); the cause is recorded in the audit log."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from urllib.parse import parse_qs
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import ip_prefix, record, record_independent, ua_family
from app.auth import credentials
from app.auth.errors import (
    AccountDisabled,
    AmbiguousCredentials,
    AuthCallbackRejected,
    AuthRequired,
    CsrfInvalid,
    LogoutTokenInvalid,
    SessionSecurityViolation,
    TokenInvalid,
)
from app.auth.runtime import AuthRuntime, runtime_of
from app.auth.sessions import service as sessions
from app.auth.sessions.models import AuthLevel, ClientType, RevokeReason, UserSession
from app.auth.settings import AuthLimitSettings
from app.auth.tokens import VerifiedIdToken
from app.auth.web import cookies
from app.auth.web import service as web_service
from app.auth.web.csrf import SAFE_METHODS, csrf_token, verify_csrf
from app.auth.web.oidc_flow import (
    binder_digest,
    new_binder,
    new_nonce,
    new_state,
    pkce_pair,
)
from app.auth.web.redirects import safe_return_to
from app.auth.web.stepup import StepUpPurpose, authorization_params, level_from_acr
from app.core.db import RequestContext, session_scope
from app.core.errors import TooManyRequests
from app.core.ratelimit import IPNetwork, Policy, by_ip, client_ip, rate_limit
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

logger = logging.getLogger(__name__)
INTERNAL = {"x-internal": True}  # browser redirects: kept out of the generated API clients
MAX_LOGOUT_BODY = 16_384
MAX_CODE_LENGTH = 2048


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
    csrf_token: str = Field(description="Send as X-CSRF-Token on every unsafe request")


class LogoutResult(BaseModel):
    end_session_url: str = Field(description="Where to send the browser to end the SSO session")


class StepUpRequest(BaseModel):
    purpose: StepUpPurpose
    return_to: str | None = Field(default=None, max_length=512)


class StepUpResult(BaseModel):
    redirect_url: str


def _request_facts(request: Request, rt: AuthRuntime) -> tuple[str | None, str | None]:
    peer = client_ip(request, rt.trusted_proxies)
    return ip_prefix(peer), ua_family(request.headers.get("user-agent"))


def _reject(request: Request, rt: AuthRuntime, reason: str) -> NoReturn:
    prefix, family = _request_facts(request, rt)
    record_independent(
        rt.factory,
        AuditEvent(
            action="auth.callback.rejected",
            outcome=Outcome.DENIED,
            actor_type=ActorType.ANONYMOUS,
            ip_prefix=prefix,
            ua_family=family,
            details={"reason": reason},
        ),
        RequestContext(),
    )
    raise AuthCallbackRejected()


def _credential(request: Request, rt: AuthRuntime) -> str:
    cookie = request.cookies.get(rt.settings.cookie_name)
    if cookie and request.headers.get("authorization"):
        raise AmbiguousCredentials()
    if not cookie:
        raise AuthRequired()
    return cookie


@contextmanager
def authenticated(
    request: Request, rt: AuthRuntime, *, lock: bool, touch: bool = True
) -> Iterator[tuple[Session, sessions.Resolved, str]]:
    """One transaction in which the cookie session is validated (and, for unsafe methods, the
    CSRF token) and the handler works. A theft signal revokes the session in its own
    transaction after this one has rolled back."""
    credential = _credential(request, rt)
    if request.method not in SAFE_METHODS:
        try:
            verify_csrf(request, credential, rt.origins)
        except CsrfInvalid:
            prefix, family = _request_facts(request, rt)
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
    resolved: sessions.Resolved | None = None
    try:
        with session_scope(rt.factory, RequestContext()) as db:
            resolved = sessions.resolve_web(
                db,
                credential,
                lock=lock,
                ua_family=ua_family(request.headers.get("user-agent")),
            )
            yield db, resolved, credential
    except SessionSecurityViolation as violation:
        sessions.revoke_independent(rt.factory, violation)
        raise
    if touch and resolved is not None:
        sessions.touch(rt.factory, resolved, rt.policy)


def _session_info(rt: AuthRuntime, resolved: sessions.Resolved, credential: str) -> SessionInfo:
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
        csrf_token=csrf_token(credential),
    )


def _new_flow(
    request: Request, rt: AuthRuntime, *, purpose: str, return_to: str | None, extra: dict[str, Any]
) -> tuple[str, str, str, str, str, str]:
    origin, client = rt.site_for(request)
    state, nonce, binder = new_state(), new_nonce(), new_binder()
    verifier, challenge = pkce_pair()
    rt.flows.put(
        state,
        {
            "purpose": purpose,
            "nonce": nonce,
            "verifier": verifier,
            "binder": binder_digest(binder),
            "return_to": safe_return_to(return_to),
            "origin": origin,
            "client_type": client.value,
            "created": int(rt.clock()),
            **extra,
        },
    )
    return origin, state, nonce, binder, verifier, challenge


def build_auth_router(limits: AuthLimitSettings, trusted: Sequence[IPNetwork] = ()) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])
    ip = by_ip(trusted)
    login_limit = rate_limit(Policy("auth_login", limits.login_per_min_ip), ip, trusted)
    callback_limit = rate_limit(Policy("auth_callback", limits.callback_per_min_ip), ip, trusted)

    @router.get(
        "/login",
        status_code=302,
        summary="Start the sign-in (redirects to the identity provider)",
        responses={302: {"description": "Redirect to the identity provider"}},
        dependencies=[Depends(login_limit)],
        openapi_extra=INTERNAL,
    )
    def login(request: Request, return_to: str | None = None) -> Response:
        rt = runtime_of(request)
        origin, state, nonce, binder, _verifier, challenge = _new_flow(
            request, rt, purpose="LOGIN", return_to=return_to, extra={}
        )
        url = rt.endpoints.authorization_url(
            redirect_uri=rt.callback_uri(origin), state=state, nonce=nonce, challenge=challenge
        )
        response = RedirectResponse(url, status_code=302)
        cookies.set_flow_cookie(response, rt.settings, binder)
        cookies.no_store(response)
        return response

    @router.get(
        "/callback",
        status_code=302,
        summary="Finish the sign-in (the identity provider redirects here)",
        responses={302: {"description": "Redirect to the application"}},
        dependencies=[Depends(callback_limit)],
        openapi_extra=INTERNAL,
    )
    def callback(
        request: Request,
        code: str | None = None,
        state: str | None = None,
        error: str | None = None,
    ) -> Response:
        rt = runtime_of(request)
        flow = rt.flows.take(state)  # single use: a replayed callback finds nothing
        if error or not code or len(code) > MAX_CODE_LENGTH:
            _reject(request, rt, "PROVIDER_ERROR" if error else "MISSING_CODE")
        if flow is None:
            _reject(request, rt, "STATE")
        binder = request.cookies.get(rt.settings.flow_cookie_name, "")
        if not binder or not credentials.equal(
            binder_digest(binder).encode(), str(flow.get("binder", "")).encode()
        ):
            _reject(request, rt, "BINDER")
        origin, client_type = rt.site_for(request)
        if flow.get("origin") != origin:
            _reject(request, rt, "ORIGIN")
        try:
            raw = rt.exchanger(
                code=code, redirect_uri=rt.callback_uri(origin), verifier=str(flow["verifier"])
            )
        except AuthCallbackRejected:
            _reject(request, rt, "EXCHANGE")
        try:
            identity = rt.id_validator.validate(
                raw, client_id=rt.settings.web_client_id, nonce=str(flow["nonce"])
            )
        except TokenInvalid as rejected:
            _reject(request, rt, f"TOKEN_{rejected.reason.value.upper()}")
        if flow.get("purpose") == "STEP_UP":
            response = _finish_step_up(request, rt, flow, identity)
        else:
            response = _finish_login(request, rt, flow, identity, client_type)
        cookies.clear_flow_cookie(response, rt.settings)
        cookies.no_store(response)
        return response

    def _finish_login(
        request: Request,
        rt: AuthRuntime,
        flow: dict[str, Any],
        identity: VerifiedIdToken,
        client_type: ClientType,
    ) -> Response:
        if not identity.email:
            _reject(request, rt, "TOKEN_EMAIL")
        prefix, family = _request_facts(request, rt)
        outcome = web_service.complete_login(
            rt, identity, client_type, email=identity.email, ip_prefix=prefix, ua_family=family
        )
        if outcome.disabled_user_id is not None:
            record_independent(
                rt.factory,
                AuditEvent(
                    action="auth.login.failed",
                    outcome=Outcome.DENIED,
                    actor_type=ActorType.ANONYMOUS,
                    subject_user_id=outcome.disabled_user_id,
                    ip_prefix=prefix,
                    ua_family=family,
                    details={"client_id": rt.settings.web_client_id, "error": "ACCOUNT_DISABLED"},
                ),
            )
            raise AccountDisabled()
        response = RedirectResponse(str(flow.get("return_to", "/")), status_code=302)
        remaining = int((outcome.absolute_expires_at - datetime.now(UTC)).total_seconds())
        cookies.set_session_cookie(response, rt.settings, outcome.secret, max_age_seconds=remaining)
        return response

    def _finish_step_up(
        request: Request, rt: AuthRuntime, flow: dict[str, Any], identity: VerifiedIdToken
    ) -> Response:
        credential = request.cookies.get(rt.settings.cookie_name, "")
        purpose = StepUpPurpose(str(flow.get("step_up_purpose", "REAUTHENTICATE")))
        achieved = level_from_acr(identity.acr)
        fresh = identity.auth_time is not None and (
            identity.auth_time >= int(flow["created"]) - rt.settings.leeway_seconds
        )
        failed = purpose is StepUpPurpose.MFA and achieved is not AuthLevel.LOA2
        failed = failed or (purpose is StepUpPurpose.REAUTHENTICATE and not fresh)
        secret = ""
        absolute = datetime.now(UTC)
        with session_scope(rt.factory, RequestContext()) as db:
            try:
                resolved = sessions.resolve_web(db, credential, lock=True)
            except Exception:
                _reject(request, rt, "STEP_UP_SESSION")
            if (
                str(resolved.session.id) != flow.get("session_id")
                or resolved.user.auth_subject != identity.subject
                or flow.get("subject") != identity.subject
            ):
                _reject(request, rt, "STEP_UP_SUBJECT")
            if failed:
                record(
                    db,
                    AuditEvent(
                        action="security.step_up.failed",
                        outcome=Outcome.FAILURE,
                        actor_type=ActorType.USER,
                        actor_user_id=resolved.user.id,
                        subject_user_id=resolved.user.id,
                        details={"level": achieved.value},
                    ),
                )
            else:
                secret = (
                    sessions.record_step_up(db, resolved.session.id, level=achieved, rotate=True)
                    or ""
                )
                record(
                    db,
                    AuditEvent(
                        action="security.step_up.succeeded",
                        outcome=Outcome.SUCCESS,
                        actor_type=ActorType.USER,
                        actor_user_id=resolved.user.id,
                        subject_user_id=resolved.user.id,
                        details={"level": achieved.value},
                    ),
                )
                absolute = resolved.session.absolute_expires_at
        if failed:
            raise AuthCallbackRejected()
        response = RedirectResponse(str(flow.get("return_to", "/")), status_code=302)
        remaining = int((absolute - datetime.now(UTC)).total_seconds())
        cookies.set_session_cookie(response, rt.settings, secret, max_age_seconds=remaining)
        return response

    @router.post(
        "/logout",
        summary="Sign out of this session",
        response_model=LogoutResult,
    )
    def logout(request: Request, response: Response) -> LogoutResult:
        rt = runtime_of(request)
        with authenticated(request, rt, lock=True, touch=False) as (db, resolved, _):
            sessions.revoke(
                db,
                resolved.session.id,
                reason=RevokeReason.LOGOUT,
                actor_user_id=resolved.user.id,
            )
            record(
                db,
                AuditEvent(
                    action="auth.logout",
                    outcome=Outcome.SUCCESS,
                    actor_type=ActorType.USER,
                    actor_user_id=resolved.user.id,
                    subject_user_id=resolved.user.id,
                    actor_session_id=resolved.session.id,
                    details={"client_type": resolved.session.client_type.value},
                ),
            )
            origin = rt.site_for(request)[0]
        cookies.clear_session_cookie(response, rt.settings)
        cookies.no_store(response)
        return LogoutResult(end_session_url=rt.endpoints.end_session_url(f"{origin}/"))

    @router.get("/session", summary="State of the current session", response_model=SessionInfo)
    def session_state(request: Request, response: Response) -> SessionInfo:
        rt = runtime_of(request)
        with authenticated(request, rt, lock=False) as (_db, resolved, credential):
            info = _session_info(rt, resolved, credential)
        cookies.no_store(response)
        return info

    @router.post(
        "/step-up",
        summary="Ask for a fresh or stronger authentication",
        response_model=StepUpResult,
    )
    def step_up(request: Request, body: StepUpRequest, response: Response) -> StepUpResult:
        rt = runtime_of(request)
        with authenticated(request, rt, lock=False) as (_db, resolved, _):
            session: UserSession = resolved.session
            subject = resolved.user.auth_subject
        limiter = request.app.state.rate_limiter
        if limiter is not None:
            decision = limiter.check(
                Policy("auth_step_up", limits.step_up_per_hour_session, 3600),
                f"session:{session.id}",
            )
            if not decision.allowed:
                raise TooManyRequests(
                    "Too many step-up requests.",
                    headers={"Retry-After": str(decision.retry_after_seconds)},
                )
        params = authorization_params(body.purpose)
        origin, state, nonce, binder, _verifier, challenge = _new_flow(
            request,
            rt,
            purpose="STEP_UP",
            return_to=body.return_to,
            extra={
                "step_up_purpose": body.purpose.value,
                "session_id": str(session.id),
                "subject": subject,
            },
        )
        url = rt.endpoints.authorization_url(
            redirect_uri=rt.callback_uri(origin),
            state=state,
            nonce=nonce,
            challenge=challenge,
            acr_values=params.acr_values,
            prompt=params.prompt,
            max_age=params.max_age,
        )
        cookies.set_flow_cookie(response, rt.settings, binder)
        cookies.no_store(response)
        return StepUpResult(redirect_url=url)

    @router.post(
        "/oidc/backchannel-logout",
        status_code=204,
        summary="Back-channel logout from the identity provider",
        dependencies=[Depends(callback_limit)],
        openapi_extra={
            "x-internal": True,
            "requestBody": {
                "required": True,
                "content": {
                    "application/x-www-form-urlencoded": {
                        "schema": {
                            "type": "object",
                            "required": ["logout_token"],
                            "properties": {"logout_token": {"type": "string"}},
                        }
                    }
                },
            },
        },
    )
    async def backchannel_logout(request: Request) -> Response:
        rt = runtime_of(request)
        content_type = request.headers.get("content-type", "")
        if not content_type.startswith("application/x-www-form-urlencoded"):
            raise LogoutTokenInvalid()
        body = await request.body()
        if len(body) > MAX_LOGOUT_BODY:
            raise LogoutTokenInvalid()
        try:
            fields = parse_qs(body.decode("ascii"), strict_parsing=False)
        except (UnicodeDecodeError, ValueError):
            raise LogoutTokenInvalid() from None
        token = (fields.get("logout_token") or [""])[0]
        await run_in_threadpool(_process_logout, request, rt, token)
        response = Response(status_code=204)
        cookies.no_store(response)
        return response

    def _process_logout(request: Request, rt: AuthRuntime, token: str) -> None:
        prefix, family = _request_facts(request, rt)
        try:
            verified = rt.logout_validator.validate(token, client_id=rt.settings.web_client_id)
        except TokenInvalid:
            raise LogoutTokenInvalid() from None
        ttl = max(verified.expires_at - int(rt.clock()), 1) + rt.settings.leeway_seconds
        if not rt.jti.first_use(verified.jti, ttl_seconds=ttl):
            record_independent(
                rt.factory,
                AuditEvent(
                    action="auth.token.invalid",
                    outcome=Outcome.DENIED,
                    actor_type=ActorType.IDP,
                    ip_prefix=prefix,
                    ua_family=family,
                    details={"reason": "LOGOUT_REPLAY"},
                ),
            )
            raise LogoutTokenInvalid()
        web_service.revoke_for_logout(rt, verified)

    return router
