"""Port to the identity provider's admin operations (F2-T02, completed in F2-T09). Keeping it a
port lets tests use a fake and keeps the application free of Keycloak types."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class IdpAdminError(Exception):
    """The identity provider's admin API failed. The message never carries a response body."""


class IdpConflict(IdpAdminError):
    """The provider refused a conflicting identity update."""


@dataclass(frozen=True, slots=True, repr=False)
class IdpEmailState:
    subject: str
    email: str
    username: str
    email_verified: bool


@dataclass(frozen=True, slots=True)
class IdpUser:
    subject: str
    enabled: bool
    email_verified: bool


@dataclass(frozen=True, slots=True)
class IdpCredential:
    """A credential of a person as the provider lists it (never the secret itself)."""

    id: str
    type: str  # password | otp | webauthn | webauthn-passwordless | recovery-authn-codes
    created_ms: int | None


# A permanent factor can be used again and again; recovery codes are its backup and run out.
PERMANENT_FACTOR_TYPES = frozenset({"otp", "webauthn", "webauthn-passwordless"})
RECOVERY_CODES_TYPE = "recovery-authn-codes"
SECOND_FACTOR_TYPES = PERMANENT_FACTOR_TYPES | {RECOVERY_CODES_TYPE}

# Realm attribute of an account that once used a second factor and may never fall back to the
# password alone (set by an operator; only administrators can see or change it).
FACTOR_OBLIGATION_ATTRIBUTE = "at_mfa_required"

# Pending provider actions that create or remove a sign-in credential.
CREDENTIAL_SETUP_ACTIONS = frozenset(
    {
        "CONFIGURE_TOTP",
        "CONFIGURE_RECOVERY_AUTHN_CODES",
        "webauthn-register",
        "webauthn-register-passwordless",
        "delete_credential",
    }
)


class IdentityProviderAdmin(Protocol):
    """Least-privilege operations the application needs from the identity provider."""

    def find_user_by_email(self, email: str) -> IdpUser | None: ...

    def get_email_state(self, subject: str) -> IdpEmailState: ...

    def set_verified_email(self, subject: str, email: str) -> None: ...

    def set_user_enabled(self, subject: str, *, enabled: bool) -> None: ...

    def logout_user_sessions(self, subject: str) -> None: ...

    def send_actions_email(
        self,
        subject: str,
        actions: Sequence[str],
        *,
        lifespan_seconds: int,
        redirect_uri: str,
    ) -> None: ...

    def list_credentials(self, subject: str) -> list[IdpCredential]: ...

    def delete_credential(self, subject: str, credential_id: str) -> None: ...

    def clear_pending_credential_setups(self, subject: str) -> None:
        """Withdraw every pending action that would create or remove a sign-in credential. The
        provider runs pending actions for whoever opens one of its e-mail links, without
        asking for any factor."""
        ...

    def has_factor_obligation(self, subject: str) -> bool: ...
