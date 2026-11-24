"""Idempotency for consequential POST requests (ADR-004, AT-01 O03).

Scope is actor + tenant + operation + key; the request fingerprint is SHA-256 over the method,
the operation and the canonical request body (``app.core.canonical``). Behaviour:

* the caller is re-authorized on EVERY request, including replays (``authorize`` runs first);
* a missing key is 400 (see ``idempotency_key``); the same key with another payload, or a
  request that arrives while the first is still running, is 409;
* an identical finished request returns the stored response without running the handler;
* keys live 24 hours; an expired key behaves as if it never existed.

Atomicity: everything happens in ONE PostgreSQL transaction, taken under a transaction-level
advisory lock on the scope. The handler's business changes and the stored response commit
together or not at all, so a crash or exception leaves no half-finished key behind and the
client can simply retry. The handler receives the transaction's session and must not commit.

The ``idempotency_keys`` table is NOT part of the F1 migrations (owner decision); F1 tests
create it as a disposable fixture (``tests/idempotency_fixture.py``). Redis plays no role.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any

from app.core.canonical import canonical_json, sha256_hex
from app.core.db import RequestContext, session_scope
from app.core.errors import BadRequest, Conflict, Forbidden, Unauthenticated
from fastapi import Header
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

DEFAULT_TTL = timedelta(hours=24)
MAX_KEY_LENGTH = 128
_KEY = re.compile(rf"^[A-Za-z0-9._:-]{{8,{MAX_KEY_LENGTH}}}$")


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    body: Any


@dataclass(frozen=True, slots=True)
class IdempotentResult:
    response: StoredResponse
    replayed: bool


def idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    """Dependency: validated ``Idempotency-Key`` header (required on consequential POST)."""
    if idempotency_key is None:
        raise BadRequest("Send an Idempotency-Key header.", code="IDEMPOTENCY_KEY_REQUIRED")
    if not _KEY.fullmatch(idempotency_key):
        raise BadRequest(
            f"Idempotency-Key must be 8 to {MAX_KEY_LENGTH} characters of letters, digits "
            "and . _ : - (a UUID v4 is recommended).",
            code="IDEMPOTENCY_KEY_INVALID",
        )
    return idempotency_key


def fingerprint(method: str, operation: str, body: bytes) -> str:
    """SHA-256 of method, operation and canonical body. JSON bodies are canonicalized (key
    order and whitespace do not matter); other bodies are hashed as raw bytes."""
    try:
        kind, content = b"json", canonical_json(json.loads(body))
    except ValueError:
        kind, content = b"raw", body
    head = f"{method.upper()}\n{operation}\n".encode()
    return sha256_hex(head + kind + b"\n" + content)


def execute_idempotent(
    engine: Engine,
    context: RequestContext,
    *,
    method: str,
    operation: str,
    key: str,
    body: bytes,
    authorize: Callable[[], None],
    handler: Callable[[Session], StoredResponse],
    ttl: timedelta = DEFAULT_TTL,
) -> IdempotentResult:
    """Run ``handler`` at most once per scope and fingerprint; replay its stored response."""
    if context.user_id is None:
        raise Unauthenticated("An authenticated actor is required.")
    if context.tenant_id is None:
        raise Forbidden("A tenant context is required.", code="TENANT_CONTEXT_REQUIRED")
    authorize()  # always, so a replay is never served to a caller who lost access
    fp = fingerprint(method, operation, body)
    scope = {
        "tenant": context.tenant_id,
        "actor": context.user_id,
        "operation": operation,
        "key": key,
    }
    lock_name = f"{context.tenant_id}|{context.user_id}|{operation}|{key}"
    with session_scope(engine, context) as session:
        locked = session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtextextended(:name, 0))"),
            {"name": lock_name},
        ).scalar_one()
        if not locked:
            raise Conflict(
                "A request with this Idempotency-Key is still being processed.",
                code="IDEMPOTENCY_IN_PROGRESS",
                headers={"Retry-After": "1"},
            )
        session.execute(
            text(
                "DELETE FROM idempotency_keys WHERE tenant_id = :tenant AND actor_id = :actor "
                "AND operation = :operation AND key = :key AND expires_at <= now()"
            ),
            scope,
        )
        row = session.execute(
            text(
                "SELECT fingerprint, status_code, response_body FROM idempotency_keys "
                "WHERE tenant_id = :tenant AND actor_id = :actor AND operation = :operation "
                "AND key = :key"
            ),
            scope,
        ).first()
        if row is not None:
            if row.fingerprint != fp:
                raise Conflict(
                    "This Idempotency-Key was already used with a different request.",
                    code="IDEMPOTENCY_KEY_REUSE",
                )
            return IdempotentResult(StoredResponse(row.status_code, row.response_body), True)
        response = handler(session)
        session.execute(
            text(
                "INSERT INTO idempotency_keys (tenant_id, actor_id, operation, key, fingerprint, "
                "status_code, response_body, expires_at) VALUES (:tenant, :actor, :operation, "
                ":key, :fp, :code, CAST(:body AS jsonb), now() + :ttl)"
            ),
            {
                **scope,
                "fp": fp,
                "code": response.status_code,
                "body": json.dumps(response.body),
                "ttl": ttl,
            },
        )
        return IdempotentResult(response, False)


def purge_expired(engine: Engine, context: RequestContext) -> int:
    """Delete expired keys visible in this context (run per tenant by a maintenance job)."""
    with session_scope(engine, context) as session:
        result = session.execute(text("DELETE FROM idempotency_keys WHERE expires_at <= now()"))
        return int(getattr(result, "rowcount", 0))
