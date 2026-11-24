"""D37 notification transport exposes failures to the future retry worker."""

import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from uuid import uuid4

import pytest
from app.auth.security.notify import Notice, NoticeKind, SmtpNotifier
from app.auth.settings import AuthSettings


def test_durable_notice_reuses_message_id_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def send_message(self, message: EmailMessage) -> dict[str, object]:
            sent.append(message)
            return {}

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = AuthSettings.model_validate(
        {
            "AUTH_OIDC_ISSUER": "https://auth.example.test/realms/test",
            "AUTH_NOTIFY_MODE": "smtp",
            "AUTH_SMTP_HOST": "localhost",
            "AUTH_SMTP_FROM": "security@example.test",
        }
    )
    notifier = SmtpNotifier(settings)
    notice = Notice(NoticeKind.SESSIONS_REVOKED, "user@example.test", datetime.now(UTC))
    job_id = uuid4()
    notifier.send_durable(notice, job_id)
    notifier.send_durable(notice, job_id)
    assert len(sent) == 2
    assert sent[0]["Message-ID"] == sent[1]["Message-ID"] == f"<{job_id}@autotramita.es>"
    with pytest.raises(ValueError):
        notifier.send_durable(Notice(notice.kind, "bad\r\nBcc: x", notice.occurred_at), job_id)

    class Down(FakeSMTP):
        def send_message(self, message: EmailMessage) -> dict[str, object]:
            raise smtplib.SMTPException("unavailable")

    monkeypatch.setattr(smtplib, "SMTP", Down)
    with pytest.raises(smtplib.SMTPException):
        notifier.send_durable(notice, job_id)


def test_verification_link_is_sent_only_to_configured_origin(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app.auth.credentials import new_credential

    sent: list[EmailMessage] = []

    class FakeSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def send_message(self, message: EmailMessage) -> dict[str, object]:
            sent.append(message)
            return {}

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = AuthSettings.model_validate(
        {
            "AUTH_OIDC_ISSUER": "https://auth.example.test/realms/test",
            "AUTH_WEB_ORIGIN": "https://app.example.test",
            "AUTH_NOTIFY_MODE": "smtp",
            "AUTH_SMTP_HOST": "localhost",
            "AUTH_SMTP_FROM": "security@example.test",
        }
    )
    notifier = SmtpNotifier(settings)
    token, _ = new_credential()
    operation = uuid4()
    notifier.send_email_change_verification(
        to="new@example.test",
        origin="https://app.example.test",
        operation_id=operation,
        token=token,
    )
    body = sent[0].get_content()
    assert f"#id={operation}&token={token}" in body
    assert token not in caplog.text
    with pytest.raises(ValueError):
        notifier.send_email_change_verification(
            to="new@example.test", origin="https://evil.test", operation_id=operation, token=token
        )
    assert len(sent) == 1
