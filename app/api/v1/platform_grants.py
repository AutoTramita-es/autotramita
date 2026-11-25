"""Platform grant routes (F2-T10; AT-02 10.2): catalog, list, request, approve, reject, revoke.

Every route needs ``PLATFORM_GRANT_ADMIN`` read from the database in the handler's own
transaction and a second factor proven recently (ten minutes for the catalog, five for the list
and every change, D23). Repeating a request, approval or revocation answers 409: the state of the
grant itself protects against replay (one live grant per person and type, decided requests
cannot be decided again), so no Idempotency-Key is needed."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from app.api.v1.authn import request_facts
from app.api.v1.guards import Principal, platform_scope, require_platform
from app.auth.errors import AuthNotConfigured
from app.auth.runtime import AuthRuntime, runtime_of
from app.auth.security.notify import Notice, NoticeKind, send_quietly
from app.auth.settings import AuthLimitSettings
from app.core.errors import Problem
from app.core.pagination import CursorPage, PageParams, page_params
from app.core.ratelimit import IPNetwork
from app.platform import repository, service
from app.platform.models import (
    CALLER_REVOKE_REASONS,
    FOUR_EYES,
    GRANT_CHANGE_STEP_UP_SECONDS,
    MAX_LIFETIME,
    PLATFORM_STEP_UP_SECONDS,
    SCOPED_TYPES,
    GrantStatus,
    GrantType,
    RevokeReason,
    ScopeKind,
)
from app.platform.models import PlatformGrant as Grant
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Reason = Annotated[str, StringConstraints(pattern=r"^[^\x00-\x1f\x7f]{3,200}$")]
Queue = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,39}$")]
CHANGE = GRANT_CHANGE_STEP_UP_SECONDS
PLATFORM = require_platform()
Admin = Annotated[Principal, Depends(PLATFORM)]
LIST_SORT = ("-created_at", "-id")


class GrantTypeInfo(BaseModel):
    grant_type: GrantType
    four_eyes: bool = Field(description="Always needs a second grant administrator")
    max_lifetime_days: int
    scope_kinds: list[ScopeKind]


class PlatformGrant(BaseModel):
    id: UUID
    user_id: UUID
    grant_type: GrantType
    scope_kind: ScopeKind
    scope_tenant_ids: list[UUID] | None
    queue: str | None
    status: GrantStatus
    active: bool = Field(description="Active and not expired now")
    expires_at: datetime
    granted_by: UUID | None
    approved_by: UUID | None
    created_at: datetime
    activated_at: datetime | None
    revoked_at: datetime | None
    revoke_reason: str | None


class GrantRequest(BaseModel):
    """A request. Whether it takes effect at once or waits for a second administrator, and
    whether the person may hold it at all, is decided by the server."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    grant_type: GrantType
    expires_at: datetime = Field(description="At most 365 days ahead (verification reviewer 90)")
    reason: Reason
    scope_kind: ScopeKind = ScopeKind.ALL
    scope_tenant_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=100)
    queue: Queue | None = None


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: RevokeReason = Field(
        description="One of " + ", ".join(sorted(r.value for r in CALLER_REVOKE_REASONS))
    )


def _out(grant: Grant, now: datetime) -> PlatformGrant:
    return PlatformGrant(
        id=grant.id,
        user_id=grant.user_id,
        grant_type=grant.grant_type,
        scope_kind=grant.scope_kind,
        scope_tenant_ids=list(grant.scope_tenant_ids) if grant.scope_tenant_ids else None,
        queue=grant.queue,
        status=grant.status,
        active=grant.active_at(now),
        expires_at=grant.expires_at,
        granted_by=grant.granted_by,
        approved_by=grant.approved_by,
        created_at=grant.created_at,
        activated_at=grant.activated_at,
        revoked_at=grant.revoked_at,
        revoke_reason=grant.revoke_reason,
    )


def _notify(rt: AuthRuntime, address: str | None) -> None:
    """The person whose privileges changed is told (D27), after the commit, best effort."""
    if address:
        send_quietly(
            rt.notifier, Notice(NoticeKind.PLATFORM_GRANT_CHANGED, address, datetime.now(UTC))
        )


def build_platform_grants_router(
    limits: AuthLimitSettings, trusted: Sequence[IPNetwork] = ()
) -> APIRouter:
    router = APIRouter(tags=["platform"])
    administrator = GrantType.PLATFORM_GRANT_ADMIN
    refused: dict[int | str, dict[str, Any]] = {
        401: {"model": Problem, "description": "Level two needed (RFC 9470)"},
        403: {"model": Problem, "description": "No platform grant for this"},
    }

    @router.get(
        "/platform/grant-types",
        summary="Catalog of platform grant types",
        response_model=list[GrantTypeInfo],
        responses=refused,
    )
    def grant_types(request: Request, principal: Admin) -> list[GrantTypeInfo]:
        with platform_scope(
            request, principal, administrator, max_age_seconds=PLATFORM_STEP_UP_SECONDS, lock=False
        ):
            pass
        return [
            GrantTypeInfo(
                grant_type=kind,
                four_eyes=kind in FOUR_EYES,
                max_lifetime_days=MAX_LIFETIME[kind].days,
                scope_kinds=list(ScopeKind) if kind in SCOPED_TYPES else [ScopeKind.ALL],
            )
            for kind in GrantType
        ]

    @router.get(
        "/platform/grants",
        summary="Platform grants, newest first",
        response_model=CursorPage[PlatformGrant],
        responses=refused,
    )
    def list_grants(
        request: Request,
        principal: Admin,
        paging: Annotated[PageParams, Depends(page_params)],
        user_id: Annotated[UUID | None, Query()] = None,
        grant_type: Annotated[GrantType | None, Query()] = None,
        status: Annotated[GrantStatus | None, Query()] = None,
    ) -> CursorPage[PlatformGrant]:
        rt = runtime_of(request)
        filters: dict[str, Any] = {
            "user_id": str(user_id) if user_id else None,
            "grant_type": grant_type.value if grant_type else None,
            "status": status.value if status else None,
        }
        codec = rt.cursor_codec
        with platform_scope(
            request, principal, administrator, max_age_seconds=CHANGE, lock=False
        ) as auth:
            after = None
            if paging.cursor is not None:  # read only after the caller was authorised
                if codec is None:
                    raise AuthNotConfigured("Paging is not configured.")
                position = codec.decode(
                    paging.cursor,
                    tenant_id=None,
                    filters=filters,
                    sort=LIST_SORT,
                    tie_breaker="id",
                )
                after = (
                    datetime.fromisoformat(str(position["created_at"])),
                    UUID(str(position["id"])),
                )
            rows = repository.page(
                auth.db,
                limit=paging.limit,
                after=after,
                user_id=user_id,
                grant_type=grant_type,
                status=status,
            )
        now = datetime.now(UTC)
        if len(rows) <= paging.limit:
            return CursorPage[PlatformGrant](items=[_out(g, now) for g in rows])
        if codec is None:
            raise AuthNotConfigured("Paging is not configured.")
        last = rows[paging.limit - 1]
        cursor = codec.encode(
            tenant_id=None,
            filters=filters,
            sort=LIST_SORT,
            tie_breaker="id",
            position={"created_at": last.created_at.isoformat(), "id": str(last.id)},
        )
        return CursorPage[PlatformGrant](
            items=[_out(g, now) for g in rows[: paging.limit]], next_cursor=cursor
        )

    @router.post(
        "/platform/grants",
        status_code=201,
        summary="Request a platform grant (four eyes where required)",
        description="Takes effect at once only for a type that needs no second administrator and "
        "that the requester holds; otherwise it waits for another grant administrator. The person "
        "must be active and have a one-time code or passkey; the identity provider then keeps "
        "their second factor mandatory.",
        response_model=PlatformGrant,
        responses=refused,
    )
    def request_grant(request: Request, body: GrantRequest, principal: Admin) -> PlatformGrant:
        rt = runtime_of(request)
        prefix, family = request_facts(request, rt)
        with platform_scope(
            request, principal, administrator, max_age_seconds=CHANGE, lock=True
        ) as auth:
            grant = service.request_grant(
                auth,
                rt.admin,
                user_id=body.user_id,
                grant_type=body.grant_type,
                expires_at=body.expires_at,
                reason=body.reason,
                scope_kind=body.scope_kind,
                scope_tenant_ids=body.scope_tenant_ids,
                queue=body.queue,
                now=datetime.now(UTC),
                ip_prefix=prefix,
                ua_family=family,
            )
            address = (
                service.notice_address(auth, grant.user_id)
                if grant.status is GrantStatus.ACTIVE
                else None
            )
        _notify(rt, address)
        return _out(grant, datetime.now(UTC))

    @router.post(
        "/platform/grants/{grant_id}/approve",
        summary="Approve a pending platform grant (second administrator)",
        response_model=PlatformGrant,
        responses=refused,
    )
    def approve(request: Request, grant_id: UUID, principal: Admin) -> PlatformGrant:
        rt = runtime_of(request)
        prefix, family = request_facts(request, rt)
        with platform_scope(
            request, principal, administrator, max_age_seconds=CHANGE, lock=True
        ) as auth:
            grant = service.approve(
                auth, rt.admin, grant_id, now=datetime.now(UTC), ip_prefix=prefix, ua_family=family
            )
            address = service.notice_address(auth, grant.user_id)
        _notify(rt, address)
        return _out(grant, datetime.now(UTC))

    @router.post(
        "/platform/grants/{grant_id}/reject",
        summary="Reject a pending platform grant (second administrator)",
        response_model=PlatformGrant,
        responses=refused,
    )
    def reject(request: Request, grant_id: UUID, principal: Admin) -> PlatformGrant:
        rt = runtime_of(request)
        prefix, family = request_facts(request, rt)
        with platform_scope(
            request, principal, administrator, max_age_seconds=CHANGE, lock=True
        ) as auth:
            grant = service.reject(
                auth, grant_id, now=datetime.now(UTC), ip_prefix=prefix, ua_family=family
            )
        return _out(grant, datetime.now(UTC))

    @router.post(
        "/platform/grants/{grant_id}/revoke",
        summary="End a pending or active platform grant at once",
        response_model=PlatformGrant,
        responses=refused,
    )
    def revoke(
        request: Request, grant_id: UUID, body: RevokeRequest, principal: Admin
    ) -> PlatformGrant:
        rt = runtime_of(request)
        prefix, family = request_facts(request, rt)
        with platform_scope(
            request, principal, administrator, max_age_seconds=CHANGE, lock=True
        ) as auth:
            grant = service.revoke(
                auth,
                grant_id,
                body.reason,
                now=datetime.now(UTC),
                ip_prefix=prefix,
                ua_family=family,
            )
            held = grant.activated_at is not None  # the person really lost a privilege
            address = service.notice_address(auth, grant.user_id) if held else None
        _notify(rt, address)
        return _out(grant, datetime.now(UTC))

    return router
