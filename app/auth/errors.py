"""Authentication errors (F2-T02). The client sees only a stable code; the precise rejection
reason is kept on the exception for logs and tests and never echoed in the response."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from app.core.errors import (
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    Unauthenticated,
)


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
    NONCE = "nonce"
    EVENTS = "events"
    REPLAY = "replay"


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


class LastPermanentFactor(Conflict):
    """409 LAST_PERMANENT_FACTOR: removing it would leave recovery codes without a factor they
    back up, or an account that must keep a second factor without one."""

    code = "LAST_PERMANENT_FACTOR"
    title = "The last permanent second factor cannot be removed"


class AccountDisabled(Forbidden):
    """403 ACCOUNT_DISABLED, only ever returned after the person authenticated successfully."""

    code = "ACCOUNT_DISABLED"
    title = "Account disabled"


class EmailNotVerified(Forbidden):
    code = "EMAIL_NOT_VERIFIED"
    title = "E-mail address not verified"


class SessionRequired(Unauthenticated):
    """401 SESSION_REQUIRED: no application session matches the credential presented."""

    code = "SESSION_REQUIRED"
    title = "Session required"


class SessionExpired(Unauthenticated):
    code = "SESSION_EXPIRED"
    title = "Session expired"


class SessionRevoked(Unauthenticated):
    code = "SESSION_REVOKED"
    title = "Session revoked"


class SessionSecurityViolation(SessionRevoked):
    """The session must be revoked: the caller revokes it in its own transaction after the
    failed request has rolled back (``revoke_independent``)."""

    def __init__(self, session_id: UUID, user_id: UUID, signal: str) -> None:
        super().__init__()
        self.session_id = session_id
        self.user_id = user_id
        self.signal = signal


class AuthCallbackRejected(BadRequest):
    """400 AUTH_CALLBACK_REJECTED: the sign-in return was refused. One generic answer for every
    cause (state, binding, code, token); the cause goes to the audit log only."""

    code = "AUTH_CALLBACK_REJECTED"
    title = "Sign-in could not be completed"


class CsrfInvalid(Forbidden):
    code = "CSRF_INVALID"
    title = "Request could not be verified"


class AmbiguousCredentials(BadRequest):
    code = "AMBIGUOUS_CREDENTIALS"
    title = "Send either a session cookie or a bearer token, not both"


class AuthRequired(Unauthenticated):
    code = "AUTH_REQUIRED"
    title = "Authentication required"


class AuthNotConfigured(ServiceUnavailable):
    code = "AUTH_NOT_CONFIGURED"
    title = "Authentication is not configured"


class LogoutTokenInvalid(BadRequest):
    code = "LOGOUT_TOKEN_INVALID"
    title = "Invalid logout token"


class StepUpRequired(Unauthenticated):
    """401 STEP_UP_REQUIRED with the RFC 9470 challenge (D23)."""

    code = "STEP_UP_REQUIRED"
    title = "Stronger or fresher authentication required"

    def __init__(self, *, acr_values: str, max_age: int) -> None:
        challenge = (
            'Bearer error="insufficient_user_authentication", '
            f'error_description="A different authentication level is required", '
            f'acr_values="{acr_values}", max_age="{max_age}"'
        )
        super().__init__(headers={"WWW-Authenticate": challenge})


class WorkspaceRequired(Forbidden):
    """403 WORKSPACE_REQUIRED: the route needs an active tenant context and the session has none
    (or the person's access to it has ended since)."""

    code = "WORKSPACE_REQUIRED"
    title = "An active workspace is required"


class WorkspaceNotFound(NotFound):
    """404 WORKSPACE_NOT_FOUND: no such workspace *for this person*. An unknown tenant and a
    tenant the person has no access to look exactly the same (AT-03 decision 5)."""

    code = "WORKSPACE_NOT_FOUND"
    title = "Workspace not found"


class AuthorizationUnavailable(ServiceUnavailable):
    """503 AUTHORIZATION_UNAVAILABLE: membership could not be checked; the request is refused
    (fail closed), never guessed."""

    code = "AUTHORIZATION_UNAVAILABLE"
    title = "Authorization is temporarily unavailable"

    def __init__(self) -> None:
        super().__init__(headers={"Retry-After": "5"})
