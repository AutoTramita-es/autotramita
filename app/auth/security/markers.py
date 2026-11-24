"""Pending-reset markers (F2-T09, D20). Keycloak sends the recovery link and the person sets the
new password on Keycloak's own page, so the application learns about it only at the next
sign-in. A marker records *when* a recovery e-mail was sent; the sign-in compares it with the
age of the password credential and, if the password really changed, ends every other session."""

from __future__ import annotations

import hashlib

import redis
from app.core.errors import ServiceUnavailable

TTL_SECONDS = 24 * 3600


class RecoveryMarkers:
    def __init__(self, client: redis.Redis, *, namespace: str) -> None:
        self._client, self._namespace = client, namespace

    def _key(self, subject: str) -> str:
        return f"recovery:{self._namespace}:{hashlib.sha256(subject.encode()).hexdigest()[:32]}"

    def mark(self, subject: str, at: float) -> None:
        try:
            self._client.set(self._key(subject), repr(at), ex=TTL_SECONDS)
        except redis.RedisError:
            raise ServiceUnavailable("Marker store unavailable.") from None

    def get(self, subject: str) -> float | None:
        try:
            raw = self._client.get(self._key(subject))
        except redis.RedisError:
            return None
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    def clear(self, subject: str) -> None:
        try:
            self._client.delete(self._key(subject))
        except redis.RedisError:
            return
