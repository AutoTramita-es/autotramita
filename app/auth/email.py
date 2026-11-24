"""E-mail normalisation (F2-T04, D09). The normal form decides uniqueness, so it must be
deterministic and must not merge addresses that are different mailboxes."""

from __future__ import annotations

import unicodedata

MAX_LENGTH = 320


def normalize_email(value: str) -> str:
    """NFKC, trimmed, lower-case. Dots and ``+tags`` are kept: dropping them would merge
    mailboxes that exist separately. Raises ``ValueError`` for anything that is not a plausible
    single address (the message never contains the input)."""
    if not isinstance(value, str):
        raise ValueError("e-mail must be a string")
    text = unicodedata.normalize("NFKC", value).strip().lower()
    local, separator, domain = text.partition("@")
    if (
        not separator
        or not local
        or not domain
        or "@" in domain
        or len(text) > MAX_LENGTH
        or len(text) < 3
        or any(ch.isspace() or unicodedata.category(ch).startswith("C") for ch in text)
        or domain.startswith(".")
        or domain.endswith(".")
        or ".." in domain
        or "." not in domain
    ):
        raise ValueError("not a valid e-mail address")
    return text
