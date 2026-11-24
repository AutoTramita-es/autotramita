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

from cryptography.hazmat.primitives.asymmetric import ec
from tests.identity.kc import Browser, Page, form_action


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


def register(browser: Browser, page: Page, origin: str) -> Page:
    """Answer Keycloak's passkey registration page."""
    challenge = re.search(r"challenge : '([^']+)'", page.text)
    rp = re.search(r"rpId : '([^']+)'", page.text)
    assert challenge and rp, page.summary
    numbers = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
    credential = secrets.token_bytes(32)
    key = cbor(
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
        + key
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
            "error": "",
        },
        action=form_action(page.text),
    )
