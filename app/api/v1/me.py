"""The signed-in person: profile and workspaces (F2-T08).

``GET /me`` and ``PATCH /me`` work for a person who has not verified the e-mail address yet
(they must be able to fix their profile and resend the verification). Identity, e-mail and status
are never writable here: they belong to the identity provider and to platform administrators."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from app.api.v1.auth import new_flow
from app.api.v1.authn import UserSummary
from app.api.v1.guards import Principal, request_scope, require_step_up, require_user
from app.auth import errors as auth_errors
from app.auth.email import normalize_email
from app.auth.errors import AuthorizationUnavailable
from app.auth.idp import SECOND_FACTOR_TYPES, IdpAdminError
from app.auth.runtime import AuthRuntime, runtime_of
from app.auth.security import actions, email_change, recovery
from app.auth.security.notify import Notice, NoticeKind, send_quietly
from app.auth.sessions.models import AuthLevel
from app.auth.settings import AuthLimitSettings
from app.auth.users import repository as user_repository
from app.auth.web import cookies
from app.core.errors import NotFound, TooManyRequests, UnprocessableEntity
from app.core.pagination import CursorPage
from app.core.ratelimit import IPNetwork, Policy
from app.core.versioning import check_version, ensure_updated, format_etag, if_match_version
from fastapi import APIRouter, BackgroundTasks, Depends, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints
from sqlalchemy.exc import IntegrityError

# A person whose e-mail is not verified yet may still read and fix their profile.
ANYONE = require_user(allow_unverified=True)
# D23: changing the password or a second factor needs a fresh authentication (10 minutes);
# taking a second factor away needs the second factor itself (LoA2).
FRESH = require_step_up(AuthLevel.LOA1, 600)
SECOND_FACTOR = require_step_up(AuthLevel.LOA2, 600)
DisplayName = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f]{1,120}$")]
Language = Annotated[str, StringConstraints(pattern=r"^[a-z]{2}(-[A-Z]{2})?$")]


class UserProfile(UserSummary):
    created_at: datetime
    version: int = Field(description="Send as If-Match when changing the profile")


class ProfilePatch(BaseModel):
    """Only the fields that are present change; ``display_name: null`` clears the name."""

    model_config = ConfigDict(extra="forbid")

    display_name: DisplayName | None = None
    preferred_language: Language | None = None


class WorkspaceOption(BaseModel):
    tenant_id: UUID
    branch_ids: list[UUID]
    default_branch_id: UUID | None


class SecondFactor(BaseModel):
    id: str
    type: str = Field(description="otp | webauthn | webauthn-passwordless | recovery-authn-codes")
    created_at: datetime | None


class SecurityOverview(BaseModel):
    email_verified: bool
    password_changed_at: datetime | None
    second_factors: list[SecondFactor]


class Accepted(BaseModel):
    status: Literal["accepted"] = "accepted"


class MfaEnrollment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: Literal["TOTP", "RECOVERY_CODES"] = "TOTP"
    return_to: str | None = Field(default=None, max_length=512)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    return_to: str | None = Field(default=None, max_length=512)


class EmailChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    new_email: str = Field(min_length=3, max_length=320)


class EmailChangeConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    token: SecretStr


class ActionStart(BaseModel):
    redirect_url: str = Field(description="Send the browser here; it returns to the callback")


def _send_email_change_verification(
    send: object, email: str, origin: str, operation_id: UUID, token: str
) -> None:
    """Mail is best effort here; the owner can reissue after an interruption."""
    try:
        if callable(send):
            send(to=email, origin=origin, operation_id=operation_id, token=token)
    except Exception:
        # No recipient, link, token or provider exception is written to logs.
        logging.getLogger(__name__).warning("email change verification delivery failed")


def _at(milliseconds: int | None) -> datetime | None:
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC) if milliseconds else None


def _admin(rt: AuthRuntime) -> None:
    if rt.admin is None:
        raise auth_errors.AuthNotConfigured("Security endpoints are not configured.")


def _profile(principal: Principal) -> UserProfile:
    u = principal.user
    return UserProfile(
        id=u.id,
        email=u.email,
        email_verified=u.email_verified_at is not None,
        status=u.status.value,
        display_name=u.display_name,
        preferred_language=u.preferred_language,
        created_at=u.created_at,
        version=u.version,
    )


def build_me_router(limits: AuthLimitSettings, trusted: Sequence[IPNetwork] = ()) -> APIRouter:
    router = APIRouter(tags=["me"])

    @router.get("/me", summary="My profile", response_model=UserProfile)
    def get_me(response: Response, principal: Annotated[Principal, Depends(ANYONE)]) -> UserProfile:
        response.headers["ETag"] = format_etag(principal.user.version)
        response.headers["Cache-Control"] = "no-store"
        return _profile(principal)

    @router.patch("/me", summary="Change my profile", response_model=UserProfile)
    def patch_me(
        request: Request,
        body: ProfilePatch,
        response: Response,
        principal: Annotated[Principal, Depends(ANYONE)],  # first: no answer before authentication
        expected: Annotated[int, Depends(if_match_version)],
    ) -> UserProfile:
        if not body.model_fields_set:
            raise UnprocessableEntity("Send at least one field to change.")
        if "preferred_language" in body.model_fields_set and body.preferred_language is None:
            raise UnprocessableEntity("preferred_language cannot be cleared.")
        with request_scope(request, principal, lock=True) as scope:
            current = user_repository.get_by_id(scope.db, scope.user.id)
            if current is None:  # pragma: no cover - the session's person exists
                raise UnprocessableEntity("Unknown person.")
            check_version(current.version, expected)
            name = (
                body.display_name
                if "display_name" in body.model_fields_set
                else current.display_name
            )
            language = body.preferred_language or current.preferred_language
            ensure_updated(
                int(
                    user_repository.update_profile(
                        scope.db,
                        current.id,
                        display_name=name,
                        preferred_language=language,
                        expected_version=expected,
                    )
                )
            )
            updated = user_repository.get_by_id(scope.db, current.id)
        assert updated is not None  # noqa: S101
        response.headers["ETag"] = format_etag(updated.version)
        response.headers["Cache-Control"] = "no-store"
        return _profile(
            Principal(
                updated, principal.session, None, principal.token, None, principal.requirement
            )
        )

    @router.get(
        "/me/workspaces",
        summary="The tenants and branches I may work in",
        response_model=CursorPage[WorkspaceOption],
    )
    def my_workspaces(
        request: Request, principal: Annotated[Principal, Depends(ANYONE)]
    ) -> CursorPage[WorkspaceOption]:
        rt = runtime_of(request)
        with request_scope(request, principal) as scope:
            try:
                listed = rt.membership.list_workspaces(scope.db, scope.user.id)
            except Exception:
                raise AuthorizationUnavailable() from None
        return CursorPage[WorkspaceOption](
            items=[
                WorkspaceOption(
                    tenant_id=w.tenant_id,
                    branch_ids=list(w.branch_ids),
                    default_branch_id=w.default_branch_id,
                )
                for w in listed
            ]
        )

    # --- security (F2-T09) ---------------------------------------------------------------------
    def _start_action(
        request: Request,
        response: Response,
        principal: Principal,
        action: actions.SecurityAction,
        return_to: str | None,
    ) -> ActionStart:
        rt = runtime_of(request)
        _admin(rt)
        limiter = recovery.limiter_of(request)
        decision = limiter.check(
            Policy("auth_security_action", limits.step_up_per_hour_session, 3600),
            f"user:{principal.user.id}",
        )
        if not decision.allowed:
            raise TooManyRequests(
                "Too many security requests.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        origin, state, nonce, binder, _verifier, challenge = new_flow(
            request,
            rt,
            purpose="SECURITY_ACTION",
            return_to=return_to,
            extra={
                "security_action": action.value,
                "session_id": str(principal.session.id),
                "subject": principal.user.auth_subject,
            },
        )
        url = rt.endpoints.authorization_url(
            redirect_uri=rt.callback_uri(origin),
            state=state,
            nonce=nonce,
            challenge=challenge,
            kc_action=actions.SPECS[action].kc_action,
        )
        cookies.set_flow_cookie(response, rt.settings, binder)
        cookies.no_store(response)
        return ActionStart(redirect_url=url)

    @router.get(
        "/me/security",
        summary="My sign-in security: verification state and second factors",
        response_model=SecurityOverview,
    )
    def my_security(
        request: Request, response: Response, principal: Annotated[Principal, Depends(ANYONE)]
    ) -> SecurityOverview:
        rt = runtime_of(request)
        _admin(rt)
        assert rt.admin is not None  # noqa: S101
        try:
            found = rt.admin.list_credentials(principal.user.auth_subject)
        except IdpAdminError:
            raise auth_errors.IdentityProviderUnavailable() from None
        response.headers["Cache-Control"] = "no-store"
        password = [c.created_ms for c in found if c.type == "password" and c.created_ms]
        return SecurityOverview(
            email_verified=principal.user.email_verified_at is not None,
            password_changed_at=_at(max(password)) if password else None,
            second_factors=[
                SecondFactor(id=c.id, type=c.type, created_at=_at(c.created_ms))
                for c in found
                if c.type in SECOND_FACTOR_TYPES
            ],
        )

    @router.post(
        "/me/email-verification",
        status_code=202,
        summary="Send the verification e-mail again (always the same answer)",
        response_model=Accepted,
    )
    def resend_verification(
        request: Request,
        response: Response,
        background: BackgroundTasks,
        principal: Annotated[Principal, Depends(ANYONE)],
    ) -> Accepted:
        rt = runtime_of(request)
        limiter = recovery.limiter_of(request)
        needed = principal.user.email_verified_at is None
        allowed = recovery.account_allowed(
            rt, limiter, "auth_verification_resend", limits.verification_resend_per_hour,
            str(principal.user.id),
        )  # fmt: skip
        if needed and allowed:
            background.add_task(
                recovery.process_verification_resend,
                rt, principal.user.id, principal.user.auth_subject,
            )  # fmt: skip
        response.headers["Cache-Control"] = "no-store"
        return Accepted()

    @router.post(
        "/me/security/password-change-requests",
        summary="Start a password change (needs a fresh authentication)",
        response_model=ActionStart,
    )
    def password_change_request(
        request: Request,
        response: Response,
        body: PasswordChange,
        principal: Annotated[Principal, Depends(FRESH)],
    ) -> ActionStart:
        return _start_action(
            request, response, principal, actions.SecurityAction.PASSWORD_CHANGE, body.return_to
        )

    @router.post(
        "/me/security/mfa-enrollment-requests",
        summary="Start adding a second factor (needs a fresh authentication)",
        response_model=ActionStart,
    )
    def mfa_enrollment_request(
        request: Request,
        response: Response,
        body: MfaEnrollment,
        principal: Annotated[Principal, Depends(FRESH)],
    ) -> ActionStart:
        action = (
            actions.SecurityAction.MFA_TOTP
            if body.factor == "TOTP"
            else actions.SecurityAction.MFA_RECOVERY_CODES
        )
        return _start_action(request, response, principal, action, body.return_to)

    def _d37_runtime(request: Request) -> AuthRuntime:
        rt = runtime_of(request)
        if not rt.email_change_ready or rt.admin is None:
            raise auth_errors.AuthNotConfigured("Email change is not configured.")
        if not callable(getattr(rt.notifier, "send_email_change_verification", None)):
            raise auth_errors.AuthNotConfigured("Email change is not configured.")
        return rt

    @router.post(
        "/me/security/email-change-requests",
        status_code=202,
        summary="Request verification of a new email",
        response_model=Accepted,
    )
    def request_email_change(
        request: Request,
        response: Response,
        background: BackgroundTasks,
        body: EmailChangeRequest,
        principal: Annotated[Principal, Depends(FRESH)],
    ) -> Accepted:
        rt = _d37_runtime(request)
        try:
            address = normalize_email(body.new_email)
        except ValueError:
            raise UnprocessableEntity("Invalid email address.") from None
        allowed = recovery.account_allowed(
            rt,
            recovery.limiter_of(request),
            "email_change",
            limits.verification_resend_per_hour,
            str(principal.user.id),
        )
        try:
            assert rt.admin is not None  # noqa: S101
            found = rt.admin.find_user_by_email(address) if allowed else None
        except IdpAdminError:
            raise auth_errors.IdentityProviderUnavailable() from None
        origin, _ = rt.site_for(request)
        pending: tuple[UUID, str] | None = None
        if allowed and (found is None or found.subject == principal.user.auth_subject):
            with request_scope(request, principal, lock=True) as scope:
                try:
                    with scope.db.begin_nested():
                        pending = email_change.create_request(
                            scope.db,
                            user_id=scope.user.id,
                            session_id=scope.session.id,
                            new_email=body.new_email,
                        )
                except (IntegrityError, ValueError):
                    pending = None
        if pending is not None:
            operation_id, token = pending
            send = getattr(rt.notifier, "send_email_change_verification", None)
            background.add_task(
                _send_email_change_verification,
                send,
                body.new_email.strip(),
                origin,
                operation_id,
                token,
            )
        response.headers["Cache-Control"] = "no-store"
        return Accepted()

    @router.post(
        "/me/security/email-change-confirmations",
        status_code=202,
        summary="Confirm a new email",
        response_model=Accepted,
    )
    def confirm_email_change(
        request: Request,
        response: Response,
        body: EmailChangeConfirmation,
        principal: Annotated[Principal, Depends(FRESH)],
    ) -> Accepted:
        _d37_runtime(request)
        limiter = recovery.limiter_of(request)
        decision = limiter.check(
            Policy("email_change_confirm", limits.step_up_per_hour_session, 3600),
            f"user:{principal.user.id}",
        )
        if not decision.allowed:
            raise TooManyRequests(
                "Too many security requests.",
                headers={"Retry-After": str(decision.retry_after_seconds)},
            )
        with request_scope(request, principal, lock=True) as scope:
            email_change.confirm_request(
                scope.db,
                user_id=scope.user.id,
                operation_id=body.operation_id,
                token=body.token.get_secret_value(),
            )
        response.headers["Cache-Control"] = "no-store"
        return Accepted()

    @router.delete(
        "/me/security/second-factors/{credential_id}",
        status_code=204,
        summary="Remove one of my second factors (needs the second factor)",
    )
    def remove_second_factor(
        request: Request,
        credential_id: Annotated[str, Path(max_length=64, pattern=r"^[A-Za-z0-9-]{1,64}$")],
        principal: Annotated[Principal, Depends(SECOND_FACTOR)],
    ) -> Response:
        rt = runtime_of(request)
        _admin(rt)
        with request_scope(request, principal, lock=True) as scope:
            try:
                factor = actions.remove_second_factor(
                    rt, scope.db, user_id=scope.user.id, session_id=principal.session.id,
                    subject=scope.user.auth_subject, credential_id=credential_id,
                )  # fmt: skip
            except IdpAdminError:
                raise auth_errors.IdentityProviderUnavailable() from None
            email = scope.user.email
        if factor is None:
            raise NotFound("No such second factor.")
        send_quietly(rt.notifier, Notice(NoticeKind.MFA_REMOVED, email, datetime.now(UTC)))
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    return router
