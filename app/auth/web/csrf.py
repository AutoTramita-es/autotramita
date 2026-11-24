"""CSRF protection for cookie-authenticated requests (F2-T06, D14).

The token is derived from the session credential (HMAC), so it needs no storage and changes
when the credential is rotated. An unsafe request must carry it in ``X-CSRF-Token`` *and* come
from one of our own origins (``Origin``, or ``Sec-Fetch-Site: same-origin`` when the browser
sends no ``Origin``). Bearer requests carry no ambient credential and are not subject to this."""

from __future__ import annotations

import base64
import hashlib
import hmac
from collections.abc import Collection

from app.auth.errors import CsrfInvalid
from starlette.requests import Request

HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def csrf_token(credential: str) -> str:
    mac = hmac.new(credential.encode("ascii"), b"at-csrf-v1", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def verify_csrf(request: Request, credential: str, allowed_origins: Collection[str]) -> None:
    """Raise ``CsrfInvalid`` unless the request proves it comes from our own pages."""
    given = request.headers.get(HEADER, "")
    if not hmac.compare_digest(given.encode(), csrf_token(credential).encode()):
        raise CsrfInvalid()
    origin = request.headers.get("origin")
    if origin is not None:
        if origin not in allowed_origins:
            raise CsrfInvalid()
        return
    if request.headers.get("sec-fetch-site") != "same-origin":
        raise CsrfInvalid()
