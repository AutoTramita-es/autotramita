"""A local identity provider for unit tests (F2-T02): real RSA/EC keys, a JWKS document and a
token builder with controllable claims and headers. No network. Test-only."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from collections.abc import Mapping
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

ISSUER = "https://auth.test.invalid/realms/autotramita-test"
NOW = 1_800_000_000.0


class Clock:
    def __init__(self, start: float = NOW) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class FakeIdp:
    def __init__(self) -> None:
        self.rsa: dict[str, rsa.RSAPrivateKey] = {}
        self.ec: dict[str, ec.EllipticCurvePrivateKey] = {}
        self.fetches = 0
        self.down = False
        self.add_rsa("rsa-1")
        self.add_ec("ec-1")

    def add_rsa(self, kid: str) -> None:
        self.rsa[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def add_ec(self, kid: str) -> None:
        self.ec[kid] = ec.generate_private_key(ec.SECP256R1())

    def remove(self, kid: str) -> None:
        self.rsa.pop(kid, None)
        self.ec.pop(kid, None)

    def jwks(self) -> dict[str, Any]:
        keys: list[dict[str, Any]] = []
        for kid, rsa_key in self.rsa.items():
            jwk = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
            keys.append({**jwk, "kid": kid, "use": "sig", "alg": "RS256"})
        for kid, ec_key in self.ec.items():
            jwk = json.loads(ECAlgorithm.to_jwk(ec_key.public_key()))
            keys.append({**jwk, "kid": kid, "use": "sig", "alg": "ES256"})
        return {"keys": keys}

    def fetch(self) -> Mapping[str, Any]:
        from app.auth.tokens import JwksFetchError

        self.fetches += 1
        if self.down:
            raise JwksFetchError("down")
        return self.jwks()

    @staticmethod
    def claims(now: float = NOW, **overrides: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "iss": ISSUER,
            "sub": "7b2f0c1e-6f9e-4f0e-9a52-0d4b6b2f8a11",
            "sid": "5d1c5b7e-0f0c-4f5a-8f0a-9b0c1d2e3f40",
            "aud": ["at-api", "account"],
            "azp": "at-mobile",
            "typ": "Bearer",
            "iat": int(now) - 10,
            "exp": int(now) + 290,
            "auth_time": int(now) - 10,
            "acr": "loa1",
            "email": "person@example.test",
            "email_verified": True,
        }
        base.update(overrides)
        return {k: v for k, v in base.items() if v is not _DROP}

    def token(
        self,
        *,
        kid: str = "rsa-1",
        algorithm: str = "RS256",
        now: float = NOW,
        headers: Mapping[str, Any] | None = None,
        **overrides: Any,
    ) -> str:
        claims = self.claims(now, **overrides)
        key = self.rsa[kid] if algorithm == "RS256" else self.ec[kid]
        return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid, **(headers or {})})

    def sign(
        self, claims: Mapping[str, Any], *, kid: str = "rsa-1", algorithm: str = "RS256"
    ) -> str:
        """Sign arbitrary claims (ID and logout tokens in the web sign-in tests)."""
        key = self.rsa[kid] if algorithm == "RS256" else self.ec[kid]
        return jwt.encode(dict(claims), key, algorithm=algorithm, headers={"kid": kid})

    @staticmethod
    def id_claims(
        nonce: str, *, client_id: str = "at-web", now: float = NOW, **overrides: Any
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "iss": ISSUER,
            "sub": "7b2f0c1e-6f9e-4f0e-9a52-0d4b6b2f8a11",
            "sid": "5d1c5b7e-0f0c-4f5a-8f0a-9b0c1d2e3f40",
            "aud": client_id,
            "azp": client_id,
            "typ": "ID",
            "nonce": nonce,
            "iat": int(now) - 5,
            "exp": int(now) + 295,
            "auth_time": int(now) - 5,
            "acr": "loa1",
            "email": "person@example.test",
            "email_verified": True,
        }
        base.update(overrides)
        return {k: v for k, v in base.items() if v is not _DROP}

    @staticmethod
    def logout_claims(
        *, client_id: str = "at-web", now: float = NOW, **overrides: Any
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "iss": ISSUER,
            "aud": client_id,
            "iat": int(now) - 2,
            "exp": int(now) + 120,
            "jti": uuid.uuid4().hex,
            "sub": "7b2f0c1e-6f9e-4f0e-9a52-0d4b6b2f8a11",
            "sid": "5d1c5b7e-0f0c-4f5a-8f0a-9b0c1d2e3f40",
            "typ": "Logout",
            "events": {"http://schemas.openid.net/event/backchannel-logout": {}},
        }
        base.update(overrides)
        return {k: v for k, v in base.items() if v is not _DROP}

    def unsigned(self, **overrides: Any) -> str:
        """``alg: none`` token with the right claims (the classic downgrade attack)."""
        header = _b64(json.dumps({"alg": "none", "typ": "JWT", "kid": "rsa-1"}).encode())
        body = _b64(json.dumps(self.claims(**overrides)).encode())
        return f"{header}.{body}."

    def hmac_with_public_key(self, kid: str = "rsa-1") -> str:
        """HS256 token signed with the published public key as the HMAC secret."""
        public_pem = (
            self.rsa[kid]
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
        )
        header = _b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode())
        body = _b64(json.dumps(self.claims()).encode())
        signature = hmac.new(public_pem, f"{header}.{body}".encode(), hashlib.sha256).digest()
        return f"{header}.{body}.{_b64(signature)}"


_DROP = object()
DROP = _DROP  # pass DROP as an override to remove a claim
