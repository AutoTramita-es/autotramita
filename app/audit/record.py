"""Writing audit events (F2-T03). Validation happens before the database is touched; the
database then enforces the same limits again (CHECK constraints, row-level security).

``record`` joins the caller's transaction, so a business change and its audit record commit or
roll back together. ``record_independent`` uses its own transaction for events that must
survive a rolled-back request (failed or denied attempts)."""

from __future__ import annotations

import ipaddress
import re
import uuid
from typing import Any

from app.audit.catalog import CATALOG, Kind
from app.audit.models import AuditEvent
from app.core.db import RequestContext, session_scope
from app.core.request_context import get_request_id
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Words and shapes that must never reach an audit record (also enforced by a CHECK in 0003).
_FORBIDDEN = re.compile(
    r"password|passwd|secret|authorization|cookie|code_verifier|id_token|refresh_token|"
    r"access_token|client_secret|bearer |eyJ[A-Za-z0-9_-]{10,}[.]|"
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+[.][A-Za-z]{2,}",
    re.IGNORECASE,
)
# Values in general audit fields may not smuggle full IPs around the prefix column.
_RAW_IP = re.compile(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}|(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}", re.I)


_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,59}$")


class AuditValidationError(ValueError):
    """The event cannot be recorded; the message never contains the offending value."""


def ip_prefix(address: str | None) -> str | None:
    """Coarse network of a client address: /24 for IPv4, /48 for IPv6. Never the full address."""
    if not address:
        return None
    try:
        parsed = ipaddress.ip_address(address.strip())
    except ValueError:
        return None
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped:
        parsed = parsed.ipv4_mapped
    length = 24 if parsed.version == 4 else 48
    return str(ipaddress.ip_network(f"{parsed}/{length}", strict=False))


def ua_family(user_agent: str | None) -> str | None:
    """Browser/app family only (D24): enough to notice a change, nothing identifying."""
    if not user_agent:
        return None
    ua = user_agent.lower()
    for family, marker in (
        ("Edge", "edg/"),
        ("Opera", "opr/"),
        ("Firefox", "firefox/"),
        ("Chrome", "chrome/"),
        ("Safari", "safari/"),
        ("Dart", "dart/"),
        ("OkHttp", "okhttp"),
    ):
        if marker in ua:
            return family
    return "Other"


def _check_value(kind: Kind, value: Any) -> None:
    if kind == "int":
        ok = isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 10**9
    elif kind == "bool":
        ok = isinstance(value, bool)
    elif kind == "uuid":
        ok = isinstance(value, uuid.UUID | str) and bool(_UUID.fullmatch(str(value).lower()))
    else:
        ok = isinstance(value, str) and bool(_CODE.fullmatch(value))
    if not ok:
        raise AuditValidationError("a detail value has an invalid type or format")


def validate(event: AuditEvent) -> dict[str, Any]:
    """Check the event against the catalog and return the JSON-ready details."""
    spec = CATALOG.get(event.action)
    if spec is None:
        raise AuditValidationError("unknown audit action")
    unknown = set(event.details) - set(spec.details)
    if unknown:
        raise AuditValidationError("a detail key is not allowed for this action")
    safe: dict[str, Any] = {}
    for key, value in event.details.items():
        _check_value(spec.details[key], value)
        safe[key] = str(value) if isinstance(value, uuid.UUID) else value
        if (
            _FORBIDDEN.search(key)
            or _FORBIDDEN.search(str(value))
            or _RAW_IP.search(key)
            or _RAW_IP.search(str(value))
        ):
            raise AuditValidationError("a detail looks like a secret or personal data")
    for value in (event.target_type, event.ua_family, event.source_event_id):
        if value is not None and (_FORBIDDEN.search(value) or _RAW_IP.search(value)):
            raise AuditValidationError("audit metadata looks like personal data or a secret")
    if event.reason_code is not None and not _REASON.fullmatch(event.reason_code):
        raise AuditValidationError("reason_code must be UPPER_SNAKE_CASE")
    if event.target_type is not None and not _CODE.fullmatch(event.target_type):
        raise AuditValidationError("target_type has an invalid format")
    if event.ip_prefix is not None:
        try:
            network = ipaddress.ip_network(event.ip_prefix, strict=True)
        except ValueError:
            raise AuditValidationError("ip_prefix is not a network") from None
        if network.prefixlen > (24 if network.version == 4 else 48):
            raise AuditValidationError("ip_prefix must be a truncated network, not an address")
    if event.ua_family is not None and not _CODE.fullmatch(event.ua_family):
        raise AuditValidationError("ua_family has an invalid format")
    return safe


_INSERT = text(
    """
    INSERT INTO audit_events (
        id, scope, category, action, outcome, actor_type, actor_user_id, actor_session_id,
        subject_user_id, tenant_id, branch_id, target_type, target_id, request_id, ip_prefix,
        ua_family, reason_code, details, source, source_event_id)
    VALUES (
        :id, :scope, :category, :action, :outcome, :actor_type, :actor_user_id, :actor_session_id,
        :subject_user_id, :tenant_id, :branch_id, :target_type, :target_id, :request_id,
        CAST(:ip_prefix AS cidr), :ua_family, :reason_code, CAST(:details AS jsonb), :source,
        :source_event_id)
    ON CONFLICT DO NOTHING  -- no target: the worker holds no SELECT privilege
    """
)


def record(session: Session, event: AuditEvent) -> bool:
    """Write the event in the caller's transaction. Returns False for a duplicate
    ``(source, source_event_id)`` (idempotent ingestion), True when a row was added."""
    import json

    details = validate(event)
    spec = CATALOG[event.action]
    request_id = event.request_id
    if request_id is None:
        current = get_request_id()
        request_id = uuid.UUID(current) if current else None
    result = session.execute(
        _INSERT,
        {
            "id": uuid.uuid4(),
            "scope": event.scope.value,
            "category": spec.category.value,
            "action": event.action,
            "outcome": event.outcome.value,
            "actor_type": event.actor_type.value,
            "actor_user_id": event.actor_user_id,
            "actor_session_id": event.actor_session_id,
            "subject_user_id": event.subject_user_id,
            "tenant_id": event.tenant_id,
            "branch_id": event.branch_id,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "request_id": request_id,
            "ip_prefix": event.ip_prefix,
            "ua_family": event.ua_family,
            "reason_code": event.reason_code,
            "details": json.dumps(details, sort_keys=True),
            "source": event.source.value,
            "source_event_id": event.source_event_id,
        },
    )
    return bool(result.rowcount)  # type: ignore[attr-defined]


def record_independent(
    factory: sessionmaker[Session], event: AuditEvent, context: RequestContext | None = None
) -> bool:
    """Write the event in its own transaction, so it persists even if the request fails."""
    with session_scope(factory, context) as session:
        return record(session, event)
