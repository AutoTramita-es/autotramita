"""F2-T10 / AC-PLT-01..11, AC-POL-09, AC-POL-10 (5-minute window), AC-AUD-08 (grant changes): the
platform-grant routes end to end on real PostgreSQL 16 and Redis 7 with the platform database
role, a fake identity provider and a fake admin API."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from app.auth.security.notify import NoticeKind
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.platform.rig import API, GRANTS, PlatformRig, evidence, problem, secure

ADMIN, USERS, AUDIT, REVIEW, RECOVERY = (
    "PLATFORM_GRANT_ADMIN",
    "PLATFORM_USER_ADMIN",
    "PLATFORM_AUDIT_VIEW",
    "PLATFORM_VERIFICATION_REVIEW",
    "PLATFORM_ACCOUNT_RECOVERY",
)


def created(response: httpx.Response, status: str) -> str:
    assert response.status_code == 201, response.text
    assert response.json()["status"] == status, response.text
    return str(response.json()["id"])


def ok(response: httpx.Response, status: str) -> dict[str, Any]:
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == status, body
    return body


# --- the life of a four-eyes grant ---------------------------------------------------------------
def test_a_four_eyes_grant_needs_a_second_administrator_and_ends_at_once(rig: PlatformRig) -> None:
    a, as_a = rig.administrator("a")
    b, as_b = rig.administrator("b")
    c = rig.person("c")
    grant = created(rig.request(as_a, c, USERS), "PENDING_APPROVAL")
    assert c.sub not in rig.admin.mandatory  # nothing at the provider before it takes effect
    body = ok(rig.decide(as_b, grant, "approve"), "ACTIVE")
    assert body["approved_by"] == str(b.id) and body["granted_by"] == str(a.id) and body["active"]
    assert c.sub in rig.admin.mandatory and c.sub in rig.admin.obliged  # factor stays mandatory
    notices = [(n.kind, n.to) for n in rig.notifier.notices]
    assert (NoticeKind.PLATFORM_GRANT_CHANGED, c.email) in notices
    ok(rig.revoke(as_b, grant), "REVOKED")
    assert rig.grant_row(grant) == ("REVOKED", b.id, "NO_LONGER_NEEDED")
    assert notices.count((NoticeKind.PLATFORM_GRANT_CHANGED, c.email)) == 1
    assert [(n.kind, n.to) for n in rig.notifier.notices].count(
        (NoticeKind.PLATFORM_GRANT_CHANGED, c.email)
    ) == 2
    # every step is recorded once, naming the actor and the person, never an address or reason
    for action, actor in (
        ("authz.platform_grant.requested", a.id),
        ("authz.platform_grant.approved", b.id),
        ("authz.platform_grant.activated", b.id),
        ("authz.platform_grant.revoked", b.id),
    ):
        rows = [r for r in rig.audit(action) if r[1] == "USER"]  # not the two bootstraps
        assert [(r[0], r[1], r[2], r[3], str(r[4])) for r in rows] == [
            ("SUCCESS", "USER", actor, c.id, grant)
        ], action
        assert rows[0][5] == {"grant_id": grant, "grant_type": USERS}
    assert rig.web.rows(
        "SELECT count(*) FROM audit_events WHERE details::text ~ '@' OR details::text ~* 'rota'"
    ) == [(0,)]


def test_a_type_the_requester_holds_takes_effect_at_once_otherwise_it_waits(
    rig: PlatformRig,
) -> None:
    a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    d, e = rig.person("d"), rig.person("e")
    waiting = created(rig.request(as_a, d, AUDIT), "PENDING_APPROVAL")  # a holds no auditor grant
    ok(rig.decide(as_b, waiting, "approve"), "ACTIVE")
    auditor_for_a = created(rig.request(as_b, a, AUDIT), "PENDING_APPROVAL")
    _third, as_third = rig.administrator("third")  # neither the requester nor the beneficiary
    ok(rig.decide(as_third, auditor_for_a, "approve"), "ACTIVE")
    at_once = created(rig.request(as_a, e, AUDIT), "ACTIVE")  # now a holds it: no second person
    assert rig.grant_row(at_once) == ("ACTIVE", None, None) and e.sub in rig.admin.mandatory
    assert [str(r[4]) for r in rig.audit("authz.platform_grant.activated")][-1] == at_once


# --- AC-PLT-04 escalation -------------------------------------------------------------------------
def test_nobody_grants_approves_or_rejects_for_themselves(rig: PlatformRig) -> None:
    a, as_a = rig.administrator("a")
    b, as_b = rig.administrator("b")
    problem(rig.request(as_a, a, AUDIT), 403, "FORBIDDEN")
    pending = created(rig.request(as_a, b, USERS), "PENDING_APPROVAL")
    problem(rig.decide(as_a, pending, "approve"), 403, "FORBIDDEN")  # the requester
    problem(rig.decide(as_b, pending, "approve"), 403, "FORBIDDEN")  # the beneficiary
    problem(rig.decide(as_a, pending, "reject"), 403, "FORBIDDEN")
    problem(rig.decide(as_b, pending, "reject"), 403, "FORBIDDEN")
    assert rig.grant_row(pending) == ("PENDING_APPROVAL", None, None)
    reasons = [r[5]["reason"] for r in rig.audit("authz.denied")]
    assert reasons == ["SELF_GRANT", "FOUR_EYES", "FOUR_EYES", "FOUR_EYES", "FOUR_EYES"]
    _c, as_c = rig.administrator("c")
    ok(rig.decide(as_c, pending, "reject"), "REVOKED")
    assert (
        rig.grant_row(pending)[2] == "REJECTED"
        and len(rig.audit("authz.platform_grant.rejected")) == 1
    )


def test_without_the_grant_administrator_grant_every_route_is_refused(rig: PlatformRig) -> None:
    holder = rig.person("auditor")
    _a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    ok(
        rig.decide(as_b, created(rig.request(as_a, holder, AUDIT), "PENDING_APPROVAL"), "approve"),
        "ACTIVE",
    )
    for who in (holder, rig.person("nobody")):
        client = rig.signed_in(who)
        attempts = [
            client.get(f"{API}/platform/grant-types"),
            client.get(GRANTS),
            rig.request(client, rig.person(), AUDIT),
            rig.decide(client, str(uuid.uuid4()), "approve"),
            rig.decide(client, str(uuid.uuid4()), "reject"),
            rig.revoke(client, str(uuid.uuid4())),
        ]
        for response in attempts:
            problem(response, 403, "FORBIDDEN")
            assert "PLATFORM_" not in response.text  # nothing about which grant is missing
    denied = rig.audit("authz.denied")
    assert len(denied) == 12 and {r[5]["reason"] for r in denied} == {"PLATFORM_GRANT"}
    assert rig.web.rows("SELECT count(*) FROM platform_grants") == [(3,)]


# --- AC-POL-09 / AC-POL-10: level two, fresh enough, from the proof itself -----------------------
def test_a_grant_holder_without_level_two_is_asked_for_it(rig: PlatformRig) -> None:
    a, _ = rig.administrator("a")
    for factor_age in (None, 700):  # password only; a factor proven too long ago
        client = rig.signed_in(a, factor_age=factor_age)
        refused = client.get(f"{API}/platform/grant-types")
        problem(refused, 401, "STEP_UP_REQUIRED")
        assert 'acr_values="loa2"' in refused.headers["www-authenticate"]


def test_grant_changes_need_a_factor_proven_within_five_minutes(rig: PlatformRig) -> None:
    a, _ = rig.administrator("a")
    rig.administrator("b")
    target = rig.person("t")
    client = rig.signed_in(a, factor_age=400)  # 6 min 40 s ago: the catalog yes, changes no
    assert client.get(f"{API}/platform/grant-types").status_code == 200
    for refused in (client.get(GRANTS), rig.request(client, target, AUDIT)):
        problem(refused, 401, "STEP_UP_REQUIRED")
        assert 'max_age="300"' in refused.headers["www-authenticate"]
    assert rig.web.rows("SELECT count(*) FROM platform_grants WHERE user_id = :u", u=target.id) == [
        (0,)
    ]
    fresh = rig.signed_in(a, factor_age=60)
    created(rig.request(fresh, target, AUDIT), "PENDING_APPROVAL")


def test_a_mobile_caller_needs_the_same_level_two_from_its_token(rig: PlatformRig) -> None:
    a, _ = rig.administrator("a")
    now = time.time()

    def phone(**claims: Any) -> TestClient:
        sid = f"m-{time.time_ns()}"
        token = rig.web.access(sub=a.sub, sid=sid, email=a.email, now=now, **claims)
        client = rig.web.bearer(token)
        assert client.post(f"{API}/auth/mobile/session", json={}).status_code == 201
        return client

    fresh = phone(acr="loa2", auth_time=int(now) - 30)
    assert fresh.get(f"{API}/platform/grant-types").status_code == 200
    problem(phone(acr="loa1").get(f"{API}/platform/grant-types"), 401, "STEP_UP_REQUIRED")
    stale = phone(acr="loa2", auth_time=int(now) - 700)
    problem(stale.get(f"{API}/platform/grant-types"), 401, "STEP_UP_REQUIRED")


def test_the_person_must_hold_a_permanent_factor_before_a_grant_takes_effect(
    rig: PlatformRig,
) -> None:
    _a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    for factor in (None, "recovery-authn-codes"):  # password only; recovery codes only
        who = rig.person(factor=factor)
        pending = created(rig.request(as_a, who, USERS), "PENDING_APPROVAL")
        problem(rig.decide(as_b, pending, "approve"), 409, "NO_SECOND_FACTOR")
        assert rig.grant_row(pending) == ("PENDING_APPROVAL", None, None)
        assert who.sub not in rig.admin.mandatory
    for factor in ("otp", "webauthn", "webauthn-passwordless"):
        who = rig.person(factor=factor)
        ok(
            rig.decide(as_b, created(rig.request(as_a, who, USERS), "PENDING_APPROVAL"), "approve"),
            "ACTIVE",
        )
        assert who.sub in rig.admin.mandatory


def test_bootstrap_needs_a_permanent_factor_too(rig: PlatformRig) -> None:
    from app.platform.bootstrap import BootstrapRefused

    for factor in (None, "recovery-authn-codes"):
        with pytest.raises(BootstrapRefused, match="one-time code or passkey"):
            rig.bootstrap(rig.person(factor=factor))
    assert rig.web.rows("SELECT count(*) FROM platform_grants") == [(0,)]


def test_when_the_provider_cannot_answer_nothing_takes_effect(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    c = rig.person("c")
    pending = created(rig.request(as_a, c, USERS), "PENDING_APPROVAL")
    rig.admin.down = True
    problem(rig.decide(as_b, pending, "approve"), 503, "IDENTITY_PROVIDER_UNAVAILABLE")
    rig.admin.down = False
    assert rig.grant_row(pending) == ("PENDING_APPROVAL", None, None)
    assert rig.audit("authz.platform_grant.approved") == []
    rig.web.runtime.admin = None
    problem(rig.decide(as_b, pending, "approve"), 503, "AUTH_NOT_CONFIGURED")
    assert rig.grant_row(pending) == ("PENDING_APPROVAL", None, None)


def test_a_grant_holder_can_no_longer_switch_the_second_factor_off(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    c = rig.person("c")
    ok(
        rig.decide(as_b, created(rig.request(as_a, c, USERS), "PENDING_APPROVAL"), "approve"),
        "ACTIVE",
    )
    client = rig.signed_in(c, factor_age=20)
    refused = client.post(
        f"{API}/me/security/mfa-disable-requests",
        json={"confirm": "DISABLE_MFA", "return_to": "/me"},
        headers=secure(client),
    )
    problem(refused, 403, "SECOND_FACTOR_MANDATORY")


# --- AC-PLT-05 revocation and expiry act on the next request ------------------------------------
def test_a_revoked_grant_administrator_is_refused_on_the_next_request(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    b, as_b = rig.administrator("b")
    assert as_b.get(f"{API}/platform/grant-types").status_code == 200
    grant = str(rig.web.rows("SELECT id FROM platform_grants WHERE user_id = :u", u=b.id)[0][0])
    ok(rig.revoke(as_a, grant, "SECURITY_INCIDENT"), "REVOKED")
    problem(as_b.get(f"{API}/platform/grant-types"), 403, "FORBIDDEN")  # same session, no cache


def test_an_expired_grant_is_refused_and_its_expiry_recorded_once(rig: PlatformRig) -> None:
    a, as_a = rig.administrator("a")
    rig.administrator("b")
    with rig.env.admin_engine().connect() as c:  # let a's grant run out
        c.execute(text("SET session_replication_role = replica"))
        c.execute(
            text(
                "UPDATE platform_grants SET created_at = now() - interval '40 days', "
                "activated_at = now() - interval '40 days', expires_at = now() - interval '1 second' "
                "WHERE user_id = :u"
            ),
            {"u": a.id},
        )
    for _ in range(2):
        problem(as_a.get(GRANTS), 403, "FORBIDDEN")
    expired = rig.audit("authz.platform_grant.expired")
    assert len(expired) == 1 and expired[0][2] == a.id


# --- AC-PLT-06 anti-lockout -----------------------------------------------------------------------
def test_the_last_grant_administrator_stays(rig: PlatformRig) -> None:
    a, as_a = rig.administrator("a")
    b, _as_b = rig.administrator("b")
    own = str(rig.web.rows("SELECT id FROM platform_grants WHERE user_id = :u", u=a.id)[0][0])
    other = str(rig.web.rows("SELECT id FROM platform_grants WHERE user_id = :u", u=b.id)[0][0])
    ok(rig.revoke(as_a, other), "REVOKED")
    problem(rig.revoke(as_a, own), 409, "LAST_GRANT_ADMIN")
    assert rig.grant_row(own)[0] == "ACTIVE"


# --- AC-PLT-03 concurrency and replay ------------------------------------------------------------
def test_two_approvals_at_once_have_exactly_one_winner(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    _c, as_c = rig.administrator("c")
    target = rig.person("t")
    pending = created(rig.request(as_a, target, USERS), "PENDING_APPROVAL")
    barrier = threading.Barrier(2)
    answers: list[int] = []

    def approve(client: TestClient) -> None:
        barrier.wait(timeout=10)
        answers.append(rig.decide(client, pending, "approve").status_code)

    threads = [threading.Thread(target=approve, args=(c,)) for c in (as_b, as_c)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(answers) == [200, 409]
    assert len(rig.audit("authz.platform_grant.approved")) == 1


def test_a_repeated_request_decision_or_revocation_changes_nothing(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    target = rig.person("t")
    pending = created(rig.request(as_a, target, USERS), "PENDING_APPROVAL")
    problem(rig.request(as_a, target, USERS), 409, "GRANT_CONFLICT")
    ok(rig.decide(as_b, pending, "approve"), "ACTIVE")
    problem(rig.decide(as_b, pending, "approve"), 409, "GRANT_CONFLICT")
    problem(rig.decide(as_b, pending, "reject"), 409, "GRANT_CONFLICT")
    ok(rig.revoke(as_a, pending), "REVOKED")
    problem(rig.revoke(as_a, pending), 409, "GRANT_CONFLICT")
    problem(rig.decide(as_b, str(uuid.uuid4()), "approve"), 404, "NOT_FOUND")
    for action in ("requested", "approved", "revoked"):
        assert len(rig.audit(f"authz.platform_grant.{action}")) == 1, action


def test_parallel_requests_create_one_grant(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    target = rig.person("t")
    barrier = threading.Barrier(2)
    answers: list[int] = []

    def ask(client: TestClient) -> None:
        barrier.wait(timeout=10)
        answers.append(rig.request(client, target, AUDIT).status_code)

    threads = [threading.Thread(target=ask, args=(c,)) for c in (as_a, as_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(answers) == [201, 409]
    assert rig.web.rows("SELECT count(*) FROM platform_grants WHERE user_id = :u", u=target.id) == [
        (1,)
    ]


def test_an_expired_live_grant_is_closed_when_a_new_one_is_made(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    rig.administrator("b")
    target = rig.person("t")
    old = created(rig.request(as_a, target, AUDIT), "PENDING_APPROVAL")
    with rig.env.admin_engine().connect() as c:
        c.execute(text("SET session_replication_role = replica"))
        c.execute(
            text(
                "UPDATE platform_grants SET created_at = now() - interval '40 days', "
                "expires_at = now() - interval '1 second' WHERE id = :g"
            ),
            {"g": old},
        )
    new = created(rig.request(as_a, target, AUDIT), "PENDING_APPROVAL")
    assert new != old and rig.grant_row(old) == ("REVOKED", None, "EXPIRED")
    assert [str(r[4]) for r in rig.audit("authz.platform_grant.expired")] == [old]


# --- validation -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("grant_type", "extra"),
    [
        (AUDIT, {"days": 366}),
        (REVIEW, {"days": 91}),
        (AUDIT, {"days": -1}),
        (AUDIT, {"scope_kind": "TENANTS", "scope_tenant_ids": [str(uuid.uuid4())]}),
        (REVIEW, {"scope_kind": "TENANTS"}),
        (REVIEW, {"scope_kind": "QUEUE"}),
        ("PLATFORM_SUPER_ADMIN", {}),
        (AUDIT, {"reason": "x"}),
        (AUDIT, {"reason": "line\nbreak"}),
        (AUDIT, {"approved_by": str(uuid.uuid4())}),
        (AUDIT, {"status": "ACTIVE"}),
    ],
)
def test_requests_outside_the_rules_are_refused(
    rig: PlatformRig, grant_type: str, extra: dict[str, Any]
) -> None:
    _a, as_a = rig.administrator("a")
    response = rig.request(as_a, rig.person(), grant_type, **extra)
    assert response.status_code == 422, response.text
    assert rig.web.rows("SELECT count(*) FROM platform_grants WHERE reason <> 'bootstrap'") == [
        (0,)
    ]


def test_a_naive_time_is_refused(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    body = {"user_id": str(rig.person().id), "grant_type": AUDIT, "reason": "needed for work",
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).replace(tzinfo=None).isoformat()}  # fmt: skip
    assert as_a.post(GRANTS, json=body, headers=secure(as_a)).status_code == 422


def test_the_verification_reviewer_may_be_scoped(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    tenant = str(uuid.uuid4())
    grant = created(
        rig.request(
            as_a, rig.person(), REVIEW, days=90, scope_kind="TENANTS", scope_tenant_ids=[tenant]
        ),
        "PENDING_APPROVAL",
    )
    body = ok(rig.decide(as_b, grant, "approve"), "ACTIVE")
    assert body["scope_kind"] == "TENANTS" and body["scope_tenant_ids"] == [tenant]


# --- reading -------------------------------------------------------------------------------------
def test_the_catalog_lists_the_five_types_and_their_rules(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    catalog = {t["grant_type"]: t for t in as_a.get(f"{API}/platform/grant-types").json()}
    assert set(catalog) == {ADMIN, USERS, AUDIT, REVIEW, RECOVERY}
    assert {k for k, v in catalog.items() if v["four_eyes"]} == {ADMIN, USERS}
    assert catalog[REVIEW]["max_lifetime_days"] == 90 and catalog[AUDIT]["max_lifetime_days"] == 365
    assert catalog[REVIEW]["scope_kinds"] == ["ALL", "TENANTS", "QUEUE"]


def test_the_list_pages_with_a_signed_cursor_and_filters(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    rig.administrator("b")
    people = [rig.person() for _ in range(3)]
    for who in people:
        created(rig.request(as_a, who, AUDIT), "PENDING_APPROVAL")
    first = as_a.get(GRANTS, params={"limit": 2, "status": "PENDING_APPROVAL"}).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = as_a.get(
        GRANTS, params={"limit": 2, "status": "PENDING_APPROVAL", "cursor": first["next_cursor"]}
    ).json()
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    seen = {i["user_id"] for i in first["items"] + second["items"]}
    assert seen == {str(p.id) for p in people}
    everything = as_a.get(GRANTS).json()["items"]
    assert len(everything) == 5  # two bootstrap grants and three requests, all people's
    problem(
        as_a.get(GRANTS, params={"limit": 2, "status": "ACTIVE", "cursor": first["next_cursor"]}),
        400,
        "INVALID_CURSOR",
    )
    problem(
        as_a.get(GRANTS, params={"cursor": first["next_cursor"][:-2] + "AA"}), 400, "INVALID_CURSOR"
    )
    mine = as_a.get(GRANTS, params={"user_id": str(people[0].id)}).json()["items"]
    assert [i["user_id"] for i in mine] == [str(people[0].id)]


# --- AC-PLT-10 every use is recorded in the same transaction -------------------------------------
def test_every_use_is_recorded_and_rolled_back_with_its_action(rig: PlatformRig) -> None:
    a, as_a = rig.administrator("a")
    _b, as_b = rig.administrator("b")
    target = rig.person("t")
    before = len(rig.audit("authz.platform_grant.used"))
    as_a.get(f"{API}/platform/grant-types")
    pending = created(rig.request(as_a, target, USERS), "PENDING_APPROVAL")
    problem(rig.request(as_a, target, USERS), 409, "GRANT_CONFLICT")  # rolled back: no use left
    used = rig.audit("authz.platform_grant.used")[before:]
    assert [(r[2], r[3]) for r in used] == [(a.id, a.id), (a.id, a.id)]
    assert {r[5]["grant_type"] for r in used} == {ADMIN}
    ok(rig.decide(as_b, pending, "approve"), "ACTIVE")
    assert len(rig.audit("authz.platform_grant.used")) == before + 3


# --- configuration, CSRF, limits ------------------------------------------------------------------
def test_without_the_platform_role_every_platform_route_answers_503(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    rig.web.runtime.platform_factory = None
    problem(as_a.get(f"{API}/platform/grant-types"), 503, "AUTH_NOT_CONFIGURED")
    problem(rig.request(as_a, rig.person(), AUDIT), 503, "AUTH_NOT_CONFIGURED")


def test_cookie_requests_need_the_csrf_token(rig: PlatformRig) -> None:
    _a, as_a = rig.administrator("a")
    body = {"user_id": str(rig.person().id), "grant_type": AUDIT, "reason": "needed for work",
            "expires_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}  # fmt: skip
    problem(as_a.post(GRANTS, json=body), 403, "CSRF_INVALID")
    assert rig.web.rows("SELECT count(*) FROM platform_grants WHERE reason <> 'bootstrap'") == [
        (0,)
    ]


def test_platform_routes_are_limited_per_person(
    rig: PlatformRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    _a, as_a = rig.administrator("a")
    monkeypatch.setattr(rig.web.runtime.settings, "platform_per_min_user", 2)
    answers = [as_a.get(f"{API}/platform/grant-types").status_code for _ in range(3)]
    assert answers == [200, 200, 429]


def test_anonymous_and_unverified_callers_never_reach_the_grants(rig: PlatformRig) -> None:
    anonymous = rig.web.client()
    problem(anonymous.get(GRANTS), 401, "AUTH_REQUIRED")
    pending_email = rig.web.client()
    assert rig.web.sign_in(pending_email, sub="sub-pending", email="pending@example.test",
                           verified=False, sid="s-pending", **evidence(5)).status_code == 302  # fmt: skip
    problem(pending_email.get(GRANTS), 403, "EMAIL_NOT_VERIFIED")
