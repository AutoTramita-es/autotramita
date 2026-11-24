"""F2-T05 / AC-SES-01 (unit part), AC-SES-02 (policy), AC-SES-11 (credential shape)."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.auth import credentials
from app.auth.sessions.models import AuthLevel, ClientType, SessionPolicy, UserSession
from app.auth.settings import AuthSettings

ISSUER = "https://auth.test.invalid/realms/autotramita-test"


def test_credentials_have_256_bits_are_unique_and_only_the_hash_is_derivable() -> None:
    secrets = {credentials.new_credential()[0] for _ in range(200)}
    assert len(secrets) == 200
    secret, digest = credentials.new_credential()
    assert len(secret) == 43 and credentials.is_well_formed(secret)
    assert digest == hashlib.sha256(secret.encode()).digest() == credentials.hash_credential(secret)
    assert secret not in digest.hex() and len(digest) == 32


@pytest.mark.parametrize(
    "value",
    [None, 123, b"x" * 43, "", "short", "a" * 42, "a" * 44, "a" * 42 + "!", "a b" + "c" * 40,
     "é" + "a" * 42, "a" * 43 + "\n"],
)  # fmt: skip
def test_malformed_credentials_are_rejected_before_any_lookup(value: object) -> None:
    assert credentials.is_well_formed(value) is False


def test_constant_time_comparison() -> None:
    a = credentials.hash_credential("a" * 43)
    assert credentials.equal(a, credentials.hash_credential("a" * 43))
    assert not credentials.equal(a, credentials.hash_credential("b" * 43))


def test_policy_lifetimes_follow_the_accepted_values() -> None:
    policy = SessionPolicy.from_settings(AuthSettings.model_validate({"AUTH_OIDC_ISSUER": ISSUER}))
    assert policy.idle[ClientType.WEB] == timedelta(minutes=30)
    assert policy.absolute[ClientType.WEB] == timedelta(hours=12)
    assert policy.idle[ClientType.ADMIN_WEB] == timedelta(minutes=15)
    assert policy.absolute[ClientType.ADMIN_WEB] == timedelta(hours=8)
    assert policy.idle[ClientType.MOBILE] == timedelta(days=7)
    assert policy.absolute[ClientType.MOBILE] == timedelta(days=30)
    assert policy.max_sessions == 10 and policy.touch_interval == timedelta(seconds=60)


def make(**kw: object) -> UserSession:
    now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
    base: dict[str, object] = {
        "id": uuid.uuid4(), "user_id": uuid.uuid4(), "client_type": ClientType.WEB,
        "kc_session_id": "kc", "active_tenant_id": None, "active_branch_id": None,
        "active_membership_id": None, "context_version": 1, "auth_time": now,
        "auth_level": AuthLevel.LOA1, "step_up_at": None, "device_label": None, "platform": None,
        "app_version": None, "ua_family": None, "country_code": None, "created_at": now,
        "last_activity_at": now, "idle_expires_at": now + timedelta(minutes=30),
        "absolute_expires_at": now + timedelta(hours=12), "revoked_at": None,
        "revoked_reason": None, "version": 1,
    }  # fmt: skip
    return UserSession(**{**base, **kw})  # type: ignore[arg-type]


def test_live_means_not_revoked_and_before_both_deadlines() -> None:
    s = make()
    start = s.created_at
    assert s.is_live(start) and s.is_live(start + timedelta(minutes=29, seconds=59))
    assert s.is_expired(start + timedelta(minutes=30)) and not s.is_live(
        start + timedelta(minutes=30)
    )
    tight = make(
        idle_expires_at=start + timedelta(hours=13), absolute_expires_at=start + timedelta(hours=12)
    )
    assert not tight.is_live(start + timedelta(hours=12))
    assert not make(revoked_at=start, revoked_reason="LOGOUT").is_live(start)
