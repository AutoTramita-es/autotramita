"""F2-T08 / AC-CTX-04..12, AC-AUTHZ-01..03: the request pipeline, workspaces and the AT-03
boundary on real PostgreSQL 16 and Redis 7. Memberships come from the F1 RLS probe tables
through a test authorizer; production wiring denies everything."""

import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from app.api.app import create_app
from app.api.v1.guards import AccessKind, iter_access
from app.auth.membership import DenyAllAuthorizer
from app.auth.runtime import AuthRuntime
from app.auth.settings import AuthSettings
from app.auth.web.csrf import csrf_token
from app.core.ratelimit import create_redis
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.auth.fake_idp import ISSUER
from tests.auth.fake_membership import (
    BrokenAuthorizer,
    InconsistentAuthorizer,
    ProbeAuthorizer,
    branches_of,
)
from tests.auth.probe_routes import router as probe_router
from tests.auth.web_harness import ORIGIN_WEB, SESSION_COOKIE, Web, build_web
from tests.conftest import RoleEnv
from tests.rls_probe import Probe, build_probe

API = "/api/v1"
ROOT = Path(__file__).resolve().parents[3]


class Rig:
    def __init__(self, web: Web, probe: Probe) -> None:
        self.web, self.probe = web, probe

    def user(self, key: str) -> tuple[uuid.UUID, str, str]:
        return {
            "a": (self.probe.user_a, "sub-a", "a@example.test"),
            "b": (self.probe.user_b, "sub-b", "b@example.test"),
        }[key]

    def login(self, who: str, sid: str | None = None, **kw: Any) -> TestClient:
        _, sub, email = self.user(who)
        client = self.web.client()
        response = self.web.sign_in(client, sub=sub, email=email, sid=sid or f"sid-{who}", **kw)
        assert response.status_code == 302, response.text
        return client

    def select(
        self,
        client: TestClient,
        tenant: uuid.UUID,
        branch: uuid.UUID | None = None,
        version: int | None = None,
    ) -> httpx.Response:
        if version is None:
            version = int(client.get(f"{API}/auth/session").headers["etag"].strip('"'))
        body: dict[str, Any] = {"tenant_id": str(tenant)}
        if branch:
            body["branch_id"] = str(branch)
        response: httpx.Response = client.post(
            f"{API}/sessions/workspace",
            json=body,
            headers={**secure(client), "If-Match": f'"{version}"'},
        )
        return response


def secure(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token(client.cookies[SESSION_COOKIE]), "Origin": ORIGIN_WEB}


def problem(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


@pytest.fixture
def rig(role_env: RoleEnv, redis_url: str) -> Iterator[Rig]:
    probe = build_probe(role_env)  # migrates to head, creates and seeds the probe tables
    web = build_web(role_env, redis_url)
    web.runtime.membership = ProbeAuthorizer()
    web.app.include_router(probe_router, prefix=API)
    with role_env.admin_engine().connect() as c:
        for uid, sub, email in (
            (probe.user_a, "sub-a", "a@example.test"),
            (probe.user_b, "sub-b", "b@example.test"),
        ):
            c.execute(
                text(
                    "INSERT INTO users (id, auth_subject, email, email_normalized, status, email_verified_at) "
                    "VALUES (:i, :s, :e, :e, 'ACTIVE', now())"
                ),
                {"i": uid, "s": sub, "e": email},
            )
    yield Rig(web, probe)
    web.close()


def owner_sql(
    rig: Rig,
    sql: str,
    user: uuid.UUID | None = None,
    tenant: uuid.UUID | None = None,
    **params: Any,
) -> None:
    """Change memberships the way an AT-03 module would (as the owner role, inside a context)."""
    from app.core.db import RequestContext, session_scope

    with session_scope(
        rig.web.env.engine("owner"), RequestContext(user_id=user, tenant_id=tenant)
    ) as s:
        s.execute(text(sql), params)


# --- AC-CTX-04 the client names a workspace, the server decides ----------------------------------------------
def test_a_selected_workspace_scopes_every_request_and_client_hints_are_ignored(rig: Rig) -> None:
    client = rig.login("a")
    tenant_a, tenant_b = rig.probe.tenant_a, rig.probe.tenant_b
    problem(client.get(f"{API}/probe/customers"), 403, "WORKSPACE_REQUIRED")  # nothing selected yet
    selected = rig.select(client, tenant_a)
    assert selected.status_code == 200, selected.text
    seen = client.get(
        f"{API}/probe/customers",
        params={"tenant_id": str(tenant_b)},
        headers={"X-Tenant-ID": str(tenant_b), "X-Branch-ID": str(branches_of(tenant_b)[0])},
    )
    body = seen.json()
    assert seen.status_code == 200 and body["tenant"] == str(tenant_a) and body["names"] == ["c"]
    assert body["joined"] == 1 and body["branch"] == str(branches_of(tenant_a)[0])
    # only the selected branch is visible to row policies; bootstrap values never reach business queries
    assert body["settings"] == [str(tenant_a), str(branches_of(tenant_a)[0]), "", ""]
    created = client.post(
        f"{API}/probe/customers",
        json={"name": "mine", "tenant_id": str(tenant_b)},
        headers=secure(client),
    )
    assert created.json() == {"tenant": str(tenant_a)}  # the body's tenant is ignored
    assert rig.web.rows("SELECT name, tenant_id FROM rls_customers WHERE name = 'mine'") == [
        ("mine", tenant_a)
    ]
    assert client.get(f"{API}/probe/customers").json()["names"] == ["c", "mine"]


def test_the_database_refuses_a_forged_tenant_even_inside_a_valid_scope(rig: Rig) -> None:
    client = rig.login("a")
    rig.select(client, rig.probe.tenant_a)
    forged = client.post(
        f"{API}/probe/forge",
        json={"name": "x", "tenant_id": str(rig.probe.tenant_b)},
        headers=secure(client),
    )
    assert forged.json() == {"blocked": True}
    honest = client.post(
        f"{API}/probe/forge",
        json={"name": "x", "tenant_id": str(rig.probe.tenant_a)},
        headers=secure(client),
    )
    assert honest.json() == {"blocked": False}  # control: the same route works for the own tenant
    leaked = rig.web.rows("SELECT tenant_id FROM rls_customers WHERE name = 'forged'")
    assert leaked == [(rig.probe.tenant_a,)]  # only the honest write exists; none for tenant B


# --- AC-CTX-05 unknown and foreign tenants look identical -------------------------------------------------------
def test_a_tenant_without_membership_and_a_tenant_that_does_not_exist_answer_the_same(
    rig: Rig,
) -> None:
    client = rig.login("b")  # B belongs to tenant B only
    foreign = rig.select(client, rig.probe.tenant_a)
    unknown = rig.select(client, uuid.uuid4())
    for response in (foreign, unknown):
        problem(response, 404, "WORKSPACE_NOT_FOUND")

    def strip(r: httpx.Response) -> dict[str, Any]:
        return {k: v for k, v in r.json().items() if k != "request_id"}

    assert strip(foreign) == strip(unknown)
    assert {k: v for k, v in foreign.headers.items() if k not in ("x-request-id", "date")} == {
        k: v for k, v in unknown.headers.items() if k not in ("x-request-id", "date")
    }
    assert rig.web.rows("SELECT active_tenant_id FROM user_sessions") == [
        (None,)
    ]  # nothing changed


def test_a_branch_the_person_may_not_use_is_refused_like_an_unknown_one(rig: Rig) -> None:
    client = rig.login("a")
    viewer_of_b = rig.select(
        client, rig.probe.tenant_b, branches_of(rig.probe.tenant_b)[1]
    )  # VIEWER: first branch only
    problem(viewer_of_b, 404, "WORKSPACE_NOT_FOUND")
    assert (
        rig.select(client, rig.probe.tenant_b, branches_of(rig.probe.tenant_b)[0]).status_code
        == 200
    )


# --- AC-CTX-06 ending access takes effect on the next request ---------------------------------------------------
def test_ending_a_membership_blocks_the_next_request_and_other_workspaces_stay_available(
    rig: Rig,
) -> None:
    client = rig.login("a")
    assert rig.select(client, rig.probe.tenant_b).status_code == 200
    assert client.get(f"{API}/probe/customers").status_code == 200
    owner_sql(
        rig,
        "DELETE FROM rls_memberships WHERE tenant_id = :t AND user_id = :u",
        user=rig.probe.user_a,
        tenant=rig.probe.tenant_b,
        t=rig.probe.tenant_b,
        u=rig.probe.user_a,
    )
    problem(client.get(f"{API}/probe/customers"), 403, "WORKSPACE_REQUIRED")
    assert client.get(f"{API}/auth/session").status_code == 200  # the sign-in itself is untouched
    assert rig.select(client, rig.probe.tenant_a).status_code == 200  # the other tenant still works
    assert client.get(f"{API}/probe/customers").json()["tenant"] == str(rig.probe.tenant_a)


@pytest.mark.parametrize("new_role", ["SUSPENDED", "VIEWER"])
def test_role_and_branch_changes_apply_immediately(rig: Rig, new_role: str) -> None:
    client = rig.login("a")
    second_branch = branches_of(rig.probe.tenant_a)[1]
    assert rig.select(client, rig.probe.tenant_a, second_branch).status_code == 200  # OWNER may
    owner_sql(
        rig,
        "UPDATE rls_memberships SET role = :r WHERE tenant_id = :t AND user_id = :u",
        user=rig.probe.user_a,
        tenant=rig.probe.tenant_a,
        r=new_role,
        t=rig.probe.tenant_a,
        u=rig.probe.user_a,
    )
    problem(
        client.get(f"{API}/probe/customers"), 403, "WORKSPACE_REQUIRED"
    )  # branch 2 / tenant gone


# --- AC-CTX-07 sessions are independent --------------------------------------------------------------------------
def test_two_sessions_of_one_person_keep_their_own_workspace(rig: Rig) -> None:
    desktop, phone = rig.login("a", sid="desktop"), rig.login("a", sid="phone")
    rig.select(desktop, rig.probe.tenant_a)
    rig.select(phone, rig.probe.tenant_b)
    assert desktop.get(f"{API}/probe/customers").json()["tenant"] == str(rig.probe.tenant_a)
    assert phone.get(f"{API}/probe/customers").json()["tenant"] == str(rig.probe.tenant_b)
    rig.select(desktop, rig.probe.tenant_b)
    assert phone.get(f"{API}/probe/customers").json()["tenant"] == str(rig.probe.tenant_b)
    assert desktop.get(f"{API}/probe/customers").json()["tenant"] == str(rig.probe.tenant_b)
    rows = rig.web.rows(
        "SELECT kc_session_id, active_tenant_id, context_version FROM user_sessions ORDER BY kc_session_id"
    )
    assert rows == [("desktop", rig.probe.tenant_b, 3), ("phone", rig.probe.tenant_b, 2)]


# --- AC-CTX-08 optimistic context version ------------------------------------------------------------------------
def test_switching_needs_the_current_version_and_is_audited(rig: Rig) -> None:
    client = rig.login("a")
    url = f"{API}/sessions/workspace"
    body = {"tenant_id": str(rig.probe.tenant_a)}
    problem(client.post(url, json=body, headers=secure(client)), 428, "PRECONDITION_REQUIRED")
    problem(
        client.post(url, json=body, headers={**secure(client), "If-Match": '"7"'}),
        412,
        "VERSION_MISMATCH",
    )
    ok = client.post(url, json=body, headers={**secure(client), "If-Match": '"1"'})
    assert ok.status_code == 200 and ok.headers["etag"] == '"2"'
    info = ok.json()
    assert info["workspace"] == {
        "tenant_id": str(rig.probe.tenant_a),
        "branch_id": str(branches_of(rig.probe.tenant_a)[0]),
        "context_version": 2,
    }
    problem(
        client.post(url, json=body, headers={**secure(client), "If-Match": '"1"'}),
        412,
        "VERSION_MISMATCH",
    )  # stale now
    assert client.get(f"{API}/auth/session").headers["etag"] == '"2"'
    switched = rig.select(client, rig.probe.tenant_b)
    assert switched.status_code == 200
    audit = rig.web.rows(
        "SELECT details FROM audit_events WHERE action = 'session.context.changed' ORDER BY occurred_at"
    )
    assert len(audit) == 2
    assert audit[1][0]["from_tenant_id"] == str(rig.probe.tenant_a) and audit[1][0][
        "to_tenant_id"
    ] == str(rig.probe.tenant_b)
    assert (audit[1][0]["from_context_version"], audit[1][0]["to_context_version"]) == (2, 3)


def test_parallel_switches_from_the_same_version_have_exactly_one_winner(rig: Rig) -> None:
    client = rig.login("a")
    barrier = threading.Barrier(2)
    results: list[int] = []

    def attempt(tenant: uuid.UUID) -> None:
        c = rig.web.client()
        c.cookies.set(SESSION_COOKIE, client.cookies[SESSION_COOKIE], domain="autotramita.example")
        barrier.wait()
        results.append(rig.select(c, tenant, version=1).status_code)

    threads = [
        threading.Thread(target=attempt, args=(t,))
        for t in (rig.probe.tenant_a, rig.probe.tenant_b)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(results) == [200, 412]
    assert rig.web.rows("SELECT context_version FROM user_sessions") == [(2,)]


def test_switching_in_a_revoked_session_is_refused(rig: Rig) -> None:
    client = rig.login("a")
    cookie = client.cookies[SESSION_COOKIE]
    client.post(f"{API}/auth/logout", headers=secure(client))
    stale = rig.web.client()
    problem(
        stale.post(
            f"{API}/sessions/workspace",
            json={"tenant_id": str(rig.probe.tenant_a)},
            headers={
                "Cookie": f"{SESSION_COOKIE}={cookie}",
                "X-CSRF-Token": csrf_token(cookie),
                "Origin": ORIGIN_WEB,
                "If-Match": '"1"',
            },
        ),
        401,
        "SESSION_REVOKED",
    )


# --- AC-CTX-09 cross-tenant access on API and database level ----------------------------------------------------------
def test_each_person_only_ever_sees_the_tenant_of_their_workspace(rig: Rig) -> None:
    a, b = rig.login("a"), rig.login("b")
    rig.select(a, rig.probe.tenant_a)
    rig.select(b, rig.probe.tenant_b)
    assert a.get(f"{API}/probe/customers").json()["tenant"] == str(rig.probe.tenant_a)
    assert b.get(f"{API}/probe/customers").json()["tenant"] == str(rig.probe.tenant_b)
    assert rig.web.rows("SELECT count(DISTINCT tenant_id) FROM rls_customers") == [
        (2,)
    ]  # both exist
    assert a.get(f"{API}/probe/customers").json()["names"] == ["c"]  # but each sees only its own


# --- AC-CTX-10 failure of the port fails closed --------------------------------------------------------------------------
def test_an_outage_of_the_membership_store_refuses_workspace_routes_and_selection(rig: Rig) -> None:
    client = rig.login("a")
    rig.select(client, rig.probe.tenant_a)
    rig.web.runtime.membership = BrokenAuthorizer()
    broken = client.get(f"{API}/probe/customers")
    problem(broken, 503, "AUTHORIZATION_UNAVAILABLE")
    assert broken.headers["retry-after"] == "5"
    problem(rig.select(client, rig.probe.tenant_a), 503, "AUTHORIZATION_UNAVAILABLE")
    problem(client.get(f"{API}/me/workspaces"), 503, "AUTHORIZATION_UNAVAILABLE")
    assert (
        client.get(f"{API}/probe/user-only").status_code == 200
    )  # routes without a workspace work
    assert client.get(f"{API}/me").status_code == 200


def test_an_inconsistent_answer_of_the_port_is_never_trusted(rig: Rig) -> None:
    client = rig.login("a")
    rig.web.runtime.membership = InconsistentAuthorizer()
    problem(rig.select(client, rig.probe.tenant_a), 404, "WORKSPACE_NOT_FOUND")


# --- AC-CTX-11 the limiter sees only validated values ---------------------------------------------------------------------
def test_tenant_limits_follow_the_validated_workspace_not_client_hints(rig: Rig) -> None:
    client = rig.login("a")
    rig.select(client, rig.probe.tenant_a)
    spoof = {"X-Tenant-ID": str(rig.probe.tenant_b), "X-Forwarded-For": "203.0.113.9"}
    codes = [
        client.get(f"{API}/probe/limited-by-tenant", headers=spoof).status_code for _ in range(4)
    ]
    assert codes == [
        200,
        200,
        200,
        429,
    ]  # one counter for the real tenant, whatever the headers say
    rig.select(client, rig.probe.tenant_b)
    assert (
        client.get(f"{API}/probe/limited-by-tenant", headers=spoof).status_code == 200
    )  # tenant B has its own


def test_user_limits_are_global_across_tenants_and_not_per_tenant(rig: Rig) -> None:
    client = rig.login("a")
    codes = []
    for tenant in (
        rig.probe.tenant_a,
        rig.probe.tenant_b,
        rig.probe.tenant_a,
        rig.probe.tenant_b,
        rig.probe.tenant_a,
    ):
        rig.select(client, tenant)
        codes.append(client.get(f"{API}/probe/limited-by-user").status_code)
    assert codes == [200, 200, 200, 200, 429]
    other = rig.login("b")
    assert other.get(f"{API}/probe/limited-by-user").status_code == 200  # another person's counter


# --- AC-CTX-12 production wiring denies everything ------------------------------------------------------------------------
def test_the_production_authorizer_denies_every_workspace(
    role_env: RoleEnv, redis_url: str
) -> None:
    probe = build_probe(role_env)
    web = build_web(role_env, redis_url)  # default membership: DenyAllAuthorizer
    try:
        assert isinstance(web.runtime.membership, DenyAllAuthorizer)
        with role_env.admin_engine().connect() as c:
            c.execute(
                text(
                    "INSERT INTO users (id, auth_subject, email, email_normalized, status, email_verified_at) VALUES (:i, 'sub-a', 'a@example.test', 'a@example.test', 'ACTIVE', now())"
                ),
                {"i": probe.user_a},
            )
        web.app.include_router(probe_router, prefix=API)
        client = web.client()
        web.sign_in(client, sub="sub-a", email="a@example.test", sid="s")
        version = client.get(f"{API}/auth/session").headers["etag"]
        denied = client.post(
            f"{API}/sessions/workspace",
            json={"tenant_id": str(probe.tenant_a)},
            headers={**secure(client), "If-Match": version},
        )
        problem(denied, 404, "WORKSPACE_NOT_FOUND")
        assert client.get(f"{API}/me/workspaces").json() == {"items": [], "next_cursor": None}
        problem(client.get(f"{API}/probe/customers"), 403, "WORKSPACE_REQUIRED")
    finally:
        web.close()


def test_runtime_built_from_settings_uses_the_deny_all_authorizer(
    role_env: RoleEnv, redis_url: str
) -> None:
    settings = AuthSettings.model_validate(
        {"AUTH_OIDC_ISSUER": ISSUER, "AUTH_WEB_ORIGIN": ORIGIN_WEB, "AUTH_WEB_CLIENT_SECRET": "x"}
    )
    runtime = AuthRuntime.build(
        settings, create_redis(redis_url), role_env.engine("app"), namespace="n"
    )
    assert isinstance(runtime.membership, DenyAllAuthorizer)


def test_test_doubles_are_never_imported_by_the_application() -> None:
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "app").rglob("*.py")
        if "tests." in p.read_text() or "fake_membership" in p.read_text()
    ]
    assert offenders == []


# --- AC-AUTHZ-01 deny by default: every route declares its access, and anonymous callers are refused --------------------------
EXPECTED_ACCESS = {
    ("GET", "/api/v1/auth/login"): AccessKind.PUBLIC,
    ("GET", "/api/v1/auth/callback"): AccessKind.PUBLIC,
    ("POST", "/api/v1/auth/oidc/backchannel-logout"): AccessKind.PUBLIC,
    ("POST", "/api/v1/auth/mobile/session"): AccessKind.TOKEN,
    ("POST", "/api/v1/auth/logout"): AccessKind.SESSION,
    ("GET", "/api/v1/auth/session"): AccessKind.SESSION,
    ("POST", "/api/v1/auth/step-up"): AccessKind.SESSION,
    ("GET", "/api/v1/sessions"): AccessKind.SESSION,
    ("DELETE", "/api/v1/sessions/{session_id}"): AccessKind.SESSION,
    ("POST", "/api/v1/sessions/revoke-others"): AccessKind.SESSION,
    ("POST", "/api/v1/sessions/revoke-all"): AccessKind.SESSION,
    ("POST", "/api/v1/sessions/workspace"): AccessKind.SESSION,
    ("GET", "/api/v1/me"): AccessKind.USER,
    ("PATCH", "/api/v1/me"): AccessKind.USER,
    ("GET", "/api/v1/me/workspaces"): AccessKind.USER,
    ("POST", "/api/v1/auth/password-recovery"): AccessKind.PUBLIC,
    ("GET", "/api/v1/auth/email-change-verification"): AccessKind.PUBLIC,
    ("POST", "/api/v1/me/security/email-change-requests"): AccessKind.USER,
    ("POST", "/api/v1/me/security/email-change-confirmations"): AccessKind.USER,
    ("GET", "/api/v1/me/security"): AccessKind.USER,
    ("POST", "/api/v1/me/email-verification"): AccessKind.USER,
    ("POST", "/api/v1/me/security/password-change-requests"): AccessKind.USER,
    ("POST", "/api/v1/me/security/mfa-enrollment-requests"): AccessKind.USER,
    ("POST", "/api/v1/me/security/mfa-disable-requests"): AccessKind.USER,
    ("DELETE", "/api/v1/me/security/second-factors/{credential_id}"): AccessKind.USER,
    # F2-T10: the grant is read in the handler's platform transaction (platform_scope)
    ("GET", "/api/v1/platform/grant-types"): AccessKind.PLATFORM,
    ("GET", "/api/v1/platform/grants"): AccessKind.PLATFORM,
    ("POST", "/api/v1/platform/grants"): AccessKind.PLATFORM,
    ("POST", "/api/v1/platform/grants/{grant_id}/approve"): AccessKind.PLATFORM,
    ("POST", "/api/v1/platform/grants/{grant_id}/reject"): AccessKind.PLATFORM,
    ("POST", "/api/v1/platform/grants/{grant_id}/revoke"): AccessKind.PLATFORM,
}


def declared_routes(app: FastAPI) -> dict[tuple[str, str], AccessKind | None]:
    return {
        (method, path): kind
        for method, path, kind in iter_access(app)
        if path != "/api/v1/health" and method not in ("HEAD", "OPTIONS")
    }


def test_every_route_declares_its_access_and_the_set_is_exactly_the_reviewed_one() -> None:
    assert declared_routes(create_app()) == EXPECTED_ACCESS  # a new route fails here until reviewed


def test_anonymous_callers_are_refused_before_anything_else_on_every_protected_route(
    rig: Rig,
) -> None:
    anonymous = rig.web.client()
    for (method, path), kind in EXPECTED_ACCESS.items():
        if kind is AccessKind.PUBLIC:
            continue
        url = (
            path.replace("{session_id}", str(uuid.uuid4()))
            .replace("{credential_id}", "c1")
            .replace("{grant_id}", str(uuid.uuid4()))
        )
        response = anonymous.request(method, url, json={} if method in ("POST", "PATCH") else None)
        assert response.status_code == 401 and response.json()["code"] == "AUTH_REQUIRED", (
            method,
            path,
            response.text,
        )


# --- AC-AUTHZ-02 authority comes from the database on every request, never from a token --------------------------------------
def test_claims_in_a_token_never_grant_a_workspace_or_a_role(rig: Rig) -> None:
    token = rig.web.access(
        sub="sub-b",
        email="b@example.test",
        tenant_id=str(rig.probe.tenant_a),
        roles=["OWNER"],
        realm_access={"roles": ["admin"]},
    )
    client = rig.web.bearer(token)
    assert client.post(f"{API}/auth/mobile/session", json={}).status_code == 201
    assert client.get(f"{API}/auth/session").json()["workspace"] is None
    problem(client.get(f"{API}/probe/customers"), 403, "WORKSPACE_REQUIRED")


def test_a_pending_person_only_reaches_the_routes_that_allow_it(rig: Rig) -> None:
    client = rig.web.client()
    rig.web.sign_in(client, sub="sub-new", email="new@example.test", sid="s-new", verified=False)
    assert client.get(f"{API}/me").json()["status"] == "PENDING_VERIFICATION"
    problem(client.get(f"{API}/probe/user-only"), 403, "EMAIL_NOT_VERIFIED")
    problem(client.get(f"{API}/probe/customers"), 403, "EMAIL_NOT_VERIFIED")
    assert client.get(f"{API}/me/workspaces").status_code == 200


# --- step-up guard ------------------------------------------------------------------------------------------------------------
def test_the_step_up_guard_wants_a_second_factor_within_the_window(rig: Rig) -> None:
    client = rig.login("a")
    refused = client.get(f"{API}/probe/mfa")
    problem(refused, 401, "STEP_UP_REQUIRED")
    assert 'acr_values="loa2"' in refused.headers["www-authenticate"]
    mfa = rig.web.client()
    rig.web.sign_in(
        mfa, sub="sub-a", email="a@example.test", sid="sid-mfa", acr="loa2"
    )  # signed in with MFA
    assert mfa.get(f"{API}/probe/mfa").json() == {"level": "LOA2"}
    bearer = rig.web.bearer(
        rig.web.access(
            sub="sub-a",
            email="a@example.test",
            sid="sid-m",
            acr="loa2",
            auth_time=int(time.time()) - 5,
        )
    )
    bearer.post(f"{API}/auth/mobile/session", json={})
    assert bearer.get(f"{API}/probe/mfa").status_code == 200
    stale = rig.web.bearer(
        rig.web.access(
            sub="sub-a",
            email="a@example.test",
            sid="sid-m2",
            acr="loa2",
            auth_time=int(time.time()) - 3600,
        )
    )
    stale.post(f"{API}/auth/mobile/session", json={})
    problem(stale.get(f"{API}/probe/mfa"), 401, "STEP_UP_REQUIRED")


# --- /me ----------------------------------------------------------------------------------------------------------------------
def test_profile_read_and_change_with_optimistic_concurrency(rig: Rig) -> None:
    client = rig.login("a")
    me = client.get(f"{API}/me")
    assert me.status_code == 200 and me.headers["etag"] == f'"{me.json()["version"]}"'
    assert me.json()["email"] == "a@example.test" and me.headers["cache-control"] == "no-store"
    version = me.json()["version"]
    url = f"{API}/me"
    problem(
        client.patch(url, json={"display_name": "Ana"}, headers=secure(client)),
        428,
        "PRECONDITION_REQUIRED",
    )
    problem(
        client.patch(
            url, json={"display_name": "Ana"}, headers={**secure(client), "If-Match": '"999"'}
        ),
        412,
        "VERSION_MISMATCH",
    )
    problem(
        client.patch(url, json={"display_name": "Ana"}, headers={"If-Match": f'"{version}"'}),
        403,
        "CSRF_INVALID",
    )
    ok = client.patch(
        url,
        json={"display_name": "Ana", "preferred_language": "en"},
        headers={**secure(client), "If-Match": f'"{version}"'},
    )
    assert (
        ok.status_code == 200
        and ok.json()["display_name"] == "Ana"
        and ok.json()["preferred_language"] == "en"
    )
    assert ok.headers["etag"] == f'"{version + 1}"'
    cleared = client.patch(
        url, json={"display_name": None}, headers={**secure(client), "If-Match": f'"{version + 1}"'}
    )
    assert cleared.json()["display_name"] is None and cleared.json()["preferred_language"] == "en"
    problem(
        client.patch(
            url,
            json={"display_name": "Late"},
            headers={**secure(client), "If-Match": f'"{version}"'},
        ),
        412,
        "VERSION_MISMATCH",
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "x@y.zz"},
        {"status": "BLOCKED"},
        {"auth_subject": "x"},
        {"id": str(uuid.uuid4())},
        {"version": 9},
        {"display_name": "a\nb"},
        {"display_name": "x" * 121},
        {"display_name": ""},
        {"preferred_language": "ES"},
        {"preferred_language": "español"},
        {"preferred_language": None},
    ],
)
def test_the_profile_cannot_change_identity_email_or_status(rig: Rig, body: dict[str, Any]) -> None:
    client = rig.login("a")
    version = client.get(f"{API}/me").json()["version"]
    refused = client.patch(
        f"{API}/me", json=body, headers={**secure(client), "If-Match": f'"{version}"'}
    )
    assert refused.status_code == 422, refused.text
    assert rig.web.rows(
        "SELECT status, email, display_name, version FROM users WHERE auth_subject = 'sub-a'"
    ) == [("ACTIVE", "a@example.test", None, version)]


def test_the_workspace_list_comes_from_the_membership_port(rig: Rig) -> None:
    client = rig.login("a")
    listed = client.get(f"{API}/me/workspaces").json()
    assert listed["next_cursor"] is None
    by_tenant = {i["tenant_id"]: i for i in listed["items"]}
    assert set(by_tenant) == {str(rig.probe.tenant_a), str(rig.probe.tenant_b)}
    assert len(by_tenant[str(rig.probe.tenant_a)]["branch_ids"]) == 2  # OWNER
    assert len(by_tenant[str(rig.probe.tenant_b)]["branch_ids"]) == 1  # VIEWER
    assert [i["tenant_id"] for i in rig.login("b").get(f"{API}/me/workspaces").json()["items"]] == [
        str(rig.probe.tenant_b)
    ]
