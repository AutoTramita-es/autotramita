"""Database role model (ADR-002, G5-01): owner, app, worker and platform per environment.

Only the owner role owns objects and runs migrations. The other roles never own tables, have
no BYPASSRLS and get privileges from default privileges plus explicit per-migration grants.
This module is used by tests and by future provisioning tooling; it is not run against the
shared server in F1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

_NAME = re.compile(r"^[a-z][a-z0-9_]{2,62}$")
_HARDEN_SQL = Path(__file__).resolve().parents[2] / "scripts" / "db" / "harden.sql"


def _checked(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError(f"Invalid PostgreSQL identifier: {name!r}")
    return name


@dataclass(frozen=True, slots=True)
class RoleNames:
    owner: str
    app: str
    worker: str
    platform: str

    @classmethod
    def for_base(cls, base: str) -> RoleNames:
        """``autotramita_dev`` -> ``autotramita_dev_owner`` and so on."""
        _checked(base)
        return cls(*(_checked(f"{base}_{r}") for r in ("owner", "app", "worker", "platform")))

    def all(self) -> tuple[str, str, str, str]:
        return (self.owner, self.app, self.worker, self.platform)


def create_roles(conn: psycopg.Connection, names: RoleNames, passwords: dict[str, str]) -> None:
    """Create missing LOGIN roles with safe attributes. Existing roles are not changed."""
    if set(passwords) != {"owner", "app", "worker", "platform"}:
        raise ValueError("passwords must cover owner, app, worker and platform")
    if len(set(passwords.values())) != 4:
        raise ValueError("The four database roles must use distinct passwords")
    for kind, role in zip(("owner", "app", "worker", "platform"), names.all(), strict=True):
        exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        if not exists:
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS NOINHERIT"
                ).format(sql.Identifier(role), sql.Literal(passwords[kind]))
            )
        safe = conn.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s AND rolcanlogin AND NOT "
            "(rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)",
            (role,),
        ).fetchone()
        if not safe:
            raise RuntimeError(f"{role} has unsafe attributes; correct them manually.")


def harden(conn: psycopg.Connection, database: str, names: RoleNames) -> None:
    """Apply scripts/db/harden.sql inside ``database`` (connection must be to that database)."""
    statements = sql.SQL(_HARDEN_SQL.read_text()).format(
        db=sql.Identifier(_checked(database)),
        owner=sql.Identifier(names.owner),
        app=sql.Identifier(names.app),
        worker=sql.Identifier(names.worker),
        platform=sql.Identifier(names.platform),
    )
    conn.execute(statements)
