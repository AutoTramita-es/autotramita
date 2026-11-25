"""Static policy checks for Keycloak realm files (F2-T01, AC-KC-02). No Keycloak needed."""

from __future__ import annotations

import re
from typing import Any

from app.auth.idp import SECOND_FACTOR_TYPES
from app.core.config import RateLimitSettings

PLACEHOLDER = re.compile(r"^\$\{[A-Z][A-Z0-9_]*\}$")
ADMIN_SVC_ROLES = {"manage-users", "view-users", "view-events"}
# Every required action and whether people may use it. Passkey registration stays off until the
# step-up flow accepts a passkey as a second level (F2-T09-REC F-1); none is forced (I07).
REQUIRED_ACTIONS = {
    "CONFIGURE_TOTP": True,
    "TERMS_AND_CONDITIONS": False,
    "UPDATE_PASSWORD": True,
    "UPDATE_PROFILE": True,
    "VERIFY_EMAIL": True,
    "delete_account": False,
    "UPDATE_EMAIL": False,
    "webauthn-register": False,
    "webauthn-register-passwordless": False,
    "VERIFY_PROFILE": True,
    "delete_credential": True,
    "idp_link": True,
    "CONFIGURE_RECOVERY_AUTHN_CODES": True,
    "update_user_locale": True,
}
# The authenticator that proves each kind of second factor the application knows (F-1R). A kind
# without one at level two would be offered a new one-time code after the password alone.
FACTOR_AUTHENTICATORS = {
    "otp": "auth-otp-form",
    "webauthn": "webauthn-authenticator",
    "webauthn-passwordless": "webauthn-authenticator-passwordless",
    "recovery-authn-codes": "auth-recovery-authn-code-form",
}
assert set(FACTOR_AUTHENTICATORS) == SECOND_FACTOR_TYPES
# Every authentication flow of the realm, exactly: (authenticator or sub-flow, requirement) in
# execution order. Anything else could let a level be reached without its proof.
FLOWS: dict[str, list[tuple[str, str]]] = {
    "browser-loa": [("auth-cookie", "ALTERNATIVE"), ("flow:browser-loa-forms", "ALTERNATIVE")],
    "browser-loa-forms": [
        ("flow:browser-loa-1", "CONDITIONAL"),
        ("flow:browser-loa-2", "CONDITIONAL"),
    ],
    "browser-loa-1": [
        ("conditional-level-of-authentication", "REQUIRED"),
        ("auth-username-password-form", "REQUIRED"),
    ],
    "browser-loa-2": [
        ("conditional-level-of-authentication", "REQUIRED"),
        ("flow:browser-loa-2-factor", "CONDITIONAL"),
        ("flow:browser-loa-2-enrol", "CONDITIONAL"),
    ],
    "browser-loa-2-factor": [("conditional-user-configured", "REQUIRED")]
    + [(name, "ALTERNATIVE") for name in FACTOR_AUTHENTICATORS.values()],
    "browser-loa-2-enrol": [
        ("conditional-sub-flow-executed", "REQUIRED"),
        ("auth-otp-form", "REQUIRED"),
    ],
    "direct-grant-denied": [("deny-access-authenticator", "REQUIRED")],
}
LOA_MAP = '{"loa1":1,"loa2":2}'
LOA_TIMES_MAPPER = {
    "user.session.note": "loa-map",
    "claim.name": "loa_map",
    "jsonType.label": "String",
    "id.token.claim": "true",
    "access.token.claim": "true",
}
SECRET_KEYS = re.compile(r"secret|password|credential", re.I)


def _is_local(uri: str) -> bool:
    return uri.startswith("http://127.0.0.1")


def lint_realm(realm: dict[str, Any], *, kind: str) -> list[str]:
    """Return policy violations (empty means compliant). ``kind`` is dev, prod or test."""
    problems: list[str] = []
    limits = RateLimitSettings()

    def need(condition: bool, message: str) -> None:
        if not condition:
            problems.append(message)

    need(realm.get("realm") == f"autotramita-{kind}", "realm name must be autotramita-<env>")
    ssl = realm.get("sslRequired")
    need(ssl == {"prod": "all", "dev": "external", "test": "none"}[kind], f"sslRequired {ssl}")
    need(realm.get("verifyEmail") is True, "verifyEmail must be true")
    need(realm.get("resetPasswordAllowed") is False, "resetPasswordAllowed must be false (D20)")
    need(realm.get("duplicateEmailsAllowed") is False, "duplicate e-mails must be disallowed")
    need(realm.get("registrationEmailAsUsername") is True, "e-mail must be the username")
    need(realm.get("editUsernameAllowed") is False, "editUsernameAllowed must be false")
    need(realm.get("bruteForceProtected") is True, "brute-force detection must be on")
    need(realm.get("permanentLockout") is False, "permanent lockout must be off")
    need(
        realm.get("failureFactor") == limits.keycloak_max_failed_logins == 5,
        "failureFactor must be 5 (accepted limit)",
    )
    need(
        realm.get("maxDeltaTimeSeconds") == limits.keycloak_failure_window_minutes * 60 == 900,
        "failure window must be 15 minutes",
    )
    need(realm.get("accessTokenLifespan", 10**9) <= 300, "access token lifespan above 5 min")
    need(realm.get("ssoSessionIdleTimeout", 10**9) <= 1800, "SSO idle above 30 min")
    need(realm.get("ssoSessionMaxLifespan", 10**9) <= 43200, "SSO max above 12 h")
    need(realm.get("revokeRefreshToken") is True, "refresh tokens must rotate")
    need(realm.get("refreshTokenMaxReuse") == 0, "refresh token reuse must be 0")
    need(realm.get("adminEventsDetailsEnabled") is False, "admin event representations off")
    need(realm.get("eventsEnabled") is True, "events must be stored")
    need(realm.get("defaultSignatureAlgorithm") == "RS256", "RS256 signing expected")
    policy = str(realm.get("passwordPolicy", ""))
    length = re.search(r"length\((\d+)\)", policy)
    need(bool(length) and int(length.group(1)) >= 12 if length else False, "password length >= 12")
    for part in ("notUsername", "notEmail", "passwordBlacklist("):
        need(part in policy, f"password policy lacks {part}")
    need(realm.get("browserFlow") == "browser-loa", "step-up browser flow must be active")
    need(
        realm.get("directGrantFlow") == "direct-grant-denied",
        "password grants must be refused for every client",
    )
    flows = {f.get("alias"): f for f in realm.get("authenticationFlows", [])}
    need(set(flows) == set(FLOWS), "unexpected set of authentication flows")
    configs = {c.get("alias"): c.get("config", {}) for c in realm.get("authenticatorConfig", [])}
    used: dict[str, list[dict[str, Any]]] = {}
    for alias, expected in FLOWS.items():
        executions = sorted(
            flows.get(alias, {}).get("authenticationExecutions", []),
            key=lambda e: e.get("priority", 0),
        )
        actual = [
            (
                f"flow:{e['flowAlias']}" if e.get("authenticatorFlow") else e.get("authenticator"),
                e.get("requirement"),
            )
            for e in executions
        ]
        need(actual == expected, f"flow {alias} differs from the reviewed one: {actual}")
        used[alias] = [configs.get(e.get("authenticatorConfig"), {}) for e in executions]

    def first_config(alias: str) -> dict[str, Any]:
        found = used.get(alias) or [{}]
        return found[0]

    for alias, level, oldest in (("browser-loa-1", "1", 43200), ("browser-loa-2", "2", 600)):
        condition = first_config(alias)
        need(
            condition.get("loa-condition-level") == level
            and 0 <= int(condition.get("loa-max-age", 10**9)) <= oldest,
            f"flow {alias}: level {level} must expire within {oldest} s",
        )
    need(
        first_config("browser-loa-2-enrol")
        == {"flow_to_check": "browser-loa-2-factor", "check_result": "not-executed"},
        "a new second factor may be set up only when there is none to prove",
    )
    need(realm.get("attributes", {}).get("acr.loa.map") == LOA_MAP, "realm level map changed")

    actions = {a.get("alias"): a for a in realm.get("requiredActions", [])}
    need(set(REQUIRED_ACTIONS) <= set(actions), "required actions must all be listed")
    for alias, enabled in REQUIRED_ACTIONS.items():
        found = actions.get(alias, {})
        need(
            found.get("enabled") is enabled and found.get("defaultAction") is False,
            f"required action {alias} must be {'on' if enabled else 'off'} and never forced",
        )
    clients = {c["clientId"]: c for c in realm.get("clients", [])}
    need(set(clients) == {"at-web", "at-mobile", "at-admin-svc"}, "unexpected client set")
    for client_id, client in clients.items():
        where = f"client {client_id}"
        need(client.get("implicitFlowEnabled") is False, f"{where}: implicit flow enabled")
        need(client.get("directAccessGrantsEnabled") is False, f"{where}: direct grants enabled")
        need(client.get("webOrigins", []) == [], f"{where}: webOrigins must be empty")
        uris = client.get("redirectUris", [])
        for uri in uris:
            need("*" not in uri, f"{where}: wildcard redirect {uri}")
            need(
                uri.startswith("https://") or (kind == "test" and _is_local(uri)),
                f"{where}: redirect {uri} must be https",
            )
        if client.get("standardFlowEnabled"):
            need(
                client.get("attributes", {}).get("pkce.code.challenge.method") == "S256",
                f"{where}: PKCE S256 required",
            )
            need(bool(uris), f"{where}: standard flow without redirect URIs")
        if client.get("publicClient"):
            need("secret" not in client, f"{where}: public client must not hold a secret")
        else:
            need(
                bool(PLACEHOLDER.match(str(client.get("secret", "")))),
                f"{where}: secret must be an ${{ENV}} placeholder",
            )
    for client_id in ("at-web", "at-mobile"):
        client = clients.get(client_id, {})
        need(
            client.get("attributes", {}).get("acr.loa.map") == LOA_MAP,
            f"client {client_id}: level map changed",
        )
        times = [
            m.get("config", {})
            for m in client.get("protocolMappers", [])
            if m.get("protocolMapper") == "oidc-usersessionmodel-note-mapper"
        ]
        need(
            len(times) == 1 and LOA_TIMES_MAPPER.items() <= times[0].items(),
            f"client {client_id}: the second-factor time (loa_map) must be in both tokens",
        )
    web = clients.get("at-web", {})
    need(bool(web.get("attributes", {}).get("backchannel.logout.url")), "at-web: backchannel URL")
    need(clients.get("at-mobile", {}).get("publicClient") is True, "at-mobile must be public")
    admin = clients.get("at-admin-svc", {})
    need(admin.get("serviceAccountsEnabled") is True, "at-admin-svc needs a service account")
    need(admin.get("standardFlowEnabled") is False, "at-admin-svc must not use browser flows")
    for user in realm.get("users", []):
        granted = set(user.get("clientRoles", {}).get("realm-management", []))
        need(granted <= ADMIN_SVC_ROLES, f"service account roles too broad: {granted}")
        need("credentials" not in user, "realm file must not carry user credentials")
    need(len(realm.get("users", [])) == 1, "only the service account user may be imported")
    for client in clients.values():
        for mapper in client.get("protocolMappers", []):
            claim = str(mapper.get("config", {}).get("claim.name", ""))
            need(
                not re.search(r"tenant|branch|role|grant", claim, re.I),
                "authorization claims must not be mapped into tokens (I02)",
            )

    def scan(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if SECRET_KEYS.search(key) and isinstance(value, str) and value:
                    need(
                        bool(PLACEHOLDER.match(value)), f"literal secret-like value at {path}.{key}"
                    )
                scan(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, item in enumerate(node):
                scan(item, f"{path}[{index}]")

    clean = {k: v for k, v in realm.items() if k not in {"passwordPolicy"}}
    scan(clean, "realm")
    return problems
