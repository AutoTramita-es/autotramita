"""Authentication errors (F2-T02). The client sees only a stable code; the precise rejection
reason is kept on the exception for logs and tests and never echoed in the response."""

from __future__ import annotations

from enum import StrEnum

from app.core.errors import Conflict, Forbidden, ServiceUnavailable, Unauthenticated


class TokenRejection(StrEnum):
    MALFORMED = "malformed"
    TOO_LARGE = "too_large"
    ALGORITHM = "algorithm"
    UNKNOWN_KEY = "unknown_key"
    SIGNATURE = "signature"
    ISSUER = "issuer"
    AUDIENCE = "audience"
    AUTHORIZED_PARTY = "authorized_party"
    TOKEN_TYPE = "token_type"  # noqa: S105 - a rejection reason, not a password
    MISSING_CLAIM = "missing_claim"
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    LIFETIME = "lifetime"


class TokenInvalid(Unauthenticated):
    """401 AUTH_TOKEN_INVALID. Generic on purpose: no hint which check failed."""

    code = "AUTH_TOKEN_INVALID"
    title = "Invalid or expired token"

    def __init__(self, reason: TokenRejection) -> None:
        super().__init__(headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
        self.reason = reason


class IdentityProviderUnavailable(ServiceUnavailable):
    """503 IDENTITY_PROVIDER_UNAVAILABLE: fail closed when signing keys cannot be obtained."""

    code = "IDENTITY_PROVIDER_UNAVAILABLE"
    title = "Identity provider unavailable"

    def __init__(self) -> None:
        super().__init__(headers={"Retry-After": "5"})


class AccountConflict(Conflict):
    """409 ACCOUNT_CONFLICT: the e-mail already belongs to another identity (D09). Generic on
    purpose: it must not reveal whose account it is."""

    code = "ACCOUNT_CONFLICT"
    title = "Account conflict"


class InvalidStatusTransition(Conflict):
    code = "INVALID_STATUS_TRANSITION"
    title = "Status change not allowed"


class AccountDisabled(Forbidden):
    """403 ACCOUNT_DISABLED, only ever returned after the person authenticated successfully."""

    code = "ACCOUNT_DISABLED"
    title = "Account disabled"


class EmailNotVerified(Forbidden):
    code = "EMAIL_NOT_VERIFIED"
    title = "E-mail address not verified"
