"""Harness of the platform-grant API tests (F2-T10): the real application on real PostgreSQL 16
and Redis 7, the platform database role, a fake identity provider and a fake admin API."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from app.auth.idp import IdpCredential
from app.auth.web.csrf import csrf_token
from app.core.db import create_session_factory
from app.platform.bootstrap import Bootstrapped, bootstrap_platform_admin
from fastapi.testclient import TestClient
from tests.auth.fake_admin import FakeAdmin, RecordingNotifier
from tests.auth.web_harness import ORIGIN_WEB, SESSION_COOKIE, Web
from tests.conftest import RoleEnv

API = "/api/v1"
GRANTS = f"{API}/platform/grants"


def secure(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token(client.cookies[SESSION_COOKIE]), "Origin": ORIGIN_WEB}


def problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code, response.text


def evidence(factor_age: int | None, auth_age: int = 5) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {"auth_time": now - auth_age, "iat": now - 1, "exp": now + 290}
    if factor_age is None:
        return {**claims, "acr": "loa1"}
    return {
        **claims,
        "acr": "loa2",
        "loa_map": json.dumps({"1": now - auth_age, "2": now - factor_age}),
    }


@dataclass
class Person:
    sub: str
    email: str
    id: uuid.UUID


class PlatformRig:
    def __init__(
        self, env: RoleEnv, web: Web, admin: FakeAdmin, notifier: RecordingNotifier
    ) -> None:
        self.env, self.web, self.admin, self.notifier = env, web, admin, notifier

    # --- people -----------------------------------------------------------------------------
    def person(self, name: str | None = None, *, factor: str | None = "otp") -> Person:
        sub = f"sub-{name or uuid.uuid4().hex[:8]}-{uuid.uuid4().hex[:6]}"
        email = f"{sub}@example.test"
        self.admin.add(email, sub)
        credentials = [IdpCredential(f"{sub}-pw", "password", 1)]
        if factor is not None:
            credentials.append(IdpCredential(f"{sub}-2f", factor, 2))
        self.admin.credentials[sub] = credentials
        client = self.login(sub, email, factor_age=None)  # first sign-in provisions the account
        client.close()
        row = self.web.rows("SELECT id FROM users WHERE auth_subject = :s", s=sub)
        return Person(sub, email, row[0][0])

    def login(self, sub: str, email: str, factor_age: int | None = 5, **kw: Any) -> TestClient:
        client = self.web.client(**kw)
        response = self.web.sign_in(
            client, sub=sub, email=email, sid=f"sid-{time.time_ns()}", **evidence(factor_age)
        )
        assert response.status_code == 302, response.text
        return client

    def signed_in(self, who: Person, factor_age: int | None = 5) -> TestClient:
        return self.login(who.sub, who.email, factor_age)

    def bootstrap(self, who: Person) -> Bootstrapped:
        return bootstrap_platform_admin(
            create_session_factory(self.env.engine("owner")),
            self.admin,
            email=who.email,
            environment="test",
            now=datetime.now(UTC),
        )

    def administrator(self, name: str | None = None) -> tuple[Person, TestClient]:
        who = self.person(name)
        self.bootstrap(who)
        return who, self.signed_in(who)

    # --- requests ---------------------------------------------------------------------------
    def request(
        self,
        client: TestClient,
        user: Person | uuid.UUID,
        grant_type: str,
        *,
        days: float = 30,
        **extra: Any,
    ) -> httpx.Response:
        body: dict[str, Any] = {
            "user_id": str(user.id if isinstance(user, Person) else user),
            "grant_type": grant_type,
            "expires_at": (datetime.now(UTC) + timedelta(days=days)).isoformat(),
            "reason": "needed for the support rota",
            **extra,
        }
        response: httpx.Response = client.post(GRANTS, json=body, headers=secure(client))
        return response

    def decide(
        self, client: TestClient, grant_id: str, action: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        response: httpx.Response = client.post(
            f"{GRANTS}/{grant_id}/{action}", json=body or {}, headers=secure(client)
        )
        return response

    def revoke(
        self, client: TestClient, grant_id: str, reason: str = "NO_LONGER_NEEDED"
    ) -> httpx.Response:
        return self.decide(client, grant_id, "revoke", {"reason": reason})

    def audit(self, action: str) -> list[tuple[Any, ...]]:
        return self.web.rows(
            "SELECT outcome, actor_type, actor_user_id, subject_user_id, target_id, details "
            "FROM audit_events WHERE action = :a ORDER BY occurred_at, id",
            a=action,
        )

    def grant_row(self, grant_id: str) -> tuple[Any, ...]:
        return self.web.rows(
            "SELECT status, approved_by, revoke_reason FROM platform_grants WHERE id = :g",
            g=grant_id,
        )[0]
