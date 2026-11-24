"""Session credentials (F2-T05, D12). The secret has 256 bits from the system CSPRNG, is shown
once and only its SHA-256 is stored, so a database leak yields no usable session."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import TypeGuard

_FORMAT = re.compile(r"^[A-Za-z0-9_-]{43}$")  # token_urlsafe(32)


def new_credential() -> tuple[str, bytes]:
    """Return ``(secret, sha256(secret))``."""
    secret = secrets.token_urlsafe(32)
    return secret, hash_credential(secret)


def is_well_formed(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and bool(_FORMAT.fullmatch(value))


def hash_credential(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("ascii")).digest()


def equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)
