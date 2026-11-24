"""Audit event model (F2-T03, D31). Plain data; persistence is in ``record``."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID


class Scope(StrEnum):
    TENANT = "TENANT"
    PLATFORM = "PLATFORM"


class Category(StrEnum):
    AUTHN = "AUTHN"
    SESSION = "SESSION"
    SECURITY_SETTING = "SECURITY_SETTING"
    AUTHZ = "AUTHZ"
    ADMIN = "ADMIN"
    ACCESS_DENIED = "ACCESS_DENIED"
    IDENTITY = "IDENTITY"


class Outcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    DENIED = "DENIED"


class ActorType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    IDP = "IDP"
    ANONYMOUS = "ANONYMOUS"


class Source(StrEnum):
    APP = "APP"
    KEYCLOAK = "KEYCLOAK"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One audit record. ``action`` must exist in the catalog; ``details`` is validated against
    that action's allowlist before anything is written."""

    action: str
    outcome: Outcome
    actor_type: ActorType
    scope: Scope = Scope.PLATFORM
    actor_user_id: UUID | None = None
    actor_session_id: UUID | None = None
    subject_user_id: UUID | None = None
    tenant_id: UUID | None = None
    branch_id: UUID | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    request_id: UUID | None = None
    ip_prefix: str | None = None  # already truncated, see app.audit.record.ip_prefix
    ua_family: str | None = None
    reason_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    source: Source = Source.APP
    source_event_id: str | None = None
