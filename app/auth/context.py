"""Request context and workspace selection (F2-T08, decisions D16, D18).

The context of a request is built by the server from the validated session and the membership
check, never from anything the client sent. A tenant or branch identifier in a request is only
ever a *request to switch* that is itself checked against the person's membership."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.audit.models import ActorType, AuditEvent, Outcome
from app.audit.record import record
from app.auth.errors import (
    AuthorizationUnavailable,
    SessionRevoked,
    WorkspaceNotFound,
)
from app.auth.membership import MembershipAuthorizer, Workspace
from app.auth.sessions import repository as session_repository
from app.auth.sessions.models import UserSession
from app.auth.users.models import User
from app.core.db import RequestContext
from app.core.errors import PreconditionFailed
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def safe_resolve(
    authorizer: MembershipAuthorizer,
    db: Session,
    user_id: UUID,
    tenant_id: UUID,
    branch_id: UUID | None,
) -> Workspace | None:
    """Ask the membership port. Any failure means "cannot tell" and the request is refused
    (503), because guessing either way would be wrong. A malformed answer counts as no access."""
    try:
        workspace = authorizer.resolve(db, user_id, tenant_id, branch_id)
    except Exception:
        logger.error("membership check failed", extra={"fields": {"type": "authorizer_error"}})
        raise AuthorizationUnavailable() from None
    if workspace is None:
        return None
    if workspace.tenant_id != tenant_id or (
        workspace.branch_id is not None and workspace.branch_id not in workspace.branch_ids
    ):
        logger.error("membership port returned an inconsistent workspace")
        return None
    return workspace


def resolve_active(
    authorizer: MembershipAuthorizer, db: Session, user: User, session: UserSession
) -> Workspace | None:
    """The workspace of this session *now*, or ``None``. Ending of a membership (or of a branch
    assignment) therefore takes effect on the very next request."""
    if session.active_tenant_id is None:
        return None
    return safe_resolve(authorizer, db, user.id, session.active_tenant_id, session.active_branch_id)


def request_context(user: User, workspace: Workspace | None) -> RequestContext:
    """The transaction context for business queries. Only the *selected* branch is visible to
    row policies: a session works in one branch at a time (AT-03)."""
    if workspace is None:
        return RequestContext(user_id=user.id)
    branches = (workspace.branch_id,) if workspace.branch_id is not None else ()
    return RequestContext(user_id=user.id, tenant_id=workspace.tenant_id, branch_ids=branches)


def change_workspace(
    db: Session,
    authorizer: MembershipAuthorizer,
    session: UserSession,
    user: User,
    *,
    tenant_id: UUID,
    branch_id: UUID | None,
    expected_version: int,
) -> UserSession:
    """Switch the active tenant/branch of *this* session. The request names a workspace; the
    membership port decides. Optimistic on ``context_version``: of two parallel switches
    started from the same version exactly one wins."""
    if session.context_version != expected_version:
        raise PreconditionFailed(
            "The session context changed; reload it and retry.", code="VERSION_MISMATCH"
        )
    workspace = safe_resolve(authorizer, db, user.id, tenant_id, branch_id)
    if workspace is None:
        raise WorkspaceNotFound()
    changed = session_repository.set_workspace(
        db,
        session.id,
        tenant_id=workspace.tenant_id,
        branch_id=workspace.branch_id,
        membership_id=workspace.membership_id,
        expected_version=expected_version,
    )
    if not changed:
        current = session_repository.by_id(db, session.id)
        if current is None or current.is_revoked:
            raise SessionRevoked()
        raise PreconditionFailed(
            "The session context changed; reload it and retry.", code="VERSION_MISMATCH"
        )
    details: dict[str, Any] = {
        "from_context_version": session.context_version,
        "to_context_version": session.context_version + 1,
        "to_tenant_id": workspace.tenant_id,
    }
    if session.active_tenant_id:
        details["from_tenant_id"] = session.active_tenant_id
    if session.active_branch_id:
        details["from_branch_id"] = session.active_branch_id
    if workspace.branch_id:
        details["to_branch_id"] = workspace.branch_id
    record(
        db,
        AuditEvent(
            action="session.context.changed",
            outcome=Outcome.SUCCESS,
            actor_type=ActorType.USER,
            actor_user_id=user.id,
            subject_user_id=user.id,
            actor_session_id=session.id,
            details=details,
        ),
    )
    refreshed = session_repository.by_id(db, session.id)
    if refreshed is None:  # pragma: no cover
        raise SessionRevoked()
    return refreshed
