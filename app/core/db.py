"""Synchronous database layer (SQLAlchemy 2.x, psycopg 3).

Tenant isolation follows ADR-002: the request context is written with transaction-local
``set_config(..., true)`` on the same connection and transaction as the queries, so nothing
can leak to the next user of a pooled connection. Row-level security policies read these
settings; this module never trusts caller-supplied tenant data beyond typed UUIDs.

Always use ``session_scope``: it applies the context as the first statement and commits at
exit. A commit inside the block ends the transaction and drops the context, after which
tenant-scoped queries see no rows (fail closed).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.core.config import DatabaseCredentials, Settings
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session

Role = Literal["runtime", "owner", "platform"]


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Server-validated context for one transaction. All fields are optional."""

    user_id: UUID | None = None
    tenant_id: UUID | None = None
    branch_ids: Sequence[UUID] = field(default_factory=tuple)


def build_url(settings: Settings, credentials: DatabaseCredentials) -> URL:
    """Build a connection URL; ``URL.create`` escapes special characters in the password."""
    return URL.create(
        "postgresql+psycopg",
        username=credentials.user,
        password=credentials.password.get_secret_value(),
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


def create_db_engine(settings: Settings, role: Role = "runtime") -> Engine:
    """Create an engine for the runtime, owner (migrations) or platform role."""
    credentials = {
        "runtime": lambda: settings.runtime_role,
        "owner": lambda: settings.owner_role,
        "platform": lambda: settings.platform_role,
    }[role]()
    return create_engine(
        build_url(settings, credentials),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
        hide_parameters=True,
    )


def apply_context(session: Session, context: RequestContext) -> None:
    """Write the context into the current transaction (transaction-local)."""
    values = {
        "app.user_id": str(context.user_id) if context.user_id else "",
        "app.tenant_id": str(context.tenant_id) if context.tenant_id else "",
        "app.branch_ids": ",".join(str(b) for b in context.branch_ids),
    }
    for name, value in values.items():
        session.execute(
            text("SELECT set_config(:name, :value, true)"), {"name": name, "value": value}
        )


@contextmanager
def session_scope(engine: Engine, context: RequestContext | None = None) -> Iterator[Session]:
    """One transaction with the request context applied first; commits on success."""
    with Session(engine) as session, session.begin():
        apply_context(session, context or RequestContext())
        yield session
