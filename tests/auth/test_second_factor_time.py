"""F2-T09-REC F-2: how long a step-up counts. No infrastructure.

The window is measured from an authentication that really happened. For level two that is the
moment the identity provider checked a second factor (the ``loa_map`` claim); neither the time
the application learned about it nor ``auth_time`` stands in for it."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from app.auth.errors import StepUpRequired
from app.auth.security.step_up import window_seconds
from app.auth.sessions import service as sessions
from app.auth.sessions.models import AuthLevel, ClientType, UserSession
from app.auth.tokens import IdTokenValidator, JwksCache, TokenValidator, VerifiedToken
from app.auth.web.stepup import (
    StepUpPurpose,
    authorization_params,
    require_step_up,
    require_token_step_up,
    second_factor_time,
)
from tests.auth.fake_idp import DROP, ISSUER, NOW, FakeIdp
from tests.auth.security.test_security_units import settings

T = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)


def validators() -> tuple[FakeIdp, TokenValidator, IdTokenValidator]:
    idp, configured = FakeIdp(), settings(AUTH_OIDC_ISSUER=ISSUER)
    cache = JwksCache(idp.fetch, ttl_seconds=600, min_refresh_seconds=0)
    clock = lambda: NOW  # noqa: E731
    return (
        idp,
        TokenValidator(configured, cache, clock=clock),
        IdTokenValidator(configured, cache, clock=clock),
    )


@pytest.mark.parametrize(
    ("claim", "expected"),
    [
        (json.dumps({"1": 100, "2": 200}), 200),
        ({"1": 100, "2": 200}, 200),
        (json.dumps({"1": 100}), None),  # a password only
        (DROP, None),  # a realm without the mapper
        (None, None),
        ("", None),
        ("not json", None),
        ("[2]", None),
        ('"2"', None),
        (200, None),
        (json.dumps({"2": "200"}), None),
        (json.dumps({"2": 200.5}), None),
        (json.dumps({"2": True}), None),
        (json.dumps({"2": 0}), None),
        (json.dumps({"2": -5}), None),
        (json.dumps({"2": 10**12}), None),
        (json.dumps({"2": 200, "pad": "x" * 600}), None),
        ("[" * 400, None),
    ],
)
def test_only_a_well_formed_level_two_time_is_read(claim: Any, expected: int | None) -> None:
    idp, access, identity = validators()
    token = idp.sign(idp.claims(acr="loa2", loa_map=claim))
    assert access.validate(token).second_factor_at == expected
    id_token = idp.sign(idp.id_claims("n", acr="loa2", loa_map=claim))
    assert identity.validate(id_token, client_id="at-web", nonce="n").second_factor_at == expected


def test_evidence_needs_level_two_a_time_and_a_time_that_is_not_in_the_future() -> None:
    at = int(T.timestamp()) - 120
    assert second_factor_time("loa2", at, now=T, leeway_seconds=30) == T - timedelta(seconds=120)
    for acr in ("loa1", None, "2", "LOA2"):
        assert second_factor_time(acr, at, now=T, leeway_seconds=30) is None
    assert second_factor_time("loa2", None, now=T, leeway_seconds=30) is None
    ahead = int(T.timestamp()) + 31
    assert second_factor_time("loa2", ahead, now=T, leeway_seconds=30) is None
    # inside the clock leeway: accepted, but never later than now (no longer window)
    assert second_factor_time("loa2", ahead - 2, now=T, leeway_seconds=30) == T


def test_both_step_up_purposes_ask_the_provider_to_authenticate_now() -> None:
    for purpose, level in ((StepUpPurpose.MFA, "loa2"), (StepUpPurpose.REAUTHENTICATE, "loa1")):
        asked = authorization_params(purpose)
        assert (asked.acr_values, asked.prompt, asked.max_age) == (level, "login", 0)


def web_session(**changes: Any) -> UserSession:
    values: dict[str, Any] = {
        "id": uuid4(), "user_id": uuid4(), "client_type": ClientType.WEB, "kc_session_id": "k",
        "active_tenant_id": None, "active_branch_id": None, "active_membership_id": None,
        "context_version": 1, "auth_time": T, "auth_level": AuthLevel.LOA1, "step_up_at": None,
        "device_label": None, "platform": None, "app_version": None, "ua_family": None,
        "country_code": None, "created_at": T, "last_activity_at": T,
        "idle_expires_at": T + timedelta(hours=1), "absolute_expires_at": T + timedelta(hours=2),
        "revoked_at": None, "revoked_reason": None, "version": 1,
    }  # fmt: skip
    values.update(changes)
    return UserSession(**values)


@pytest.mark.parametrize("window", [600, 300], ids=["ten_minutes", "privileged_five_minutes"])
def test_a_web_session_counts_level_two_from_the_factor_to_the_second(window: int) -> None:
    mfa = web_session(auth_level=AuthLevel.LOA2, step_up_at=T)
    at_limit = T + timedelta(seconds=window)
    require_step_up(mfa, level=AuthLevel.LOA2, max_age_seconds=window, now=at_limit)
    with pytest.raises(StepUpRequired) as expired:
        require_step_up(
            mfa,
            level=AuthLevel.LOA2,
            max_age_seconds=window,
            now=at_limit + timedelta(seconds=1),
        )
    assert f'max_age="{window}"' in expired.value.headers["WWW-Authenticate"]


def test_a_later_password_sign_in_never_renews_level_two() -> None:
    old_factor = web_session(
        auth_level=AuthLevel.LOA2, step_up_at=T, auth_time=T + timedelta(minutes=20)
    )
    now = T + timedelta(minutes=21)
    require_step_up(old_factor, level=AuthLevel.LOA1, max_age_seconds=600, now=now)
    with pytest.raises(StepUpRequired):
        require_step_up(old_factor, level=AuthLevel.LOA2, max_age_seconds=600, now=now)


def bearer(*, auth_time: int, factor: int | None, acr: str = "loa2") -> VerifiedToken:
    return VerifiedToken(
        subject="s", session_id="k", client_id="at-mobile", issued_at=int(T.timestamp()),
        expires_at=int(T.timestamp()) + 300, auth_time=auth_time, acr=acr, email=None,
        email_verified=None, second_factor_at=factor,
    )  # fmt: skip


@pytest.mark.parametrize("window", [600, 300], ids=["ten_minutes", "privileged_five_minutes"])
def test_a_bearer_token_counts_level_two_from_the_factor_not_from_its_own_age(window: int) -> None:
    factor = int(T.timestamp()) - window
    # issued just now (a refresh) and the password entered just now: neither counts
    token = bearer(auth_time=int(T.timestamp()), factor=factor)
    require_token_step_up(token, level=AuthLevel.LOA2, max_age_seconds=window, now=T)
    with pytest.raises(StepUpRequired):
        require_token_step_up(
            token, level=AuthLevel.LOA2, max_age_seconds=window, now=T + timedelta(seconds=1)
        )


@pytest.mark.parametrize(
    "token",
    [
        bearer(auth_time=int(T.timestamp()), factor=None),
        bearer(auth_time=int(T.timestamp()), factor=int(T.timestamp()), acr="loa1"),
        bearer(auth_time=int(T.timestamp()), factor=int(T.timestamp()) + 3600),
    ],
    ids=["no_factor_time", "level_one", "future"],
)
def test_a_bearer_token_without_usable_evidence_is_not_level_two(token: VerifiedToken) -> None:
    with pytest.raises(StepUpRequired):
        require_token_step_up(token, level=AuthLevel.LOA2, max_age_seconds=600, now=T)


def test_level_one_for_a_bearer_counts_the_newest_real_authentication() -> None:
    token = bearer(auth_time=int(T.timestamp()) - 3600, factor=int(T.timestamp()) - 60)
    require_token_step_up(token, level=AuthLevel.LOA1, max_age_seconds=600, now=T)
    stale = bearer(auth_time=int(T.timestamp()) - 3600, factor=None, acr="loa1")
    with pytest.raises(StepUpRequired):
        require_token_step_up(stale, level=AuthLevel.LOA1, max_age_seconds=600, now=T)


def test_the_configured_window_can_only_shorten_a_step_up() -> None:
    class Runtime:
        def __init__(self, minutes: int) -> None:
            self.settings = settings(AUTH_STEP_UP_WINDOW_MINUTES=minutes)

    assert window_seconds(Runtime(10), 900) == 600  # type: ignore[arg-type]
    assert window_seconds(Runtime(10), 300) == 300  # type: ignore[arg-type]
    assert window_seconds(Runtime(5), 600) == 300  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        settings(AUTH_STEP_UP_WINDOW_MINUTES=11)


def test_a_level_two_session_cannot_be_opened_without_the_factor_time() -> None:
    with pytest.raises(ValueError, match="second factor"):
        sessions.create_session(
            None,  # type: ignore[arg-type]  # refused before the database is touched
            user_id=uuid4(),
            client_type=ClientType.WEB,
            kc_session_id="k",
            auth_time=T,
            policy=None,  # type: ignore[arg-type]
            auth_level=AuthLevel.LOA2,
        )
