"""Port to the identity provider's admin operations (F2-T02). Interface only: the Keycloak
implementation arrives with T09/T11. Keeping it a port lets tests use a fake and keeps the
application free of Keycloak types."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class IdentityProviderAdmin(Protocol):
    """Least-privilege operations the application needs from the identity provider."""

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
