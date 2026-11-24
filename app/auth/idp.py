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


SECOND_FACTOR_TYPES = frozenset(
    {"otp", "webauthn", "webauthn-passwordless", "recovery-authn-codes"}
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
