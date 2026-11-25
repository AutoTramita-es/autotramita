"""A software authenticator for the Keycloak WebAuthn registration page (test-only).

It produces what a browser would post after ``navigator.credentials.create``: client data, a
``none`` attestation and an ES256 public key. It proves nothing about real hardware."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import struct
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from tests.identity.kc import Browser, Page, form_action, hidden_inputs


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _head(major: int, length: int) -> bytes:
    if length < 24:
        return bytes([major << 5 | length])
    if length < 256:
        return bytes([major << 5 | 24, length])
    return bytes([major << 5 | 25]) + struct.pack(">H", length)


def cbor(value: Any) -> bytes:
    """Just enough CBOR for an attestation object: integers, bytes, text and maps."""
    if isinstance(value, int):
        return _head(0, value) if value >= 0 else _head(1, -1 - value)
    if isinstance(value, bytes):
        return _head(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode()
        return _head(3, len(encoded)) + encoded
    assert isinstance(value, dict)
    return _head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())


def _page_value(page: Page, name: str) -> re.Match[str] | None:
    """A value the page's script passes to the WebAuthn API: ``name : '…'`` (Keycloak 26.4),
    ``name : "…"`` (26.8, FreeMarker ``?c``) or JSON ``"name": "…"``."""
    return (
        re.search(name + r" : '([^']+)'", page.text)
        or re.search(name + r' : "([^"]+)"', page.text)
        or re.search(r'"' + name + r'"\s*:\s*"([^"]+)"', page.text)
    )


class SoftwareKey:
    """The private half of a registered software passkey, to answer sign-in challenges."""

    def __init__(self) -> None:
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.credential = secrets.token_bytes(32)
        self.counter = 0


def register(browser: Browser, page: Page, origin: str, key: SoftwareKey | None = None) -> Page:
    """Answer Keycloak's passkey registration page."""
    holder = key or SoftwareKey()
    challenge = _page_value(page, "challenge")
    rp = _page_value(page, "rpId")
    assert challenge and rp, page.summary
    numbers = holder.private.public_key().public_numbers()
    credential = holder.credential
    public_key = cbor(
        {
            1: 2,
            3: -7,
            -1: 1,
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        }
    )
    authenticator_data = (
        hashlib.sha256(rp.group(1).encode()).digest()
        + bytes([0x45])  # user present, user verified, attested credential data
        + struct.pack(">I", 0)
        + bytes(16)
        + struct.pack(">H", len(credential))
        + credential
        + public_key
    )
    client_data = json.dumps(
        {
            "type": "webauthn.create",
            "challenge": challenge.group(1),
            "origin": origin,
            "crossOrigin": False,
        }
    ).encode()
    attestation = cbor({"fmt": "none", "attStmt": {}, "authData": authenticator_data})
    return browser.submit(
        page,
        {
            "clientDataJSON": _b64(client_data),
            "attestationObject": _b64(attestation),
            "publicKeyCredentialId": _b64(credential),
            "authenticatorLabel": "software key",
            "transports": "internal",
            # what the browser reports for a built-in authenticator (Keycloak 26.8 reads it)
            "authenticatorAttachment": "platform",
            "error": "",
        },
        action=form_action(page.text),
    )


def authenticate(
    browser: Browser, page: Page, origin: str, key: SoftwareKey, *, forged: bool = False
) -> Page:
    """Answer Keycloak's passkey sign-in page, as a browser would after
    ``navigator.credentials.get``. ``forged`` signs with a different private key."""
    challenge = _page_value(page, "challenge")
    rp = _page_value(page, "rpId")
    assert challenge and rp, page.summary
    key.counter += 1
    authenticator_data = (
        hashlib.sha256(rp.group(1).encode()).digest()
        + bytes([0x05])  # user present, user verified
        + struct.pack(">I", key.counter)
    )
    client_data = json.dumps(
        {
            "type": "webauthn.get",
            "challenge": challenge.group(1),
            "origin": origin,
            "crossOrigin": False,
        }
    ).encode()
    signer = ec.generate_private_key(ec.SECP256R1()) if forged else key.private
    signature = signer.sign(
        authenticator_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
    )
    fields = hidden_inputs(page.text)
    fields.pop("tryAnotherWay", None)  # the hidden field of the other form on this page
    fields.update(
        {
            "clientDataJSON": _b64(client_data),
            "authenticatorData": _b64(authenticator_data),
            "signature": _b64(signature),
            "credentialId": _b64(key.credential),
            "userHandle": "",
            "error": "",
        }
    )
    action = re.search(r'<form[^>]*id="webauth"[^>]*action="([^"]+)"', page.text) or re.search(
        r'<form[^>]*action="([^"]+)"[^>]*id="webauth"', page.text
    )
    target = action.group(1).replace("&amp;", "&") if action else form_action(page.text)
    return browser.submit(page, fields, action=target)
