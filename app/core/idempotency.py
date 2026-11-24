"""Idempotency for consequential POST requests (ADR-004).

Flow: ``begin`` claims the key in its own short transaction (visible to concurrent retries),
the handler runs, then ``complete`` stores the response for replay or ``release`` frees the
key after a server failure so the client may retry. Same key with a different request body
is rejected. Keys are scoped by tenant context (RLS), user and route and kept 24 hours.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any
from uuid import UUID

from app.core.db import RequestContext, session_scope
from app.core.errors import BadRequest, Conflict, UnprocessableEntity
from fastapi import Header
from sqlalchemy import Engine, text

DEFAULT_TTL = timedelta(hours=24)
_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    body: Any


def idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    """Dependency: validated ``Idempotency-Key`` header (required on consequential POST)."""
    if idempotency_key is None:
        raise BadRequest("Send an Idempotency-Key header.", code="idempotency_key_required")
    if not _KEY.fullmatch(idempotency_key):
        raise BadRequest(
            "Idempotency-Key must be 8 to 128 characters of letters, digits and . _ : -",
            code="idempotency_key_invalid",
        )
    return idempotency_key


def scope_for(user_id: UUID | None, method: str, route: str) -> str:
    raw = f"{user_id or '-'}|{method.upper()}|{route}"
    return hashlib.sha256(raw.encode()).hexdigest()


def request_hash(body: bytes) -> str:
    """Hash of the request payload; JSON is canonicalized so key order does not matter."""
    try:
        canonical = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode()
    except ValueError:
        canonical = body
    return hashlib.sha256(canonical).hexdigest()


def begin(
    engine: Engine,
    context: RequestContext,
    *,
    scope: str,
    key: str,
    body_hash: str,
    ttl: timedelta = DEFAULT_TTL,
) -> StoredResponse | None:
    """Return ``None`` if the caller now owns the key, or the stored response to replay."""
    params = {"scope": scope, "key": key, "hash": body_hash, "ttl": ttl}
    with session_scope(engine, context) as session:
        session.execute(
            text(
                "DELETE FROM idempotency_keys WHERE scope = :scope AND key = :key "
                "AND expires_at <= now()"
            ),
            params,
        )
        claimed = session.execute(
            text(
                "INSERT INTO idempotency_keys "
                "(tenant_id, scope, key, request_hash, state, expires_at) "
                "VALUES (coalesce(app_tenant_id(), '00000000-0000-0000-0000-000000000000'::uuid), "
                ":scope, :key, :hash, 'in_progress', now() + :ttl) ON CONFLICT DO NOTHING "
                "RETURNING 1"
            ),
            params,
        ).first()
        if claimed:
            return None
        row = session.execute(
            text(
                "SELECT request_hash, state, status_code, response_body FROM idempotency_keys "
                "WHERE scope = :scope AND key = :key"
            ),
            params,
        ).one()
    if row.request_hash != body_hash:
        raise UnprocessableEntity(
            "This Idempotency-Key was already used with a different request.",
            code="idempotency_key_reuse",
        )
    if row.state == "in_progress":
        raise Conflict(
            "A request with this Idempotency-Key is still being processed.",
            code="idempotency_in_progress",
            headers={"Retry-After": "1"},
        )
    return StoredResponse(status_code=row.status_code, body=row.response_body)


def complete(
    engine: Engine, context: RequestContext, *, scope: str, key: str, status_code: int, body: Any
) -> None:
    with session_scope(engine, context) as session:
        session.execute(
            text(
                "UPDATE idempotency_keys SET state = 'completed', status_code = :code, "
                "response_body = CAST(:body AS jsonb) WHERE scope = :scope AND key = :key"
            ),
            {"scope": scope, "key": key, "code": status_code, "body": json.dumps(body)},
        )


def release(engine: Engine, context: RequestContext, *, scope: str, key: str) -> None:
    """Free an unfinished key after a server failure so the client can retry."""
    with session_scope(engine, context) as session:
        session.execute(
            text(
                "DELETE FROM idempotency_keys WHERE scope = :scope AND key = :key "
                "AND state = 'in_progress'"
            ),
            {"scope": scope, "key": key},
        )


def purge_expired(engine: Engine, context: RequestContext) -> int:
    """Delete expired keys visible in this context (run per tenant by a maintenance job)."""
    with session_scope(engine, context) as session:
        result = session.execute(text("DELETE FROM idempotency_keys WHERE expires_at <= now()"))
        return int(getattr(result, "rowcount", 0))
