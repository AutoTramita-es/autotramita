"""F2-T01 / AC-KC-01..03: realm files are generated, policy-compliant and secret-free.
These tests need no Keycloak."""

import copy
import json
import re
import runpy
from pathlib import Path
from typing import Any

import pytest
from tests.identity.realm_lint import lint_realm

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / "identity" / "keycloak"
KINDS = ("dev", "prod", "test")


def load(kind: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DIRECTORY / f"realm-{kind}.json").read_text())
    return data


@pytest.mark.parametrize("kind", KINDS)
def test_committed_realms_comply_with_policy(kind: str) -> None:
    assert lint_realm(load(kind), kind=kind) == []


def test_committed_realms_equal_the_rendered_template() -> None:
    renderer = runpy.run_path(str(ROOT / "scripts" / "identity" / "render_realms.py"))
    for kind in KINDS:
        assert (DIRECTORY / f"realm-{kind}.json").read_text() == renderer["render"](kind)


def test_dev_and_prod_share_nothing_environment_specific() -> None:
    dev, prod = load("dev"), load("prod")
    assert dev["realm"] != prod["realm"]
    dev_uris = {u for c in dev["clients"] for u in c["redirectUris"]}
    prod_uris = {u for c in prod["clients"] for u in c["redirectUris"]}
    assert not dev_uris & prod_uris
    assert all("dev." in u for u in dev_uris) and all("dev." not in u for u in prod_uris)


def test_no_literal_secret_or_unresolved_template_token_in_any_realm_file() -> None:
    for path in sorted(DIRECTORY.glob("realm-*.json")):
        text = path.read_text()
        if path.name != "realm-template.json":
            assert not re.search(r"__[A-Z_]+__", text), path.name
        for secret in re.findall(r'"secret":\s*"([^"]*)"', text):
            assert re.fullmatch(r"\$\{[A-Z0-9_]+\}", secret), path.name


def _mutated(kind: str, change: Any) -> list[str]:
    realm = copy.deepcopy(load(kind))
    change(realm)
    return lint_realm(realm, kind=kind)


def _action(realm: dict[str, Any], alias: str) -> dict[str, Any]:
    found: dict[str, Any] = next(a for a in realm["requiredActions"] if a["alias"] == alias)
    return found


def _flow(realm: dict[str, Any], alias: str) -> dict[str, Any]:
    return next(f for f in realm["authenticationFlows"] if f["alias"] == alias)


def _config(realm: dict[str, Any], alias: str) -> dict[str, str]:
    found: dict[str, str] = next(
        c["config"] for c in realm["authenticatorConfig"] if c["alias"] == alias
    )
    return found


def _marker_editable(realm: dict[str, Any]) -> None:
    _attribute_editable(realm, "at_mfa_required")


def _attribute_editable(realm: dict[str, Any], name: str) -> None:
    config = realm["components"]["org.keycloak.userprofile.UserProfileProvider"][0]["config"]
    profile = json.loads(config["kc.user.profile.config"][0])
    marker = next(a for a in profile["attributes"] if a["name"] == name)
    marker["permissions"]["edit"] = ["admin", "user"]
    config["kc.user.profile.config"] = [json.dumps(profile)]


def _client(realm: dict[str, Any], client_id: str) -> dict[str, Any]:
    return next(c for c in realm["clients"] if c["clientId"] == client_id)


@pytest.mark.parametrize(
    ("label", "change", "expected"),
    [
        (
            "wildcard",
            lambda r: _client(r, "at-web")["redirectUris"].append("https://x.test/*"),
            "wildcard",
        ),
        ("implicit", lambda r: _client(r, "at-web").update(implicitFlowEnabled=True), "implicit"),
        (
            "direct grants",
            lambda r: _client(r, "at-mobile").update(directAccessGrantsEnabled=True),
            "direct",
        ),
        (
            "public secret",
            lambda r: _client(r, "at-mobile").update(secret="hunter2"),
            "public client",
        ),
        ("literal secret", lambda r: _client(r, "at-web").update(secret="hunter2"), "placeholder"),
        (
            "no pkce",
            lambda r: _client(r, "at-web")["attributes"].pop("pkce.code.challenge.method"),
            "PKCE",
        ),
        ("web origins", lambda r: _client(r, "at-web").update(webOrigins=["*"]), "webOrigins"),
        (
            "http redirect",
            lambda r: _client(r, "at-web")["redirectUris"].append("http://evil.test/cb"),
            "https",
        ),
        ("verify email", lambda r: r.update(verifyEmail=False), "verifyEmail"),
        ("reset allowed", lambda r: r.update(resetPasswordAllowed=True), "resetPasswordAllowed"),
        ("brute force off", lambda r: r.update(bruteForceProtected=False), "brute-force"),
        ("failure factor", lambda r: r.update(failureFactor=10), "failureFactor"),
        ("window", lambda r: r.update(maxDeltaTimeSeconds=3600), "window"),
        ("permanent lockout", lambda r: r.update(permanentLockout=True), "permanent"),
        ("duplicate mail", lambda r: r.update(duplicateEmailsAllowed=True), "duplicate"),
        ("reuse", lambda r: r.update(refreshTokenMaxReuse=1), "reuse"),
        ("long token", lambda r: r.update(accessTokenLifespan=3600), "access token"),
        ("admin repr", lambda r: r.update(adminEventsDetailsEnabled=True), "representation"),
        ("short password", lambda r: r.update(passwordPolicy="length(8)"), "length"),
        (
            "passkey registration",
            lambda r: _action(r, "webauthn-register").update(enabled=True),
            "webauthn-register must be off",
        ),
        (
            "passwordless registration",
            lambda r: _action(r, "webauthn-register-passwordless").update(enabled=True),
            "webauthn-register-passwordless must be off",
        ),
        (
            "forced second factor",
            lambda r: _action(r, "CONFIGURE_TOTP").update(defaultAction=True),
            "CONFIGURE_TOTP must be on and never forced",
        ),
        (
            "defaults left to Keycloak",
            lambda r: r.pop("requiredActions"),
            "required actions must all be listed",
        ),
        (
            "a factor missing at step-up",
            lambda r: _flow(r, "browser-loa-2-factor")["authenticationExecutions"].pop(),
            "browser-loa-2-factor differs",
        ),
        (
            "factor optional",
            lambda r: _flow(r, "browser-loa-2")["authenticationExecutions"][1].update(
                requirement="DISABLED"
            ),
            "browser-loa-2 differs",
        ),
        (
            "pass-through at level two",
            lambda r: _flow(r, "browser-loa-2-factor")["authenticationExecutions"].append(
                {
                    "authenticator": "allow-access-authenticator",
                    "requirement": "ALTERNATIVE",
                    "priority": 90,
                }
            ),
            "browser-loa-2-factor differs",
        ),
        (
            "enrol although a factor exists",
            lambda r: _config(r, "loa2-no-factor-to-prove").update(check_result="executed"),
            "browser-loa-2-enrol differs",
        ),
        (
            "long level two",
            lambda r: _config(r, "loa2-condition").update({"loa-max-age": "3600"}),
            "browser-loa-2 differs",
        ),
        (
            "a recovery code at step-up",
            lambda r: _flow(r, "browser-loa-2-factor")["authenticationExecutions"].append(
                {
                    "authenticator": "auth-recovery-authn-code-form",
                    "requirement": "ALTERNATIVE",
                    "priority": 90,
                }
            ),
            "browser-loa-2-factor differs",
        ),
        (
            "no factor with the password",
            lambda r: _flow(r, "browser-loa-1")["authenticationExecutions"].pop(6),
            "browser-loa-1 differs",
        ),
        (
            "last code needs no permanent factor",
            lambda r: _flow(r, "browser-loa-1")["authenticationExecutions"].pop(),
            "browser-loa-1 differs",
        ),
        (
            "other sessions survive a spent set",
            lambda r: _config(r, "one-session").update(userRealmLimit="0"),
            "browser-loa-1-codes-spent differs",
        ),
        (
            "codes belong to level two",
            lambda r: _flow(r, "browser-loa-4")["authenticationExecutions"].pop(),
            "browser-loa-4 differs",
        ),
        (
            "levels reordered",
            lambda r: _flow(r, "browser-loa-forms")["authenticationExecutions"][1].update(
                priority=35
            ),
            "browser-loa-forms differs",
        ),
        (
            "long level three",
            lambda r: _config(r, "loa3-condition").update({"loa-max-age": "600"}),
            "browser-loa-3 differs",
        ),
        (
            "codes alone let in",
            lambda r: _flow(r, "browser-deny-codes-only")["authenticationExecutions"].pop(),
            "browser-deny-codes-only differs",
        ),
        (
            "locked account lets in",
            lambda r: _flow(r, "browser-deny-marked-without-factor")[
                "authenticationExecutions"
            ].pop(),
            "browser-deny-marked-without-factor differs",
        ),
        (
            "marker editable by the user",
            lambda r: _marker_editable(r),
            "administrators only",
        ),
        (
            "removal at the provider",
            lambda r: _action(r, "delete_credential").update(enabled=True),
            "delete_credential must be off",
        ),
        (
            "password change from an old session",
            lambda r: _action(r, "UPDATE_PASSWORD").pop("config"),
            "fresh authentication",
        ),
        (
            "factor set-up from an old session",
            lambda r: _action(r, "CONFIGURE_TOTP").update(config={}),
            "CONFIGURE_TOTP: a credential may change only after a fresh",
        ),
        (
            "no guard step",
            lambda r: _flow(r, "browser-loa-forms")["authenticationExecutions"].pop(0),
            "browser-loa-forms differs",
        ),
        (
            "mandatory flag editable by the user",
            lambda r: _attribute_editable(r, "at_mfa_mandatory"),
            "at_mfa_mandatory must be visible and changeable by administrators only",
        ),
        (
            "refusals not stored",
            lambda r: r["enabledEventTypes"].remove("CUSTOM_REQUIRED_ACTION_ERROR"),
            "stored as events",
        ),
        (
            "switch-off off",
            lambda r: _action(r, "at-disable-mfa").update(enabled=False),
            "at-disable-mfa must be on",
        ),
        (
            "password grant flow",
            lambda r: r.update(directGrantFlow="direct grant"),
            "password grants",
        ),
        (
            "level map",
            lambda r: _client(r, "at-mobile")["attributes"].update({"acr.loa.map": "{}"}),
            "level map changed",
        ),
        (
            "no factor time",
            lambda r: _client(r, "at-web")["protocolMappers"].pop(),
            "loa_map",
        ),
        (
            "svc roles",
            lambda r: r["users"][0]["clientRoles"]["realm-management"].append("manage-realm"),
            "too broad",
        ),
        (
            "user credentials",
            lambda r: r["users"][0].update(credentials=[{"value": "x"}]),
            "credentials",
        ),
        (
            "svc without the admin API scope",
            lambda r: _client(r, "at-admin-svc")["defaultClientScopes"].remove("kc-admin-api"),
            "kc-admin-api",
        ),
        (
            "tenant claim",
            lambda r: _client(r, "at-web")["protocolMappers"].append(
                {"name": "t", "config": {"claim.name": "tenant_id"}}
            ),
            "authorization claims",
        ),
    ],
)
def test_linter_rejects_each_violation(label: str, change: Any, expected: str) -> None:
    problems = _mutated("dev", change)
    assert any(expected.lower() in p.lower() for p in problems), (label, problems)


def test_blacklist_file_exists_and_has_only_long_entries() -> None:
    entries = (DIRECTORY / "blacklists" / "at-common-passwords.txt").read_text().split()
    assert entries and all(len(e) >= 12 for e in entries)


@pytest.mark.parametrize("kind", KINDS)
def test_token_scopes_and_optional_names_are_explicit(kind: str) -> None:
    realm = load(kind)
    for client_id in ("at-web", "at-mobile"):
        client = _client(realm, client_id)
        assert set(client["defaultClientScopes"]) == {"email", "acr", "basic"}
        assert client["optionalClientScopes"] == [] and client["fullScopeAllowed"] is False
    component = realm["components"]["org.keycloak.userprofile.UserProfileProvider"][0]
    profile = json.loads(component["config"]["kc.user.profile.config"][0])
    attrs = {attribute["name"]: attribute for attribute in profile["attributes"]}
    assert "required" not in attrs["firstName"] and "required" not in attrs["lastName"]
    assert attrs["email"]["required"] == {"roles": ["user"]}


def test_every_second_factor_the_application_knows_is_proven_at_level_two() -> None:
    """Each kind is asked with the password; a step-up of an existing session takes the
    permanent ones only."""
    from app.auth.idp import SECOND_FACTOR_TYPES
    from tests.identity.realm_lint import FACTOR_AUTHENTICATORS

    assert set(FACTOR_AUTHENTICATORS) == SECOND_FACTOR_TYPES
    every = set(FACTOR_AUTHENTICATORS.values())
    permanent = every - {FACTOR_AUTHENTICATORS["recovery-authn-codes"]}
    for kind in KINDS:
        with_password = _flow(load(kind), "browser-loa-1-factor")["authenticationExecutions"]
        assert {e.get("authenticator") for e in with_password} >= every
        step_up = _flow(load(kind), "browser-loa-2-factor")["authenticationExecutions"]
        asked = {e.get("authenticator") for e in step_up} & every
        assert asked == permanent
