"""Test doubles for the AT-03 membership port (F2-T08). Nothing here ships: production wiring
uses ``DenyAllAuthorizer``. ``ProbeAuthorizer`` reads the F1 RLS probe tables, so the two-step
context of G5-02 (own memberships visible with only ``app.user_id`` set) is exercised for real."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from uuid import UUID

from app.auth.membership import Workspace, WorkspaceSummary
from sqlalchemy import text
from sqlalchemy.orm import Session


def branches_of(tenant_id: UUID) -> tuple[UUID, UUID]:
    """Two deterministic branches per probe tenant: the first is the default."""
    return (uuid.uuid5(tenant_id, "branch-1"), uuid.uuid5(tenant_id, "branch-2"))


class ProbeAuthorizer:
    """OWNER may use both branches, VIEWER only the first, anything else (e.g. SUSPENDED)
    nothing. Memberships come from ``rls_memberships`` under the person's own context."""

    def _role(self, db: Session, user_id: UUID, tenant_id: UUID) -> str | None:
        row = db.execute(
            text("SELECT role FROM rls_memberships WHERE tenant_id = :t AND user_id = :u"),
            {"t": tenant_id, "u": user_id},
        ).one_or_none()
        return str(row[0]) if row else None

    @staticmethod
    def _allowed(role: str | None, tenant_id: UUID) -> tuple[UUID, ...]:
        first, second = branches_of(tenant_id)
        return {"OWNER": (first, second), "VIEWER": (first,)}.get(role or "", ())

    def list_workspaces(self, session: Session, user_id: UUID) -> Sequence[WorkspaceSummary]:
        rows = session.execute(
            text("SELECT tenant_id, role FROM rls_memberships ORDER BY role")
        ).all()
        found: list[WorkspaceSummary] = []
        for tenant_id, role in rows:
            allowed = self._allowed(str(role), tenant_id)
            if allowed:
                found.append(WorkspaceSummary(tenant_id, allowed, allowed[0]))
        return found

    def resolve(
        self, session: Session, user_id: UUID, tenant_id: UUID, branch_id: UUID | None
    ) -> Workspace | None:
        allowed = self._allowed(self._role(session, user_id, tenant_id), tenant_id)
        if not allowed:
            return None
        branch = branch_id if branch_id is not None else allowed[0]
        if branch not in allowed:
            return None
        return Workspace(tenant_id, branch, uuid.uuid5(tenant_id, str(user_id)), allowed)


class BrokenAuthorizer:
    """The membership store is down."""

    def list_workspaces(self, session: Session, user_id: UUID) -> Sequence[WorkspaceSummary]:
        raise RuntimeError("membership store unavailable")

    def resolve(
        self, session: Session, user_id: UUID, tenant_id: UUID, branch_id: UUID | None
    ) -> Workspace | None:
        raise RuntimeError("membership store unavailable")


class InconsistentAuthorizer:
    """A buggy implementation that answers for another tenant: it must never be trusted."""

    def list_workspaces(self, session: Session, user_id: UUID) -> Sequence[WorkspaceSummary]:
        return ()

    def resolve(
        self, session: Session, user_id: UUID, tenant_id: UUID, branch_id: UUID | None
    ) -> Workspace | None:
        other = uuid.uuid4()
        return Workspace(other, None, uuid.uuid4(), ())
