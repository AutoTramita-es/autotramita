"""Route guards and the request scope (F2-T08): deny by default.

Every route declares what it needs, and a test refuses a route that does not:

* ``declared(kind)``      only declares (PUBLIC, TOKEN, SESSION); for SESSION/TOKEN it also refuses
                          a request without any credential before anything else happens;
* ``require_user``        a validated session whose person may use the account (ACTIVE, or also
                          PENDING with ``allow_unverified``);
* ``require_workspace``   additionally an active tenant context, checked against the person's
                          *current* membership through the AT-03 port;
* ``require_step_up``     additionally a sufficiently fresh and strong authentication;
* ``require_account_step_up``  the same, with the level the account itself demands: a second
                          factor whenever the person has one (F-3).

A guard validates the session and sets ``request.state.principal_id`` / ``tenant_id`` (used by
the rate limiter) from the validated result only. Handlers that touch the database open
``request_scope``, which validates again inside *their* transaction (with a share lock on the
session for mutating requests, D16) and applies the full request context."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.api.v1.authn import authenticated, bearer_token, record_attempt, request_facts
from app.audit.models import ActorType, AuditEvent, Outcome
from app.auth import context as workspace_context
from app.auth.errors import AuthRequired, EmailNotVerified, WorkspaceRequired
from app.auth.membership import Workspace
from app.auth.runtime import AuthRuntime, runtime_of
from app.auth.security import step_up
from app.auth.sessions.models import AuthLevel, UserSession
from app.auth.tokens import VerifiedToken
from app.auth.users.models import User, UserStatus
from app.core.db import RequestContext, apply_context
from fastapi import Request
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session


class AccessKind(StrEnum):
    PUBLIC = "PUBLIC"  # no credential (sign-in redirects, provider callbacks)
    TOKEN = "TOKEN"  # noqa: S105 - an access kind, not a password
    SESSION = "SESSION"  # a validated application session (checked in the handler)
    USER = "USER"  # a validated session of a usable account (guard)
    WORKSPACE = "WORKSPACE"  # ... with an active, currently authorised workspace (guard)


@dataclass(frozen=True, slots=True)
class StepUp:
    level: AuthLevel
    max_age_seconds: int


@dataclass(frozen=True, slots=True)
class Requirement:
    kind: AccessKind
    allow_unverified: bool = False
    step_up: StepUp | None = None
    account_step_up_seconds: int | None = None  # the level follows from the account (F-3)


@dataclass(frozen=True, slots=True)
class Principal:
    user: User
    session: UserSession
    workspace: Workspace | None
    token: VerifiedToken | None
    credential: str | None
    requirement: Requirement
    second_factor: bool = False  # set by ``require_account_step_up`` only


@dataclass(frozen=True, slots=True)
class Scope:
    """Inside ``request_scope``: the open transaction with the full context applied."""

    db: Session
    user: User
    session: UserSession
    workspace: Workspace | None
    token: VerifiedToken | None


def declared(kind: AccessKind) -> Callable[[Request], None]:
    """Declaration for routes whose handler authenticates itself. SESSION and TOKEN routes
    refuse a request without any credential right here, before the body is even validated."""

    def dependency(request: Request) -> None:
        if kind in (AccessKind.SESSION, AccessKind.TOKEN):
            runtime_of(request)  # an unconfigured service answers 503 before anything else
            has_cookie = any(
                request.cookies.get(name) for name in ("__Host-at_session", "at_session")
            )
            if not has_cookie and bearer_token(request) is None:
                raise AuthRequired()

    dependency.access_kind = kind  # type: ignore[attr-defined]
    return dependency


def _enforce(
    rt: AuthRuntime, db: Session, ctx_principal: Principal, requirement: Requirement
) -> None:
    user = ctx_principal.user
    if user.status is UserStatus.PENDING_VERIFICATION and not requirement.allow_unverified:
        raise EmailNotVerified()
    if requirement.kind is AccessKind.WORKSPACE and ctx_principal.workspace is None:
        raise WorkspaceRequired()
    if requirement.step_up is not None:
        step_up.enforce(
            rt,
            session=ctx_principal.session,
            token=ctx_principal.token,
            level=requirement.step_up.level,
            max_age_seconds=requirement.step_up.max_age_seconds,
            now=datetime.now(UTC),
        )


def record_denied_workspace(
    request: Request, rt: AuthRuntime, user_id: UUID, session_id: UUID
) -> None:
    """A workspace the person may not use (any more) was asked for. The record names the person
    and the session, never the tenant the client sent."""
    prefix, family = request_facts(request, rt)
    record_attempt(
        rt,
        AuditEvent(
            action="authz.denied",
            outcome=Outcome.DENIED,
            actor_type=ActorType.USER,
            actor_user_id=user_id,
            subject_user_id=user_id,
            actor_session_id=session_id,
            ip_prefix=prefix,
            ua_family=family,
            details={"reason": "WORKSPACE", "resource_type": "workspace"},
        ),
        RequestContext(user_id=user_id),
    )


def _guard(requirement: Requirement) -> Callable[[Request], Principal]:
    def dependency(request: Request) -> Principal:
        rt = runtime_of(request)
        with authenticated(request, rt, lock=False) as ctx:
            workspace = None
            if requirement.kind is AccessKind.WORKSPACE:
                workspace = workspace_context.resolve_active(
                    rt.membership, ctx.db, ctx.resolved.user, ctx.resolved.session
                )
            principal = Principal(
                ctx.resolved.user,
                ctx.resolved.session,
                workspace,
                ctx.token,
                ctx.credential,
                requirement,
            )
            lost = (
                requirement.kind is AccessKind.WORKSPACE
                and workspace is None
                and ctx.resolved.session.active_tenant_id is not None
            )
            if lost:
                record_denied_workspace(request, rt, principal.user.id, principal.session.id)
            _enforce(rt, ctx.db, principal, requirement)
        if requirement.account_step_up_seconds is not None:
            # After the transaction: no database lock is held while the provider is asked.
            enrolled = step_up.enforce_for_account(
                rt,
                subject=principal.user.auth_subject,
                session=principal.session,
                token=principal.token,
                max_age_seconds=requirement.account_step_up_seconds,
                now=datetime.now(UTC),
            )
            principal = replace(principal, second_factor=enrolled)
        # Only values the validated session produced reach the rate limiter (no client input).
        request.state.principal_id = principal.user.id
        request.state.tenant_id = workspace.tenant_id if workspace else None
        return principal

    dependency.requirement = requirement  # type: ignore[attr-defined]
    dependency.access_kind = requirement.kind  # type: ignore[attr-defined]
    return dependency


def require_user(
    *, allow_unverified: bool = False, step_up: StepUp | None = None
) -> Callable[[Request], Principal]:
    return _guard(Requirement(AccessKind.USER, allow_unverified, step_up))


def require_workspace(*, step_up: StepUp | None = None) -> Callable[[Request], Principal]:
    return _guard(Requirement(AccessKind.WORKSPACE, False, step_up))


def require_step_up(
    level: AuthLevel, max_age_seconds: int, *, workspace: bool = False
) -> Callable[[Request], Principal]:
    kind = AccessKind.WORKSPACE if workspace else AccessKind.USER
    return _guard(Requirement(kind, False, StepUp(level, max_age_seconds)))


def require_account_step_up(max_age_seconds: int) -> Callable[[Request], Principal]:
    return _guard(Requirement(AccessKind.USER, account_step_up_seconds=max_age_seconds))


@contextmanager
def request_scope(request: Request, principal: Principal, *, lock: bool = False) -> Iterator[Scope]:
    """The transaction of a handler. The session, the account and the workspace are validated
    again *inside it*; for mutating requests (``lock=True``) the session row is share-locked,
    so a revocation waits for this request and every later request sees it. Business queries
    then run under the full context (user, tenant, selected branch) and nothing else."""
    rt = runtime_of(request)
    requirement = principal.requirement
    with authenticated(request, rt, lock=lock, touch=False) as ctx:
        user, session = ctx.resolved.user, ctx.resolved.session
        workspace = None
        if requirement.kind is AccessKind.WORKSPACE:
            workspace = workspace_context.resolve_active(rt.membership, ctx.db, user, session)
            if workspace is None:
                raise WorkspaceRequired()
        apply_context(ctx.db, workspace_context.request_context(user, workspace))
        yield Scope(ctx.db, user, session, workspace, ctx.token)


def _declared_kind(dependant: Any) -> AccessKind | None:
    for sub in dependant.dependencies:
        kind = getattr(sub.call, "access_kind", None)
        if isinstance(kind, AccessKind):
            return kind
        deeper = _declared_kind(sub)
        if deeper is not None:
            return deeper
    return None


def iter_access(app: Any) -> Iterator[tuple[str, str, AccessKind | None]]:
    """Every operation of the application with the access it declares (``None``: nothing).
    Walks FastAPI's included routers, so a route added anywhere shows up here."""
    for top in app.routes:
        contexts = (
            top.effective_route_contexts() if hasattr(top, "effective_route_contexts") else [top]
        )
        for context in contexts:
            route = getattr(context, "original_route", context)
            if not isinstance(route, APIRoute):
                continue
            kind: AccessKind | None = None
            for dep in getattr(context, "dependencies", None) or route.dependencies:
                found = getattr(dep.dependency, "access_kind", None)
                if isinstance(found, AccessKind):
                    kind = found
                    break
            kind = kind or _declared_kind(route.dependant)
            path = getattr(context, "path", None) or route.path
            for method in getattr(context, "methods", None) or route.methods or ():
                yield method, path, kind
