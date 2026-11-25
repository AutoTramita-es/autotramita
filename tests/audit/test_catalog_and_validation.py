"""F2-T03 / AC-AUD-04, AC-AUD-05: the catalog and the validator. No database needed."""

import uuid
from typing import Any

import pytest
from app.audit.catalog import CATALOG, Kind
from app.audit.models import ActorType, AuditEvent, Category, Outcome
from app.audit.record import AuditValidationError, ip_prefix, ua_family, validate

SAMPLE: dict[Kind, Any] = {"code": "WEB", "int": 3, "bool": True, "uuid": str(uuid.uuid4())}
SPEC_ACTIONS = {  # AT-02 section 9.2, expanded
    "auth.login.succeeded", "auth.login.failed", "auth.logout", "auth.callback.rejected",
    "auth.token.invalid", "identity.user.provisioned", "identity.link.conflict",
    "identity.email.verified", "identity.email.changed", "identity.email.change_reviewed",
    "identity.user.deactivated",
    "identity.user.blocked", "identity.user.reactivated", "session.created", "session.revoked",
    "session.expired_detected", "session.context.changed", "session.theft_suspected",
    "security.password.changed", "security.password.recovery.requested",
    "security.password.recovery.limited", "security.mfa.enrolled", "security.mfa.removed",
    "security.step_up.succeeded", "security.step_up.failed", "security.settings.changed",
    "authz.platform_grant.requested", "authz.platform_grant.approved",
    "authz.platform_grant.activated", "authz.platform_grant.revoked",
    "authz.platform_grant.used", "authz.platform_grant.expired", "authz.denied",
    "admin.audit.viewed", "admin.user.searched",
}  # fmt: skip


def event(action: str, **kw: Any) -> AuditEvent:
    return AuditEvent(action=action, outcome=Outcome.SUCCESS, actor_type=ActorType.SYSTEM, **kw)


def test_catalog_covers_exactly_the_specified_actions() -> None:
    assert set(CATALOG) == SPEC_ACTIONS


@pytest.mark.parametrize("action", sorted(CATALOG))
def test_every_action_accepts_its_own_allowlisted_details(action: str) -> None:
    spec = CATALOG[action]
    assert isinstance(spec.category, Category)
    details = {key: SAMPLE[kind] for key, kind in spec.details.items()}
    assert validate(event(action, details=details)) == {k: v for k, v in details.items()}


def test_unknown_action_and_unlisted_detail_keys_are_rejected() -> None:
    with pytest.raises(AuditValidationError):
        validate(event("auth.something.else"))
    with pytest.raises(AuditValidationError):
        validate(event("auth.logout", details={"note": "free text"}))
    with pytest.raises(AuditValidationError):
        validate(event("auth.logout", details={"client_type": "WEB", "extra": "x"}))


@pytest.mark.parametrize(
    "value",
    [
        "my password is x", "Bearer abcdefghijkl", "person@example.test", "a@b.co",
        "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.payload", "set-cookie", "client_secret",
        "refresh_token", "id_token", "code_verifier", "AUTHORIZATION",
    ],
)  # fmt: skip
def test_secret_like_values_are_rejected_in_details(value: str) -> None:
    with pytest.raises(AuditValidationError):
        validate(event("auth.callback.rejected", details={"reason": value}))


@pytest.mark.parametrize(
    ("action", "details"),
    [
        ("auth.logout", {"client_type": 5}),
        ("auth.logout", {"client_type": "has space"}),
        ("auth.logout", {"client_type": "x" * 65}),
        ("auth.logout", {"client_type": ""}),
        ("session.revoked", {"count": True}),
        ("session.revoked", {"count": -1}),
        ("session.revoked", {"count": "3"}),
        ("authz.platform_grant.used", {"grant_id": "not-a-uuid", "grant_type": "X"}),
        ("auth.token.invalid", {"reason": ["list"]}),
    ],
)
def test_wrongly_typed_or_shaped_values_are_rejected(action: str, details: dict[str, Any]) -> None:
    with pytest.raises(AuditValidationError):
        validate(event(action, details=details))


def test_validation_errors_never_echo_the_value() -> None:
    with pytest.raises(AuditValidationError) as caught:
        validate(event("auth.callback.rejected", details={"reason": "leak me@example.test"}))
    assert "example.test" not in str(caught.value) and "leak" not in str(caught.value)


def test_reason_code_target_and_prefix_are_checked() -> None:
    validate(event("auth.logout", reason_code="USER_REQUEST", ip_prefix="192.0.2.0/24"))
    for bad in (
        {"reason_code": "lower"}, {"reason_code": "X" * 61}, {"target_type": "has space"},
        {"ip_prefix": "192.0.2.7/32"}, {"ip_prefix": "192.0.2.0/25"}, {"ip_prefix": "nonsense"},
        {"ip_prefix": "2001:db8:1:2::/64"}, {"ua_family": "Mozilla/5.0 (X11)"},
    ):  # fmt: skip
        with pytest.raises(AuditValidationError):
            validate(event("auth.logout", **bad))


def test_ip_prefix_truncates_and_never_returns_a_full_address() -> None:
    assert ip_prefix("203.0.113.77") == "203.0.113.0/24"
    assert ip_prefix("2001:db8:aaaa:bbbb:cccc::1") == "2001:db8:aaaa::/48"
    assert ip_prefix("::ffff:198.51.100.9") == "198.51.100.0/24"
    assert ip_prefix("not an ip") is None and ip_prefix(None) is None and ip_prefix("") is None


def test_ua_family_is_coarse() -> None:
    chrome = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    assert ua_family(chrome) == "Chrome"
    assert ua_family("Mozilla/5.0 Firefox/121.0") == "Firefox"
    assert ua_family("Dart/3.2 (dart:io)") == "Dart"
    assert ua_family("curl/8.0") == "Other" and ua_family(None) is None
