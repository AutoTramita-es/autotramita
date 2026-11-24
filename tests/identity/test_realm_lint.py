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
