"""Keycloak access-token validation (F2-T02, decisions D05/D06/D34).

The signature is verified before any claim is trusted. Allowed algorithms are an allowlist
(RS256, ES256): ``none`` and HMAC algorithms never reach key material. Claims are then checked
one by one, each with its own rejection reason, so every check is individually testable.
Tenant, branch, role and grant claims are never read: authorization is the application's (I02).

A token is only a proof of who the person is. It does not create or keep a session: the
application session (T05) is looked up afterwards, on every request.
"""

from __future__ import annotations

import hmac
import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeGuard

import httpx
import jwt
from app.auth.errors import IdentityProviderUnavailable, TokenInvalid, TokenRejection
from app.auth.settings import AuthSettings
from jwt import PyJWK
from jwt.exceptions import DecodeError, InvalidKeyError, InvalidTokenError, PyJWKError

logger = logging.getLogger(__name__)

ALLOWED_ALGORITHMS = frozenset({"RS256", "ES256"})
_MAX_JWKS_BYTES = 1_000_000


class JwksFetchError(Exception):
    """The key set could not be obtained (network, status, size or format)."""


class JwksFetcher(Protocol):
    def __call__(self) -> Mapping[str, Any]: ...


def http_jwks_fetcher(url: str, timeout: float) -> JwksFetcher:
    """Fetch the realm key set over HTTP. No redirects are followed and the body is bounded."""

    def fetch() -> Mapping[str, Any]:
        try:
            response = httpx.get(url, timeout=timeout, follow_redirects=False)
            if response.status_code != 200 or len(response.content) > _MAX_JWKS_BYTES:
                raise JwksFetchError("unexpected JWKS response")
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JwksFetchError("JWKS unavailable") from exc
        if not isinstance(body, dict) or not isinstance(body.get("keys"), list):
            raise JwksFetchError("malformed JWKS")
        return body

    return fetch


class JwksCache:
    """Signing keys by ``kid``. Cached for ``ttl`` seconds; a refresh is attempted at most once
    per ``min_refresh`` seconds, also when an unknown ``kid`` appears (key rotation, D06). If the
    provider is unreachable, only keys within the configured TTL remain usable."""

    def __init__(
        self,
        fetch: JwksFetcher,
        *,
        ttl_seconds: float,
        min_refresh_seconds: float,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch
        self._ttl = ttl_seconds
        self._min_refresh = min_refresh_seconds
        self._monotonic = monotonic
        self._keys: dict[str, PyJWK] = {}
        self._loaded_at: float | None = None
        self._attempted_at: float | None = None
        self._lock = threading.Lock()

    def key(self, kid: str) -> PyJWK:
        with self._lock:
            now = self._monotonic()
            fresh = self._loaded_at is not None and now - self._loaded_at < self._ttl
            if fresh and kid in self._keys:
                return self._keys[kid]
            may_refresh = (
                self._attempted_at is None or now - self._attempted_at >= self._min_refresh
            )
            if may_refresh:
                self._attempted_at = now
                try:
                    self._load(self._fetch())
                    self._loaded_at = now
                except JwksFetchError:
                    logger.warning("jwks refresh failed")
                    raise IdentityProviderUnavailable() from None
            if self._loaded_at is None or now - self._loaded_at >= self._ttl:
                raise IdentityProviderUnavailable()
            if kid in self._keys:
                return self._keys[kid]
            if not self._keys:
                raise IdentityProviderUnavailable()
            raise TokenInvalid(TokenRejection.UNKNOWN_KEY)

    def _load(self, document: Mapping[str, Any]) -> None:
        keys: dict[str, PyJWK] = {}
        for entry in document.get("keys", []):
            if not isinstance(entry, dict) or entry.get("use", "sig") != "sig":
                continue
            kid = entry.get("kid")
            if not isinstance(kid, str) or entry.get("kty") not in {"RSA", "EC"}:
                continue
            try:
                keys[kid] = PyJWK(entry)
            except PyJWKError:
                continue
        self._keys = keys


@dataclass(frozen=True, slots=True)
class VerifiedToken:
    """What the application takes from a valid access token. Nothing about tenants or roles."""

    subject: str
    session_id: str
    client_id: str
    issued_at: int
    expires_at: int
    auth_time: int | None
    acr: str | None
    email: str | None  # only for first-login provisioning (D08); never for authorization
    email_verified: bool | None
    second_factor_at: int | None = None  # when a second factor was last proven (``loa_map``)


def verify_signed(token: object, jwks: JwksCache, *, max_bytes: int) -> dict[str, Any]:
    """Check size, header and signature and return the claims. Nothing in the claims is
    trusted yet: every caller still checks issuer, audience, type and times."""
    if not isinstance(token, str) or not token:
        raise TokenInvalid(TokenRejection.MALFORMED)
    if len(token.encode("utf-8", "ignore")) > max_bytes:
        raise TokenInvalid(TokenRejection.TOO_LARGE)
    try:
        header = jwt.get_unverified_header(token)
    except (DecodeError, InvalidTokenError):
        raise TokenInvalid(TokenRejection.MALFORMED) from None
    algorithm = header.get("alg")
    if algorithm not in ALLOWED_ALGORITHMS:
        raise TokenInvalid(TokenRejection.ALGORITHM)
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise TokenInvalid(TokenRejection.UNKNOWN_KEY)
    key = jwks.key(kid)
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key.key,
            algorithms=[str(algorithm)],
            options={
                "verify_signature": True,
                "verify_exp": False,
                "verify_nbf": False,
                "verify_iat": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except (InvalidKeyError, jwt.InvalidSignatureError, TypeError, ValueError):
        # a key of the wrong type for the header algorithm fails here as well
        raise TokenInvalid(TokenRejection.SIGNATURE) from None
    except (DecodeError, InvalidTokenError):
        raise TokenInvalid(TokenRejection.MALFORMED) from None
    return claims


def _audiences(claims: Mapping[str, Any]) -> list[Any]:
    audience = claims.get("aud")
    if isinstance(audience, str):
        return [audience]
    return audience if isinstance(audience, list) else []


def _number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


class TokenValidator:
    def __init__(
        self,
        settings: AuthSettings,
        jwks: JwksCache,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._jwks = jwks
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: AuthSettings) -> TokenValidator:
        cache = JwksCache(
            http_jwks_fetcher(settings.jwks_endpoint, settings.jwks_timeout_seconds),
            ttl_seconds=settings.jwks_cache_seconds,
            min_refresh_seconds=settings.jwks_min_refresh_seconds,
        )
        return cls(settings, cache)

    def validate(self, token: object) -> VerifiedToken:
        try:
            return self._validate(token)
        except TokenInvalid as rejected:
            # Only the reason is logged; the token and its claims never are.
            logger.info("token rejected", extra={"fields": {"reason": rejected.reason.value}})
            raise

    def _validate(self, token: object) -> VerifiedToken:
        claims = verify_signed(token, self._jwks, max_bytes=self._settings.max_token_bytes)
        return self._check_claims(claims)

    def _check_claims(self, claims: Mapping[str, Any]) -> VerifiedToken:
        settings = self._settings
        if claims.get("iss") != settings.issuer:
            raise TokenInvalid(TokenRejection.ISSUER)
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        if not isinstance(audiences, list) or settings.audience not in audiences:
            raise TokenInvalid(TokenRejection.AUDIENCE)
        azp = claims.get("azp")
        if not isinstance(azp, str) or azp not in settings.authorized_parties:
            raise TokenInvalid(TokenRejection.AUTHORIZED_PARTY)
        if claims.get("typ") != "Bearer":
            raise TokenInvalid(TokenRejection.TOKEN_TYPE)
        subject, session_id = claims.get("sub"), claims.get("sid")
        if not isinstance(subject, str) or not subject:
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        if not isinstance(session_id, str) or not session_id:
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        exp, iat = claims.get("exp"), claims.get("iat")
        if not _is_number(exp) or not _is_number(iat):
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        now, leeway = self._clock(), settings.leeway_seconds
        if now >= float(exp) + leeway:
            raise TokenInvalid(TokenRejection.EXPIRED)
        nbf = claims.get("nbf")
        if nbf is not None and (not _is_number(nbf) or now + leeway < float(nbf)):
            raise TokenInvalid(TokenRejection.NOT_YET_VALID)
        if float(iat) > now + leeway:
            raise TokenInvalid(TokenRejection.NOT_YET_VALID)
        if float(exp) - float(iat) > settings.max_token_lifetime_seconds:
            raise TokenInvalid(TokenRejection.LIFETIME)
        auth_time, acr = claims.get("auth_time"), claims.get("acr")
        email, verified = claims.get("email"), claims.get("email_verified")
        return VerifiedToken(
            subject=subject,
            session_id=session_id,
            client_id=azp,
            issued_at=int(iat),
            expires_at=int(exp),
            auth_time=int(auth_time) if _is_number(auth_time) else None,
            acr=acr if isinstance(acr, str) else None,
            email=email if isinstance(email, str) else None,
            email_verified=verified if isinstance(verified, bool) else None,
            second_factor_at=_second_factor_time(claims.get(LOA_TIMES_CLAIM)),
        )


_is_number = _number


# The realm maps the provider's session note "loa-map" ({"<level>": <time of its last real
# authentication>}) into this claim. Level 2 is reached only by proving (or first setting up) a
# second factor. Neither single sign-on nor a token refresh moves the time (verified against
# Keycloak in tests/identity), unlike ``auth_time``, which a password-only sign-in renews.
LOA_TIMES_CLAIM = "loa_map"
_SECOND_FACTOR_LEVEL = "2"
_MAX_LOA_TIMES_LENGTH = 512


def _second_factor_time(value: object) -> int | None:
    """The level-two time of the ``loa_map`` claim, or ``None`` for anything unexpected."""
    if isinstance(value, str):
        if len(value) > _MAX_LOA_TIMES_LENGTH:
            return None
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            return None
    if not isinstance(value, dict):
        return None
    moment = value.get(_SECOND_FACTOR_LEVEL)
    if not isinstance(moment, int) or isinstance(moment, bool) or not 0 < moment < 10**11:
        return None
    return moment


@dataclass(frozen=True, slots=True)
class VerifiedIdToken:
    """The identity facts of a sign-in (web). The ID token is read once and then discarded."""

    subject: str
    session_id: str
    issued_at: int
    auth_time: int | None
    acr: str | None
    email: str | None
    email_verified: bool | None
    second_factor_at: int | None = None


class IdTokenValidator:
    """Validates the ID token of the authorization-code flow (D03): signature, issuer, audience
    equal to our client, token type, the nonce of this very flow, and times."""

    def __init__(
        self, settings: AuthSettings, jwks: JwksCache, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._settings, self._jwks, self._clock = settings, jwks, clock

    def validate(self, token: object, *, client_id: str, nonce: str) -> VerifiedIdToken:
        try:
            return self._validate(token, client_id, nonce)
        except TokenInvalid as rejected:
            logger.info("id token rejected", extra={"fields": {"reason": rejected.reason.value}})
            raise

    def _validate(self, token: object, client_id: str, nonce: str) -> VerifiedIdToken:
        settings = self._settings
        claims = verify_signed(token, self._jwks, max_bytes=settings.max_token_bytes)
        if claims.get("iss") != settings.issuer:
            raise TokenInvalid(TokenRejection.ISSUER)
        audiences = _audiences(claims)
        if client_id not in audiences:
            raise TokenInvalid(TokenRejection.AUDIENCE)
        azp = claims.get("azp")
        if (azp is not None or len(audiences) > 1) and azp != client_id:
            raise TokenInvalid(TokenRejection.AUTHORIZED_PARTY)
        if claims.get("typ") != "ID":
            raise TokenInvalid(TokenRejection.TOKEN_TYPE)
        given = claims.get("nonce")
        if not isinstance(given, str) or not hmac.compare_digest(given, nonce):
            raise TokenInvalid(TokenRejection.NONCE)
        subject, session_id = claims.get("sub"), claims.get("sid")
        if not isinstance(subject, str) or not subject:
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        if not isinstance(session_id, str) or not session_id:
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        exp, iat = claims.get("exp"), claims.get("iat")
        if not _is_number(exp) or not _is_number(iat):
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        now, leeway = self._clock(), settings.leeway_seconds
        if now >= float(exp) + leeway:
            raise TokenInvalid(TokenRejection.EXPIRED)
        if float(iat) > now + leeway:
            raise TokenInvalid(TokenRejection.NOT_YET_VALID)
        if float(exp) - float(iat) > settings.max_token_lifetime_seconds:
            raise TokenInvalid(TokenRejection.LIFETIME)
        auth_time, acr = claims.get("auth_time"), claims.get("acr")
        email, verified = claims.get("email"), claims.get("email_verified")
        return VerifiedIdToken(
            subject=subject,
            session_id=session_id,
            issued_at=int(iat),
            auth_time=int(auth_time) if _is_number(auth_time) else None,
            acr=acr if isinstance(acr, str) else None,
            email=email if isinstance(email, str) else None,
            email_verified=verified if isinstance(verified, bool) else None,
            second_factor_at=_second_factor_time(claims.get(LOA_TIMES_CLAIM)),
        )


BACKCHANNEL_EVENT = "http://schemas.openid.net/event/backchannel-logout"
_LOGOUT_MAX_AGE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class VerifiedLogout:
    subject: str
    session_id: str | None
    jti: str
    expires_at: int


class LogoutTokenValidator:
    """Validates an OpenID back-channel ``logout_token`` (OIDC Back-Channel Logout 1.0 sec. 2.6)."""

    def __init__(
        self, settings: AuthSettings, jwks: JwksCache, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._settings, self._jwks, self._clock = settings, jwks, clock

    def validate(self, token: object, *, client_id: str) -> VerifiedLogout:
        try:
            return self._validate(token, client_id)
        except TokenInvalid as rejected:
            logger.info(
                "logout token rejected", extra={"fields": {"reason": rejected.reason.value}}
            )
            raise

    def _validate(self, token: object, client_id: str) -> VerifiedLogout:
        settings = self._settings
        claims = verify_signed(token, self._jwks, max_bytes=settings.max_token_bytes)
        if claims.get("iss") != settings.issuer:
            raise TokenInvalid(TokenRejection.ISSUER)
        if client_id not in _audiences(claims):
            raise TokenInvalid(TokenRejection.AUDIENCE)
        if claims.get("typ") not in (None, "Logout", "secevent+jwt"):
            raise TokenInvalid(TokenRejection.TOKEN_TYPE)
        events = claims.get("events")
        if not isinstance(events, dict) or BACKCHANNEL_EVENT not in events:
            raise TokenInvalid(TokenRejection.EVENTS)
        if "nonce" in claims:  # a logout token must never be usable as an ID token
            raise TokenInvalid(TokenRejection.NONCE)
        jti, subject, session_id = claims.get("jti"), claims.get("sub"), claims.get("sid")
        if not isinstance(jti, str) or not jti or not isinstance(subject, str) or not subject:
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        if session_id is not None and (not isinstance(session_id, str) or not session_id):
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        iat, exp = claims.get("iat"), claims.get("exp")
        if not _is_number(iat):
            raise TokenInvalid(TokenRejection.MISSING_CLAIM)
        now, leeway = self._clock(), settings.leeway_seconds
        if float(iat) > now + leeway:
            raise TokenInvalid(TokenRejection.NOT_YET_VALID)
        if now - float(iat) > _LOGOUT_MAX_AGE_SECONDS + leeway:
            raise TokenInvalid(TokenRejection.EXPIRED)
        if exp is not None and (not _is_number(exp) or now >= float(exp) + leeway):
            raise TokenInvalid(TokenRejection.EXPIRED)
        return VerifiedLogout(
            subject=subject,
            session_id=session_id,
            jti=jti,
            expires_at=int(exp) if _is_number(exp) else int(iat) + _LOGOUT_MAX_AGE_SECONDS,
        )
