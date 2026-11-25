"""Test doubles for the identity provider's admin API and the notice sender (F2-T09)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.auth.idp import (
    CREDENTIAL_SETUP_ACTIONS,
    IdpAdminError,
    IdpConflict,
    IdpCredential,
    IdpEmailState,
    IdpUser,
)
from app.auth.security.notify import Notice


@dataclass
class FakeAdmin:
    users: dict[str, IdpUser] = field(default_factory=dict)  # by normalised e-mail
    credentials: dict[str, list[IdpCredential]] = field(default_factory=dict)  # by subject
    sent: list[tuple[str, tuple[str, ...], int, str]] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    deleted: list[tuple[str, str]] = field(default_factory=list)
    pending: dict[str, list[str]] = field(default_factory=dict)  # pending provider actions
    obliged: set[str] = field(default_factory=set)  # subjects that must keep a second factor
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

    def get_email_state(self, subject: str) -> IdpEmailState:
        self._check("email_state")
        for address, user in self.users.items():
            if user.subject == subject:
                return IdpEmailState(subject, address, address, user.email_verified)
        raise IdpAdminError("missing user")

    def set_verified_email(self, subject: str, email: str) -> None:
        self._check("set_email")
        old = next(
            (address for address, user in self.users.items() if user.subject == subject), None
        )
        if old is None:
            raise IdpAdminError("identity update refused")
        if email in self.users and self.users[email].subject != subject:
            raise IdpConflict("identity update conflicts")
        user = self.users.pop(old)
        self.users[email] = IdpUser(subject, user.enabled, True)

    def set_user_enabled(self, subject: str, *, enabled: bool) -> None:
        self._check("enable")

    def logout_user_sessions(self, subject: str) -> None:
        self._check("logout")

    def send_actions_email(
        self, subject: str, actions: Sequence[str], *, lifespan_seconds: int, redirect_uri: str
    ) -> None:
        self.clear_pending_credential_setups(subject)  # as the real client does
        self._check("email")
        self.sent.append((subject, tuple(actions), lifespan_seconds, redirect_uri))

    def list_credentials(self, subject: str) -> list[IdpCredential]:
        self._check("credentials")
        return list(self.credentials.get(subject, []))

    def delete_credential(self, subject: str, credential_id: str) -> None:
        self._check("delete")
        self.deleted.append((subject, credential_id))
        self.credentials[subject] = [c for c in self.credentials[subject] if c.id != credential_id]

    def clear_pending_credential_setups(self, subject: str) -> None:
        self._check("clear_pending")
        if subject in self.pending:
            self.pending[subject] = [
                a for a in self.pending[subject] if a not in CREDENTIAL_SETUP_ACTIONS
            ]

    def has_factor_obligation(self, subject: str) -> bool:
        self._check("obligation")
        return subject in self.obliged


@dataclass
class RecordingNotifier:
    notices: list[Notice] = field(default_factory=list)

    def send(self, notice: Notice) -> None:
        self.notices.append(notice)
