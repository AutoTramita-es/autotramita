"""D37 notification transport exposes failures to the future retry worker."""

import smtplib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.auth.security.notify import Notice, NoticeKind, SmtpNotifier
from app.auth.settings import AuthSettings


def test_durable_notice_reuses_message_id_and_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = []

    class FakeSMTP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def send_message(self, message: object) -> dict[str, object]:
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
        def send_message(self, message: object) -> dict[str, object]:
            raise smtplib.SMTPException("unavailable")

    monkeypatch.setattr(smtplib, "SMTP", Down)
    with pytest.raises(smtplib.SMTPException):
        notifier.send_durable(notice, job_id)
