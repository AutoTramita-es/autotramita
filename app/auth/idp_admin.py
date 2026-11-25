"""Keycloak admin REST client (F2-T09). It signs in as the least-privilege service account
(``manage-users``, ``view-users``, ``view-events``), caches the short-lived token and never
logs a secret, a token or a response body."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import quote

import httpx
from app.auth.idp import (
    CREDENTIAL_SETUP_ACTIONS,
    FACTOR_OBLIGATION_ATTRIBUTE,
    IdpAdminError,
    IdpConflict,
    IdpCredential,
    IdpEmailState,
    IdpUser,
)
from app.auth.settings import AuthSettings

log = logging.getLogger(__name__)
_REFRESH_MARGIN_SECONDS = 20


class KeycloakAdmin:
    def __init__(
        self,
        settings: AuthSettings,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        secret = settings.admin_client_secret
        if secret is None:
            raise IdpAdminError("admin client is not configured")
        self._settings = settings
        self._secret = secret
        self._http = client or httpx.Client(timeout=settings.admin_timeout_seconds)
        self._clock = clock
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires = 0.0

    def close(self) -> None:
        self._http.close()

    # --- plumbing ---------------------------------------------------------------------------
    def _bearer(self) -> str:
        with self._lock:
            if self._token and self._clock() < self._expires:
                return self._token
            try:
                response = self._http.post(
                    f"{self._settings.issuer}/protocol/openid-connect/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self._settings.admin_client_id,
                        "client_secret": self._secret.get_secret_value(),
                    },
                )
                response.raise_for_status()
                body = response.json()
                token, lifetime = str(body["access_token"]), int(body.get("expires_in", 60))
            except (httpx.HTTPError, ValueError, KeyError):
                raise IdpAdminError("admin token request failed") from None
            self._token = token
            self._expires = self._clock() + max(lifetime - _REFRESH_MARGIN_SECONDS, 1)
            return token

    def _call(
        self, method: str, path: str, *, ok: tuple[int, ...] = (200, 204), **kwargs: Any
    ) -> httpx.Response:
        try:
            response = self._http.request(
                method,
                f"{self._settings.admin_base_url}{path}",
                headers={"Authorization": f"Bearer {self._bearer()}"},
                **kwargs,
            )
        except httpx.HTTPError:
            raise IdpAdminError("admin request failed") from None
        if response.status_code == 409:
            raise IdpConflict("identity update conflicts")
        if response.status_code not in ok:
            log.warning(
                "identity admin call refused",
                extra={"fields": {"method": method, "status": response.status_code}},
            )
            raise IdpAdminError(f"admin request refused ({response.status_code})")
        return response

    @staticmethod
    def _id(subject: str) -> str:
        return quote(subject, safe="")

    # --- port -------------------------------------------------------------------------------
    def find_user_by_email(self, email: str) -> IdpUser | None:
        found = self._call("GET", "/users", params={"email": email, "exact": "true", "max": 2})
        users: list[dict[str, Any]] = found.json()
        exact = [u for u in users if str(u.get("email", "")).lower() == email.lower()]
        if len(exact) != 1:
            return None  # none, or an ambiguous answer: treated as "no such account"
        user = exact[0]
        return IdpUser(
            subject=str(user["id"]),
            enabled=bool(user.get("enabled", False)),
            email_verified=bool(user.get("emailVerified", False)),
        )

    def get_email_state(self, subject: str) -> IdpEmailState:
        response = self._call("GET", f"/users/{self._id(subject)}")
        try:
            user = response.json()
            if (
                not isinstance(user, dict)
                or user.get("id") != subject
                or not isinstance(user.get("email"), str)
                or not isinstance(user.get("username"), str)
                or not isinstance(user.get("emailVerified"), bool)
            ):
                raise ValueError("invalid response")
            return IdpEmailState(subject, user["email"], user["username"], user["emailVerified"])
        except (ValueError, KeyError, TypeError):
            raise IdpAdminError("invalid identity state") from None

    def set_verified_email(self, subject: str, email: str) -> None:
        self._call(
            "PUT",
            f"/users/{self._id(subject)}",
            json={"email": email, "username": email, "emailVerified": True},
        )

    def set_user_enabled(self, subject: str, *, enabled: bool) -> None:
        self._call("PUT", f"/users/{self._id(subject)}", json={"enabled": enabled})

    def logout_user_sessions(self, subject: str) -> None:
        self._call("POST", f"/users/{self._id(subject)}/logout")

    def send_actions_email(
        self,
        subject: str,
        actions: Sequence[str],
        *,
        lifespan_seconds: int,
        redirect_uri: str,
    ) -> None:
        # The link runs every pending action, not only those named here, and asks for no factor.
        self.clear_pending_credential_setups(subject)
        self._call(
            "PUT",
            f"/users/{self._id(subject)}/execute-actions-email",
            params={
                "lifespan": lifespan_seconds,
                "redirect_uri": redirect_uri,
                "client_id": self._settings.web_client_id,
            },
            json=list(actions),
        )

    def list_credentials(self, subject: str) -> list[IdpCredential]:
        rows: list[dict[str, Any]] = self._call(
            "GET", f"/users/{self._id(subject)}/credentials"
        ).json()
        return [
            IdpCredential(
                id=str(row["id"]),
                type=str(row.get("type", "")),
                created_ms=int(row["createdDate"]) if row.get("createdDate") is not None else None,
            )
            for row in rows
        ]

    def delete_credential(self, subject: str, credential_id: str) -> None:
        self._call("DELETE", f"/users/{self._id(subject)}/credentials/{self._id(credential_id)}")

    def clear_pending_credential_setups(self, subject: str) -> None:
        user = self._user(subject)
        pending = user.get("requiredActions", [])
        if not isinstance(pending, list):
            raise IdpAdminError("invalid identity state")
        kept = [action for action in pending if action not in CREDENTIAL_SETUP_ACTIONS]
        if kept != pending:
            self._call("PUT", f"/users/{self._id(subject)}", json={"requiredActions": kept})

    def has_factor_obligation(self, subject: str) -> bool:
        attributes = self._user(subject).get("attributes") or {}
        if not isinstance(attributes, dict):
            raise IdpAdminError("invalid identity state")
        return attributes.get(FACTOR_OBLIGATION_ATTRIBUTE) == ["true"]

    def _user(self, subject: str) -> dict[str, Any]:
        try:
            user = self._call("GET", f"/users/{self._id(subject)}").json()
        except ValueError:
            raise IdpAdminError("invalid identity state") from None
        if not isinstance(user, dict) or user.get("id") != subject:
            raise IdpAdminError("invalid identity state")
        return user
