"""Password-change markers (F2-T09, D20). Keycloak sends the recovery link and the person sets
the new password on Keycloak's own page, so the application learns about it only at the next
sign-in. A marker records *when* a recovery e-mail was sent and which password change has
already been handled. The sign-in compares it with the age of the password credential: the first
sign-in after a change ends the other sessions, and for as long as the marker lives a sign-in
resting on an authentication older than the change is refused (a surviving single sign-on
session must not open the application again). The lifetime exceeds the longest identity-provider
session (12 h)."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import redis
from app.core.errors import ServiceUnavailable

TTL_SECONDS = 24 * 3600
log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Marker:
    requested: float
    handled: float | None  # creation time of the password whose change was already acted on


class RecoveryMarkers:
    def __init__(self, client: redis.Redis, *, namespace: str) -> None:
        self._client, self._namespace = client, namespace

    def _key(self, subject: str) -> str:
        return f"pwchange:{self._namespace}:{hashlib.sha256(subject.encode()).hexdigest()[:32]}"

    def mark(self, subject: str, at: float) -> None:
        """A recovery e-mail was sent. The earliest request is kept, so asking again can never
        hide a change that has already happened."""
        try:
            pipe = self._client.pipeline()
            pipe.hsetnx(self._key(subject), "requested", repr(at))
            pipe.expire(self._key(subject), TTL_SECONDS)
            pipe.execute()
        except redis.RedisError:
            raise ServiceUnavailable("Marker store unavailable.") from None

    def record_change(self, subject: str, changed_at: float) -> None:
        """Remember a password change that has been acted on. Best effort: the sessions have
        already been dealt with, so a store outage is logged, not raised."""
        try:
            pipe = self._client.pipeline()
            pipe.hsetnx(self._key(subject), "requested", repr(changed_at))
            pipe.hset(self._key(subject), "handled", repr(changed_at))
            pipe.expire(self._key(subject), TTL_SECONDS)
            pipe.execute()
        except redis.RedisError:
            log.warning("password change marker not stored")

    def get(self, subject: str) -> Marker | None:
        try:
            raw = self._client.hgetall(self._key(subject))
        except redis.RedisError:
            return None
        fields = {_text(k): _text(v) for k, v in dict(raw).items()}
        try:
            handled = fields.get("handled")
            return Marker(
                float(fields["requested"]), float(handled) if handled is not None else None
            )
        except (KeyError, ValueError):
            return None


def _text(value: object) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
