"""AC-AUD-08 within T01-T09: refused attempts leave a record without tokens, addresses or the
identifiers the client sent. Real PostgreSQL 16 and Redis 7, fake identity provider."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from app.api.v1 import authn
from app.auth.web.csrf import csrf_token
from sqlalchemy.exc import OperationalError
from tests.auth.context.test_workspace_pipeline import Rig as WorkspaceRig
from tests.auth.context.test_workspace_pipeline import owner_sql
from tests.auth.web_harness import ORIGIN_WEB, SESSION_COOKIE, Web, build_web
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

pytest_plugins = ["tests.auth.context.test_workspace_pipeline"]
API = "/api/v1"


@pytest.fixture
def web(role_env: RoleEnv, redis_url: str) -> Iterator[Web]:
    migrate(role_env.engine("owner"), "upgrade", "head")
    harness = build_web(role_env, redis_url)
    yield harness
    harness.close()


def records(web: Web, action: str) -> list[tuple[Any, ...]]:
    return web.rows(
        "SELECT outcome, actor_type, details, actor_user_id IS NOT NULL, "
        "row_to_json(a)::text FROM audit_events a WHERE action = :a ORDER BY occurred_at",
        a=action,
    )


@pytest.mark.parametrize(
    ("claims", "reason"),
    [
        ({"aud": "somebody-else"}, "audience"),
        ({"azp": "at-web"}, "authorized_party"),
        ({"typ": "ID"}, "token_type"),
        ({"exp": 1}, "expired"),
    ],
)
def test_a_refused_bearer_token_is_recorded_by_its_reason_only(
    web: Web, claims: dict[str, Any], reason: str
) -> None:
    token = web.access(**claims)
    client = web.bearer(token)
    for response in (
        client.get(f"{API}/auth/session"),
        client.post(f"{API}/auth/mobile/session", json={}),
    ):
        assert response.status_code == 401 and response.json()["code"] == "AUTH_TOKEN_INVALID"
    found = records(web, "auth.token.invalid")
    assert [r[:4] for r in found] == [("DENIED", "ANONYMOUS", {"reason": reason}, False)] * 2
    for _, _, _, _, row in found:
        assert token not in row and token.split(".")[1] not in row and "person@" not in row


def test_a_malformed_token_is_recorded_too(web: Web) -> None:
    assert web.bearer("not-a-token").get(f"{API}/auth/session").status_code == 401
    assert [r[2] for r in records(web, "auth.token.invalid")] == [{"reason": "malformed"}]


def test_the_refusal_stands_when_the_audit_store_cannot_take_the_record(
    web: Web, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(*args: Any, **kwargs: Any) -> bool:
        raise OperationalError("insert", {}, RuntimeError("down"))

    monkeypatch.setattr(authn, "record_independent", broken)
    caplog.set_level(logging.WARNING)
    token = web.access(aud="somebody-else")
    response = web.bearer(token).get(f"{API}/auth/session")
    assert response.status_code == 401 and response.json()["code"] == "AUTH_TOKEN_INVALID"
    assert "a refused attempt could not be recorded" in caplog.text and token not in caplog.text


def secure(client: Any) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token(client.cookies[SESSION_COOKIE]), "Origin": ORIGIN_WEB}


def test_a_refused_workspace_switch_is_recorded_without_the_requested_tenant(
    rig: WorkspaceRig,
) -> None:
    client = rig.login("a")
    asked = str(uuid.uuid4())
    refused = client.post(
        f"{API}/sessions/workspace",
        headers={**secure(client), "If-Match": '"1"'},
        json={"tenant_id": asked},
    )
    assert refused.status_code == 404 and refused.json()["code"] == "WORKSPACE_NOT_FOUND"
    found = records(rig.web, "authz.denied")
    assert [r[:4] for r in found] == [
        ("DENIED", "USER", {"reason": "WORKSPACE", "resource_type": "workspace"}, True)
    ]
    assert asked not in found[0][4]


def test_using_a_workspace_after_the_membership_ended_is_recorded(rig: WorkspaceRig) -> None:
    client = rig.login("a")
    assert client.get(f"{API}/probe/customers").status_code == 403  # nothing selected yet
    assert records(rig.web, "authz.denied") == []  # not having selected one is not an attempt
    assert rig.select(client, rig.probe.tenant_b).status_code == 200
    owner_sql(
        rig,
        "DELETE FROM rls_memberships WHERE tenant_id = :t AND user_id = :u",
        user=rig.probe.user_a,
        tenant=rig.probe.tenant_b,
        t=rig.probe.tenant_b,
        u=rig.probe.user_a,
    )
    assert client.get(f"{API}/probe/customers").status_code == 403
    found = records(rig.web, "authz.denied")
    assert [r[:3] for r in found] == [
        ("DENIED", "USER", {"reason": "WORKSPACE", "resource_type": "workspace"})
    ]
    assert str(rig.probe.tenant_b) not in found[0][4]
