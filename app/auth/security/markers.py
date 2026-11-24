"""Password-change markers (F2-T09, D20). Keycloak sends the recovery link and the person sets
the new password on Keycloak's own page, and it tells the application nothing. A marker records
*when* a recovery e-mail was sent and which password change has already been handled. Both the
periodic check (F-0) and the next sign-in compare it with the age of the password credential:
the first of them to see a change ends the sessions that rest on an older authentication, and
for as long as the marker lives a sign-in resting on such an authentication is refused (a
surviving single sign-on session must not open the application again). The lifetime exceeds the
longest identity-provider session (12 h).

A second set lists whom the periodic check still has to look at. It holds the provider's
opaque subject identifier (never an address) and the time of the latest recovery request."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import redis
from app.core.errors import ServiceUnavailable

TTL_SECONDS = 24 * 3600
log = logging.getLogger(__name__)
_FORGET = """
local score = redis.call('ZSCORE', KEYS[1], ARGV[1])
if score and tonumber(score) <= tonumber(ARGV[2]) then
    return redis.call('ZREM', KEYS[1], ARGV[1])
end
return 0
"""


@dataclass(frozen=True, slots=True)
class Marker:
    requested: float
    handled: float | None  # creation time of the password whose change was already acted on


class RecoveryMarkers:
    def __init__(self, client: redis.Redis, *, namespace: str) -> None:
        self._client, self._namespace = client, namespace

    def _key(self, subject: str) -> str:
        return f"pwchange:{self._namespace}:{hashlib.sha256(subject.encode()).hexdigest()[:32]}"

    def _pending_key(self) -> str:
        return f"pwpending:{self._namespace}"

    def mark(self, subject: str, at: float) -> None:
        """A recovery e-mail was sent. The earliest request is kept, so asking again can never
        hide a change that has already happened; the periodic check counts from the latest."""
        try:
            pipe = self._client.pipeline()
            pipe.hsetnx(self._key(subject), "requested", repr(at))
            pipe.expire(self._key(subject), TTL_SECONDS)
            pipe.zadd(self._pending_key(), {subject: at})
            # entries whose markers have expired go even while no worker is running
            pipe.zremrangebyscore(self._pending_key(), "-inf", at - TTL_SECONDS)
            pipe.expire(self._pending_key(), TTL_SECONDS)
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

    def pending(self) -> list[tuple[str, float]]:
        """Subjects the periodic check still looks at, with the latest request time. Raises on
        a store outage, so a sweep that saw nothing is never mistaken for one with nothing."""
        found: Any = self._client.zrange(self._pending_key(), 0, -1, withscores=True)
        return [(_text(member), float(score)) for member, score in found]

    def forget_pending(self, subject: str, requested: float) -> None:
        """Stop checking this subject, unless a newer request arrived in the meantime."""
        self._client.eval(_FORGET, 1, self._pending_key(), subject, repr(requested))

    def get(self, subject: str) -> Marker | None:
        try:
            return self.read(subject)
        except redis.RedisError:
            return None

    def read(self, subject: str) -> Marker | None:
        """Like ``get`` but a store outage raises instead of looking like "no marker"."""
        raw = self._client.hgetall(self._key(subject))
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
