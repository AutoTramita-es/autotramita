"""Synchronous database layer (SQLAlchemy 2.x, psycopg 3).

Tenant isolation follows ADR-002: the request context is written with transaction-local
``set_config(..., true)`` on the same connection and transaction as the queries, so nothing
can leak to the next user of a pooled connection. Row-level security policies read these
settings; this module never trusts caller-supplied tenant data beyond typed UUIDs.

Always use ``session_scope``: it applies the context as the first statement and commits at
exit. Transactions are explicit (R01): sessions never autobegin, so a session used outside
``session_scope`` cannot run any statement. A commit, rollback or close inside the block ends
the scope's transaction and drops the context; the session then rejects every further
statement (``InvalidRequestError``) instead of silently starting a new, context-free
transaction. Do not commit inside the block; ``session_scope`` commits at exit.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.core.config import DatabaseCredentials, DatabaseRole, Settings
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

# "runtime" is the pre-T03 name of the app role and stays accepted for compatibility.
Role = Literal["runtime", "owner", "app", "worker", "platform"]


_SUBJECT = re.compile(r"[A-Za-z0-9._:-]{1,128}")


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Server-validated context for one transaction. All fields are optional."""

    user_id: UUID | None = None
    tenant_id: UUID | None = None
    branch_ids: Sequence[UUID] = field(default_factory=tuple)
    # Authentication bootstrap (F2, D17): set only by app.auth, before the user is known. They
    # let a policy recognise the one row whose secret/subject the caller proves; see 0002.
    auth_subject: str | None = None
    session_hash: bytes | None = None

    def __post_init__(self) -> None:
        """Only real UUIDs are accepted; strings and other raw input are rejected."""
        for name in ("user_id", "tenant_id"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, UUID):
                raise TypeError(f"{name} must be a UUID or None")
        if isinstance(self.branch_ids, str | bytes) or not all(
            isinstance(b, UUID) for b in self.branch_ids
        ):
            raise TypeError("branch_ids must be a sequence of UUIDs")
        object.__setattr__(self, "branch_ids", tuple(self.branch_ids))
        if self.auth_subject is not None:
            if not isinstance(self.auth_subject, str):
                raise TypeError("auth_subject must be a string or None")
            if not _SUBJECT.fullmatch(self.auth_subject):
                raise ValueError("auth_subject has an invalid format")
        if self.session_hash is not None:
            if not isinstance(self.session_hash, bytes):
                raise TypeError("session_hash must be bytes or None")
            if len(self.session_hash) != 32:
                raise ValueError("session_hash must be a 32-byte SHA-256 digest")


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


def create_db_engine(settings: Settings, role: Role = "app") -> Engine:
    """Create an engine for exactly one role; nothing is opened until first use.

    A role that is not configured raises ``RuntimeError``; there is no fallback to another
    role, so the API runtime (``app``) can never end up on the owner or platform role.
    """
    kind: DatabaseRole = "app" if role == "runtime" else role
    return create_engine(
        build_url(settings, settings.role_credentials(kind)),
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_recycle=1800,
        hide_parameters=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Session factory bound to one role's engine. ``autobegin`` is off: a transaction only
    exists inside ``session_scope``; ``expire_on_commit`` is off so results stay readable."""
    return sessionmaker(engine, expire_on_commit=False, autobegin=False)


def apply_context(session: Session, context: RequestContext) -> None:
    """Write the context into the current transaction (transaction-local)."""
    values = {
        "app.user_id": str(context.user_id) if context.user_id else "",
        "app.tenant_id": str(context.tenant_id) if context.tenant_id else "",
        "app.branch_ids": ",".join(str(b) for b in context.branch_ids),
        "app.auth_subject": context.auth_subject or "",
        "app.session_hash": context.session_hash.hex() if context.session_hash else "",
    }
    for name, value in values.items():
        session.execute(
            text("SELECT set_config(:name, :value, true)"), {"name": name, "value": value}
        )


@contextmanager
def session_scope(
    engine: Engine | sessionmaker[Session], context: RequestContext | None = None
) -> Iterator[Session]:
    """One transaction with the request context applied first; commits on success, rolls
    back on any exception, and always closes the session (returning the connection).

    A caller-supplied factory must disable autobegin (use ``create_session_factory``);
    otherwise ``ValueError`` is raised before any connection is used.
    """
    factory = engine if isinstance(engine, sessionmaker) else create_session_factory(engine)
    if factory.kw.get("autobegin", True):
        raise ValueError("session_scope requires a session factory with autobegin=False")
    with factory() as session, session.begin():
        apply_context(session, context or RequestContext())
        yield session
