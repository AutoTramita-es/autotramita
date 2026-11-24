"""The signed-in person: profile and workspaces (F2-T08).

``GET /me`` and ``PATCH /me`` work for a person who has not verified the e-mail address yet
(they must be able to fix their profile and resend the verification). Identity, e-mail and status
are never writable here: they belong to the identity provider and to platform administrators."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated
from uuid import UUID

from app.api.v1.authn import UserSummary
from app.api.v1.guards import Principal, request_scope, require_user
from app.auth.errors import AuthorizationUnavailable
from app.auth.runtime import runtime_of
from app.auth.users import repository as user_repository
from app.core.errors import UnprocessableEntity
from app.core.pagination import CursorPage
from app.core.ratelimit import IPNetwork
from app.core.versioning import check_version, ensure_updated, format_etag, if_match_version
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# A person whose e-mail is not verified yet may still read and fix their profile.
ANYONE = require_user(allow_unverified=True)
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


def build_me_router(trusted: Sequence[IPNetwork] = ()) -> APIRouter:
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

    return router
