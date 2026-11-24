"""``return_to`` handling (F2-T06, D14): only a path on our own site is ever followed, so the
sign-in redirect cannot be turned into an open redirect."""

from __future__ import annotations

from urllib.parse import unquote

MAX_LENGTH = 512


def _bad(candidate: str) -> bool:
    return (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate)
        or "://" in candidate.split("?", 1)[0]
    )


def safe_return_to(value: object, default: str = "/") -> str:
    """Return ``value`` if it is a same-site absolute path, otherwise ``default``.

    The text is also checked after one and two rounds of percent-decoding, because a browser or
    proxy may decode it before following it (``/%2F/evil.example`` becomes ``//evil.example``)."""
    if not isinstance(value, str) or not value or len(value) > MAX_LENGTH:
        return default
    candidate = value
    for _ in range(3):
        if _bad(candidate):
            return default
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    return value
