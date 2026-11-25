"""F2-T09 unit tests that need no database: the admin client, notices, settings, markers and the
static rules around the new modules (AC-POL-11, AC-POL-14)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from app.auth.idp import IdpAdminError
from app.auth.idp_admin import KeycloakAdmin
from app.auth.security.notify import (
    DisabledNotifier,
    Notice,
    NoticeKind,
    SmtpNotifier,
    build_notifier,
    render,
    send_quietly,
)
from app.auth.settings import AuthSettings
from app.core.config import RateLimitSettings
from pydantic import ValidationError
from tests.identity.kc import SMTP_PORT, SmtpSink

ROOT = Path(__file__).resolve().parents[3]
ISSUER = "https://auth.test.invalid/realms/autotramita-test"


def settings(**extra: Any) -> AuthSettings:
    return AuthSettings.model_validate(
        {
            "AUTH_OIDC_ISSUER": ISSUER,
            "AUTH_ADMIN_CLIENT_SECRET": "svc-secret-not-real",
            "AUTH_WEB_ORIGIN": "https://autotramita.example",
            **extra,
        }
    )


# --- admin client ------------------------------------------------------------------------------
class Provider:
    """A tiny Keycloak double behind httpx.MockTransport."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self.users: list[dict[str, Any]] = [
            {"id": "u-1", "email": "a@example.test", "enabled": True, "emailVerified": True}
        ]
        self.status = 200
        self.person: dict[str, Any] = {}  # the representation read by id

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/protocol/openid-connect/token"):
            self.token_calls += 1
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 60})
        if self.status != 200:
            return httpx.Response(self.status, json={"errorMessage": "secret detail"})
        if request.url.path.endswith("/users") and request.method == "GET":
            return httpx.Response(200, json=self.users)
        parent, _, last = request.url.raw_path.decode().split("?")[0].rpartition("/")
        if request.method == "GET" and parent.endswith("/users"):
            return httpx.Response(200, json={"id": unquote(last), **self.person})
        if request.url.path.endswith("/credentials"):
            return httpx.Response(
                200,
                json=[
                    {"id": "c1", "type": "password", "createdDate": 5000, "secretData": "x"},
                    {"id": "c2", "type": "otp", "createdDate": None},
                ],
            )
        return httpx.Response(204)


def admin_with(provider: Provider, now: list[float] | None = None) -> KeycloakAdmin:
    clock = now or [0.0]
    return KeycloakAdmin(
        settings(),
        client=httpx.Client(transport=httpx.MockTransport(provider)),
        clock=lambda: clock[0],
    )


def test_admin_url_is_derived_from_the_issuer_and_needs_a_secret() -> None:
    assert settings().admin_base_url == "https://auth.test.invalid/admin/realms/autotramita-test"
    with pytest.raises(IdpAdminError):
        KeycloakAdmin(AuthSettings.model_validate({"AUTH_OIDC_ISSUER": ISSUER}))


def test_the_service_token_is_cached_until_shortly_before_it_expires() -> None:
    provider, clock = Provider(), [0.0]
    admin = admin_with(provider, clock)
    admin.find_user_by_email("a@example.test")
    admin.find_user_by_email("a@example.test")
    assert provider.token_calls == 1
    clock[0] = 45.0  # 60 s lifetime minus the refresh margin
    admin.find_user_by_email("a@example.test")
    assert provider.token_calls == 2


def test_lookup_by_email_is_exact_and_ambiguity_means_no_account() -> None:
    provider = Provider()
    admin = admin_with(provider)
    found = admin.find_user_by_email("a@example.test")
    assert found is not None and found.subject == "u-1" and found.enabled and found.email_verified
    query = provider.requests[-1].url.params
    assert query["exact"] == "true" and query["email"] == "a@example.test"
    provider.users = [{"id": "u-2", "email": "other@example.test"}]
    assert admin.find_user_by_email("a@example.test") is None
    provider.users = [
        {"id": "u-3", "email": "a@example.test"},
        {"id": "u-4", "email": "A@example.test"},
    ]
    assert admin.find_user_by_email("a@example.test") is None


def test_actions_email_carries_lifespan_client_and_redirect_but_no_secret_in_the_url() -> None:
    provider = Provider()
    admin_with(provider).send_actions_email(
        "u/1",
        ["UPDATE_PASSWORD"],
        lifespan_seconds=1800,
        redirect_uri="https://autotramita.example/",
    )
    request = provider.requests[-1]
    assert request.method == "PUT"
    assert request.url.raw_path.split(b"?")[0].endswith(b"/users/u%2F1/execute-actions-email")
    assert dict(request.url.params) == {
        "lifespan": "1800",
        "redirect_uri": "https://autotramita.example/",
        "client_id": "at-web",
    }
    assert json.loads(request.content) == ["UPDATE_PASSWORD"]
    assert request.headers["authorization"] == "Bearer tok"


def writes(provider: Provider) -> list[tuple[str, str, Any]]:
    return [
        (r.method, r.url.path.rpartition("/")[2], json.loads(r.content))
        for r in provider.requests
        if r.method != "GET" and not r.url.path.endswith("/token")
    ]


def send_reset(provider: Provider) -> None:
    admin_with(provider).send_actions_email(
        "u-1",
        ["UPDATE_PASSWORD"],
        lifespan_seconds=1800,
        redirect_uri="https://autotramita.example/",
    )


def test_pending_credential_setups_are_withdrawn_before_any_actions_email() -> None:
    """The link runs whatever is pending, without a factor (F-1R-B through e-mail)."""
    provider = Provider()
    provider.person = {
        "requiredActions": [
            "CONFIGURE_TOTP",
            "VERIFY_EMAIL",
            "CONFIGURE_RECOVERY_AUTHN_CODES",
            "webauthn-register",
            "webauthn-register-passwordless",
            "delete_credential",
        ]
    }
    send_reset(provider)
    assert writes(provider) == [
        ("PUT", "u-1", {"requiredActions": ["VERIFY_EMAIL"]}),
        ("PUT", "execute-actions-email", ["UPDATE_PASSWORD"]),
    ]
    untouched = Provider()
    untouched.person = {"requiredActions": ["VERIFY_EMAIL"]}
    send_reset(untouched)
    assert [w[1] for w in writes(untouched)] == ["execute-actions-email"]


@pytest.mark.parametrize("person", [{"id": "somebody-else"}, {"requiredActions": "x"}])
def test_no_email_is_sent_when_pending_setups_cannot_be_checked(person: dict[str, Any]) -> None:
    provider = Provider()
    provider.person = person
    with pytest.raises(IdpAdminError):
        send_reset(provider)
    assert writes(provider) == []


@pytest.mark.parametrize(
    ("attributes", "obliged"),
    [
        (None, False),
        ({}, False),
        ({"at_mfa_required": ["true"]}, True),
        ({"at_mfa_required": ["false"]}, False),
    ],
)
def test_the_factor_obligation_is_read_from_the_realm_attribute(
    attributes: dict[str, Any] | None, obliged: bool
) -> None:
    provider = Provider()
    provider.person = {} if attributes is None else {"attributes": attributes}
    assert admin_with(provider).has_factor_obligation("u-1") is obliged


def test_credentials_are_listed_without_secret_data() -> None:
    credentials = admin_with(Provider()).list_credentials("u-1")
    assert [(c.id, c.type, c.created_ms) for c in credentials] == [
        ("c1", "password", 5000),
        ("c2", "otp", None),
    ]
    assert "secret" not in repr(credentials)


def test_failures_become_one_error_that_never_carries_the_response_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = Provider()
    admin = admin_with(provider)
    admin.find_user_by_email("a@example.test")
    provider.status = 500
    with pytest.raises(IdpAdminError) as caught:
        admin.delete_credential("u-1", "c1")
    assert "secret detail" not in str(caught.value) and "svc-secret" not in str(caught.value)
    assert "secret detail" not in caplog.text and "svc-secret" not in caplog.text


def test_a_token_failure_is_an_admin_error_too() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized_client"})

    admin = KeycloakAdmin(settings(), client=httpx.Client(transport=httpx.MockTransport(refuse)))
    with pytest.raises(IdpAdminError):
        admin.find_user_by_email("a@example.test")


# --- notices (AC-POL-11) --------------------------------------------------------------------------
WHEN = datetime(2026, 11, 24, 12, 30, tzinfo=UTC)


@pytest.mark.parametrize("kind", list(NoticeKind))
def test_every_notice_is_spanish_short_and_carries_nothing_but_the_kind_and_the_time(
    kind: NoticeKind,
) -> None:
    subject, body = render(Notice(kind, "person@example.test", WHEN))
    assert subject.startswith("AutoTramita: ") and "24/11/2026 12:30 UTC" in body
    assert "@" not in subject + body and "http" not in (subject + body).lower()
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}", body)  # no identifiers
    assert "contraseña" in body.lower() or "factor" in body.lower() or "sesiones" in body.lower()
    assert len(body) < 600


def test_production_default_sends_nothing_and_smtp_needs_a_host() -> None:
    assert isinstance(build_notifier(settings()), DisabledNotifier)
    with pytest.raises(ValidationError):
        settings(AUTH_NOTIFY_MODE="smtp")
    with pytest.raises(ValidationError):
        settings(AUTH_NOTIFY_MODE="carrier-pigeon")
    assert isinstance(
        build_notifier(
            settings(
                AUTH_NOTIFY_MODE="smtp",
                AUTH_SMTP_HOST="127.0.0.1",
                AUTH_SMTP_FROM="no-reply@example.test",
            )
        ),
        SmtpNotifier,
    )


def test_smtp_notifier_delivers_to_a_dev_mail_sink_and_survives_a_dead_one() -> None:
    sink = SmtpSink()
    sink.start()
    try:
        notifier = SmtpNotifier(
            settings(
                AUTH_NOTIFY_MODE="smtp",
                AUTH_SMTP_HOST="127.0.0.1",
                AUTH_SMTP_PORT=SMTP_PORT,
                AUTH_SMTP_FROM="no-reply@autotramita.example",
            )
        )
        notifier.send(Notice(NoticeKind.PASSWORD_CHANGED, "p-notice@example.test", WHEN))
        mails = sink.for_recipient("p-notice@example.test")
        assert mails and "contraseña" in mails[0]["body"]
    finally:
        sink.stop()
    notifier.send(
        Notice(NoticeKind.PASSWORD_CHANGED, "p@example.test", WHEN)
    )  # nobody listens: no raise
    notifier.send(
        Notice(NoticeKind.PASSWORD_CHANGED, "a@example.test\r\nBcc: x@example.test", WHEN)
    )


def test_a_failing_notifier_never_reaches_the_caller() -> None:
    class Boom:
        def send(self, notice: Notice) -> None:
            raise RuntimeError("down")

    send_quietly(Boom(), Notice(NoticeKind.MFA_ENROLLED, "p@example.test", WHEN))


# --- settings and documentation (AC-POL-14) ---------------------------------------------------------
def test_rate_limit_settings_say_the_application_enforces_recovery() -> None:
    doc = RateLimitSettings.__doc__ or ""
    assert "enforced by the application" in doc and "not by this application layer" not in doc
    assert RateLimitSettings().password_recovery_per_hour == 3
    assert RateLimitSettings().keycloak_max_failed_logins == 5


def test_recovery_link_lifetime_and_hmac_key_are_configuration() -> None:
    assert settings().recovery_link_minutes == 30 and settings().security_hmac_key is None
    assert settings(AUTH_SECURITY_HMAC_KEY="k" * 32).security_hmac_key is not None


def test_only_the_security_modules_and_the_admin_client_use_the_admin_secret() -> None:
    users = [
        p.relative_to(ROOT).as_posix()
        for p in (ROOT / "app").rglob("*.py")
        if "admin_client_secret" in p.read_text()
    ]
    assert sorted(users) == ["app/auth/idp_admin.py", "app/auth/runtime.py", "app/auth/settings.py"]


def test_security_modules_log_fixed_messages_only() -> None:
    """No f-string, %-format or positional argument in a log call: values cannot leak."""
    sources = "".join(p.read_text() for p in (ROOT / "app/auth/security").glob("*.py"))
    sources += (ROOT / "app/auth/idp_admin.py").read_text()
    calls = re.findall(r"log\.\w+\(\s*(.*?)\)\n", sources, flags=re.S)
    assert calls
    for call in calls:
        assert re.match(
            r'^"[^"{%]*"(,\s*extra=\{"fields": \{[^}]*\}\})?,?\s*$', " ".join(call.split())
        ), call
