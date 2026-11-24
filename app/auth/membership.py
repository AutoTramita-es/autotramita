"""Boundary towards the tenant membership of AT-03 (F2-T08, D18).

F2 does not implement tenants, memberships or branches. It defines what the request pipeline
asks of them and ships an authorizer that answers "no" to everything, so no access can exist
until F3a provides the real one. The port is called inside the request's transaction with the
person already known (``app.user_id`` set, step one of the two-step context of G5-02); it
returns the workspace the person may use *now*, read from the database on every request.

Rules for implementations: ``None`` means no access; never raise to signal "no" (a raised error
is treated as an outage and the request is refused with 503); never trust a tenant or branch id
for anything but looking up that person's own membership.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class Workspace:
    """What a person may do in one tenant right now."""

    tenant_id: UUID
    branch_id: UUID | None  # the selected branch; None when the tenant has none to select
    membership_id: UUID
    branch_ids: tuple[UUID, ...]  # every branch of this tenant the person may select


@dataclass(frozen=True, slots=True)
class WorkspaceSummary:
    tenant_id: UUID
    branch_ids: tuple[UUID, ...]
    default_branch_id: UUID | None = None


class MembershipAuthorizer(Protocol):
    def list_workspaces(self, session: Session, user_id: UUID) -> Sequence[WorkspaceSummary]: ...

    def resolve(
        self, session: Session, user_id: UUID, tenant_id: UUID, branch_id: UUID | None
    ) -> Workspace | None: ...


class DenyAllAuthorizer:
    """The F2 implementation: there are no memberships, so nobody has a workspace."""

    def list_workspaces(self, session: Session, user_id: UUID) -> Sequence[WorkspaceSummary]:
        return ()

    def resolve(
        self, session: Session, user_id: UUID, tenant_id: UUID, branch_id: UUID | None
    ) -> Workspace | None:
        return None
