"""Test doubles for the identity provider's admin API and the notice sender (F2-T09)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.auth.idp import IdpAdminError, IdpCredential, IdpUser
from app.auth.security.notify import Notice


@dataclass
class FakeAdmin:
    users: dict[str, IdpUser] = field(default_factory=dict)  # by normalised e-mail
    credentials: dict[str, list[IdpCredential]] = field(default_factory=dict)  # by subject
    sent: list[tuple[str, tuple[str, ...], int, str]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    deleted: list[tuple[str, str]] = field(default_factory=list)
    down: bool = False

    def add(self, email: str, subject: str, *, enabled: bool = True, verified: bool = True) -> None:
        self.users[email] = IdpUser(subject, enabled, verified)

    def _check(self, call: str) -> None:
        self.calls.append(call)
        if self.down:
            raise IdpAdminError("down")

    def find_user_by_email(self, email: str) -> IdpUser | None:
        self._check("find")
        return self.users.get(email)

    def set_user_enabled(self, subject: str, *, enabled: bool) -> None:
        self._check("enable")

    def logout_user_sessions(self, subject: str) -> None:
        self._check("logout")

    def send_actions_email(
        self, subject: str, actions: Sequence[str], *, lifespan_seconds: int, redirect_uri: str
    ) -> None:
        self._check("email")
        self.sent.append((subject, tuple(actions), lifespan_seconds, redirect_uri))

    def list_credentials(self, subject: str) -> list[IdpCredential]:
        self._check("credentials")
        return list(self.credentials.get(subject, []))

    def delete_credential(self, subject: str, credential_id: str) -> None:
        self._check("delete")
        self.deleted.append((subject, credential_id))
        self.credentials[subject] = [c for c in self.credentials[subject] if c.id != credential_id]


@dataclass
class RecordingNotifier:
    notices: list[Notice] = field(default_factory=list)

    def send(self, notice: Notice) -> None:
        self.notices.append(notice)
