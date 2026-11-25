"""Static policy checks for Keycloak realm files (F2-T01, AC-KC-02). No Keycloak needed."""

from __future__ import annotations

import json
import re
from typing import Any

from app.auth.idp import SECOND_FACTOR_TYPES
from app.core.config import RateLimitSettings

# (authenticator or "flow:<alias>", requirement, authenticator configuration or None)
Step = tuple[str, str, dict[str, str] | None]

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
    "delete_credential": False,  # no person removes a credential at the provider (F-1R-B)
    "idp_link": True,
    "CONFIGURE_RECOVERY_AUTHN_CODES": True,
    "at-disable-mfa": True,  # the provider's controlled switch-off, started by the application
    "update_user_locale": True,
}
# Every credential change and the switch-off start with a fresh sign-in (``max_auth_age`` 0); the
# provider then checks the proof of that sign-in when the form is submitted.
ACTION_CONFIG = {
    "CONFIGURE_TOTP": {"max_auth_age": "0"},
    "CONFIGURE_RECOVERY_AUTHN_CODES": {"max_auth_age": "0", "warning_threshold": "4"},
    "UPDATE_PASSWORD": {"max_auth_age": "0"},
    "webauthn-register": {"max_auth_age": "0"},
    "webauthn-register-passwordless": {"max_auth_age": "0"},
    "at-disable-mfa": {"max_auth_age": "0"},
}
GUARD = "at-security-guard"  # the provider's first sign-in step; without the provider no sign-in
MANDATORY = "at_mfa_mandatory"
# The authenticator that proves each kind of second factor the application knows (F-1R). A kind
# without one would be offered a new one-time code after the password alone.
FACTOR_AUTHENTICATORS = {
    "otp": "auth-otp-form",
    "webauthn": "webauthn-authenticator",
    "webauthn-passwordless": "webauthn-authenticator-passwordless",
    "recovery-authn-codes": "auth-recovery-authn-code-form",
}
assert set(FACTOR_AUTHENTICATORS) == SECOND_FACTOR_TYPES
MARKER = "at_mfa_required"
_CODE = FACTOR_AUTHENTICATORS["recovery-authn-codes"]
_PERMANENT = [name for name in FACTOR_AUTHENTICATORS.values() if name != _CODE]


def _any_of(names: list[str]) -> list[Step]:
    return [(name, "ALTERNATIVE", None) for name in names]


def _ran(flow: str, result: str = "executed") -> Step:
    return (
        "conditional-sub-flow-executed",
        "REQUIRED",
        {"flow_to_check": flow, "check_result": result},
    )


def _used(credentials: str, included: str) -> Step:
    return (
        "conditional-credential",
        "REQUIRED",
        {"credentials": credentials, "included": included},
    )


def _marked(negated: str) -> Step:
    config = {
        "attribute_name": MARKER,
        "attribute_expected_value": "true",
        "not": negated,
        "include_group_attributes": "false",
        "regex": "false",
    }
    return ("conditional-user-attribute", "REQUIRED", config)


def _level(number: str, max_age: str) -> Step:
    config = {
        "loa-condition-level": number,
        "loa-store-in-user-session": "true",
        "loa-max-age": max_age,
    }
    return ("conditional-level-of-authentication", "REQUIRED", config)


def _sub(name: str, requirement: str = "CONDITIONAL") -> Step:
    return (f"flow:browser-{name}", requirement, None)


def _step(name: str, requirement: str = "REQUIRED") -> Step:
    return (name, requirement, None)


_CONFIGURED = _step("conditional-user-configured")
_ALLOW = _step("allow-access-authenticator")
_DENY = _step("deny-access-authenticator")
_PERMANENT_TYPES = "otp##webauthn##webauthn-passwordless"
_USED_CODE = _used("recovery-authn-codes", "true")


def _probe(name: str, kinds: list[str]) -> dict[str, list[Step]]:
    """Executed, asking nothing, exactly for a person who has one of ``kinds``."""
    return {
        f"browser-probe-{name}": [
            _CONFIGURED,
            _sub(f"probe-{name}-pass", "REQUIRED"),
            *_any_of(kinds),
        ],
        f"browser-probe-{name}-pass": [_ALLOW],
    }


# Every authentication flow of the realm, exactly: (authenticator or sub-flow, requirement,
# configuration) in execution order. Anything else could let a level be reached without its proof.
FLOWS: dict[str, list[Step]] = {
    "browser-loa": [
        _step("auth-cookie", "ALTERNATIVE"),
        _sub("loa-forms", "ALTERNATIVE"),
    ],
    # The order 1, 3, 2, 4 decides the level each kind of credential belongs to.
    "browser-loa-forms": [_step(GUARD), *[_sub(f"loa-{number}") for number in (1, 3, 2, 4)]],
    "browser-loa-1": [
        _level("1", "43200"),
        _step("auth-username-password-form"),
        _sub("probe-permanent"),
        _sub("probe-codes"),
        _sub("deny-codes-only"),
        _sub("deny-marked-without-factor"),
        _sub("loa-1-factor"),
        _sub("probe-codes-left"),
        _sub("loa-1-codes-spent"),
        _sub("loa-1-last-code"),
    ],
    **_probe("permanent", _PERMANENT),
    **_probe("codes", [_CODE]),
    **_probe("codes-left", [_CODE]),
    # recovery codes alone are no proof of a permanent factor: refused before a code is asked
    "browser-deny-codes-only": [
        _ran("browser-probe-permanent", "not-executed"),
        _ran("browser-probe-codes"),
        _DENY,
    ],
    "browser-deny-marked-without-factor": [
        _marked("false"),
        _ran("browser-probe-permanent", "not-executed"),
        _ran("browser-probe-codes", "not-executed"),
        _DENY,
    ],
    "browser-loa-1-factor": [_CONFIGURED, *_any_of(list(FACTOR_AUTHENTICATORS.values()))],
    "browser-loa-1-codes-spent": [
        _USED_CODE,
        _ran("browser-probe-codes-left", "not-executed"),
        (
            "user-session-limits",
            "REQUIRED",
            {
                "userRealmLimit": "1",
                "userClientLimit": "0",
                "behavior": "Terminate oldest session",
            },
        ),
    ],
    "browser-loa-1-last-code": [
        _USED_CODE,
        _ran("browser-probe-codes-left", "not-executed"),
        _ran("browser-probe-permanent"),
        *_any_of(_PERMANENT),
    ],
    "browser-loa-3": [
        _level("3", "0"),
        _sub("loa-3-prove"),
        _sub("loa-3-enrol"),
        _sub("loa-3-proven"),
    ],
    "browser-loa-3-prove": [_used(_PERMANENT_TYPES, "false"), _CONFIGURED, *_any_of(_PERMANENT)],
    "browser-loa-3-enrol": [
        _used(_PERMANENT_TYPES, "false"),
        _ran("browser-loa-3-prove", "not-executed"),
        _marked("true"),
        _step("auth-otp-form"),
    ],
    "browser-loa-3-proven": [_used(_PERMANENT_TYPES, "true"), _ALLOW],
    "browser-loa-2": [
        _level("2", "600"),
        _sub("loa-2-factor"),
        _sub("loa-2-enrol"),
        _sub("loa-2-proven"),
        _sub("loa-2-proven-permanent"),
    ],
    "browser-loa-2-factor": [
        _ran("browser-loa-1-factor", "not-executed"),
        _ran("browser-loa-3-prove", "not-executed"),
        _CONFIGURED,
        *_any_of(_PERMANENT),
    ],
    "browser-loa-2-enrol": [
        _ran("browser-loa-1-factor", "not-executed"),
        _ran("browser-loa-3-prove", "not-executed"),
        _ran("browser-loa-2-factor", "not-executed"),
        _marked("true"),
        _step("auth-otp-form"),
    ],
    "browser-loa-2-proven": [_ran("browser-loa-1-factor"), _ALLOW],
    "browser-loa-2-proven-permanent": [
        _ran("browser-loa-1-factor", "not-executed"),
        _ran("browser-loa-3-prove"),
        _ALLOW,
    ],
    "browser-loa-4": [_level("4", "0"), _ALLOW, _step(_CODE, "DISABLED")],
    "direct-grant-denied": [_DENY],
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


def _profile_permissions(realm: dict[str, Any], name: str) -> Any:
    components = realm.get("components", {}).get("org.keycloak.userprofile.UserProfileProvider", [])
    for component in components:
        for text in component.get("config", {}).get("kc.user.profile.config", []):
            profile = json.loads(text)
            if profile.get("unmanagedAttributePolicy") not in (None, "ADMIN_VIEW", "ADMIN_EDIT"):
                return None
            for attribute in profile.get("attributes", []):
                if attribute.get("name") == name:
                    return attribute.get("permissions")
    return None


def _names_credential_types(path: str, value: Any) -> bool:
    """The credential condition lists kinds of credential, not credentials."""
    return (
        path.startswith("realm.authenticatorConfig[")
        and isinstance(value, str)
        and set(value.split("##")) <= SECOND_FACTOR_TYPES
    )


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
    for alias, expected in FLOWS.items():
        executions = sorted(
            flows.get(alias, {}).get("authenticationExecutions", []),
            key=lambda e: e.get("priority", 0),
        )
        actual = [
            (
                f"flow:{e['flowAlias']}" if e.get("authenticatorFlow") else e.get("authenticator"),
                e.get("requirement"),
                configs.get(e["authenticatorConfig"], {}) if "authenticatorConfig" in e else None,
            )
            for e in executions
        ]
        need(actual == expected, f"flow {alias} differs from the reviewed one: {actual}")

    for attribute in (MARKER, MANDATORY):
        need(
            _profile_permissions(realm, attribute) == {"view": ["admin"], "edit": ["admin"]},
            f"the attribute {attribute} must be visible and changeable by administrators only",
        )
    need(
        "CUSTOM_REQUIRED_ACTION_ERROR" in realm.get("enabledEventTypes", []),
        "refused credential changes must be stored as events",
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
    for alias, config in ACTION_CONFIG.items():
        need(
            actions.get(alias, {}).get("config") == config,
            f"required action {alias}: a credential may change only after a fresh authentication",
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
    # Keycloak 26.8 accepts an admin API token only with the kc-admin-api scope (its audience);
    # without it the application's administration (F-0, account actions) fails.
    need(
        "kc-admin-api" in admin.get("defaultClientScopes", []),
        "at-admin-svc needs the kc-admin-api scope for the admin API",
    )
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
                if key == "credentials" and _names_credential_types(path, value):
                    continue
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
