"""Routes that exist only in tests (F2-T08): they use the production guards and the request
scope against the F1 RLS probe tables, so the whole pipeline is exercised end to end."""

from __future__ import annotations

from typing import Annotated, Any

from app.api.v1.guards import (
    Principal,
    request_scope,
    require_step_up,
    require_user,
    require_workspace,
)
from app.auth.sessions.models import AuthLevel
from app.core.ratelimit import Policy, by_principal, by_tenant, rate_limit
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

WORKSPACE = require_workspace()
USER = require_user()
MFA = require_step_up(AuthLevel.LOA2, 600)
TENANT_LIMIT = rate_limit(Policy("probe_tenant", 3), by_tenant)
USER_LIMIT = rate_limit(Policy("probe_user", 4), by_principal)

router = APIRouter(prefix="/probe")


class NewCustomer(BaseModel):
    name: str
    tenant_id: str | None = None  # a client-supplied tenant: must be ignored


@router.get("/customers")
def customers(
    request: Request, principal: Annotated[Principal, Depends(WORKSPACE)]
) -> dict[str, Any]:
    with request_scope(request, principal) as scope:
        names = [
            r[0] for r in scope.db.execute(text("SELECT name FROM rls_customers ORDER BY name"))
        ]
        joined = scope.db.execute(
            text("SELECT count(*) FROM rls_cases c JOIN rls_customers u "
                 "ON u.id = c.customer_id AND u.tenant_id = c.tenant_id")
        ).scalar_one()  # fmt: skip
        seen = scope.db.execute(text("SELECT current_setting('app.tenant_id', true), "
                                     "current_setting('app.branch_ids', true), "
                                     "current_setting('app.session_hash', true), "
                                     "current_setting('app.auth_subject', true)")).one()  # fmt: skip
    return {
        "names": names, "joined": joined, "tenant": str(scope.workspace.tenant_id) if scope.workspace else None,
        "branch": str(scope.workspace.branch_id) if scope.workspace and scope.workspace.branch_id else None,
        "settings": [seen[0], seen[1], seen[2], seen[3]],
    }  # fmt: skip


@router.post("/customers")
def add_customer(
    request: Request, body: NewCustomer, principal: Annotated[Principal, Depends(WORKSPACE)]
) -> dict[str, Any]:
    with request_scope(request, principal, lock=True) as scope:
        assert scope.workspace is not None
        scope.db.execute(
            text("INSERT INTO rls_customers (tenant_id, name) VALUES (:t, :n)"),
            {
                "t": scope.workspace.tenant_id,
                "n": body.name,
            },  # the tenant comes from the context only
        )
        return {"tenant": str(scope.workspace.tenant_id)}


@router.post("/forge")
def forge(
    request: Request, body: NewCustomer, principal: Annotated[Principal, Depends(WORKSPACE)]
) -> dict[str, bool]:
    """Try to write a row for the tenant the client names: the database must refuse it."""
    blocked = False
    try:
        with request_scope(request, principal, lock=True) as scope:
            scope.db.execute(
                text(
                    "INSERT INTO rls_customers (tenant_id, name) VALUES (CAST(:t AS uuid), 'forged')"
                ),
                {"t": body.tenant_id},
            )
    except DBAPIError:
        blocked = True
    return {"blocked": blocked}


@router.get("/user-only")
def user_only(principal: Annotated[Principal, Depends(USER)]) -> dict[str, str]:
    return {"user": str(principal.user.id), "status": principal.user.status.value}


@router.get("/mfa")
def needs_mfa(principal: Annotated[Principal, Depends(MFA)]) -> dict[str, str]:
    return {"level": principal.session.auth_level.value}


@router.get("/limited-by-tenant", dependencies=[Depends(WORKSPACE), Depends(TENANT_LIMIT)])
def limited_tenant(principal: Annotated[Principal, Depends(WORKSPACE)]) -> dict[str, str]:
    return {"tenant": str(principal.workspace.tenant_id) if principal.workspace else ""}


@router.get("/limited-by-user", dependencies=[Depends(USER), Depends(USER_LIMIT)])
def limited_user(principal: Annotated[Principal, Depends(USER)]) -> dict[str, str]:
    return {"user": str(principal.user.id)}
