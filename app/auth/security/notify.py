"""Security notices by e-mail (F2-T09, D27): a port, Spanish templates and an SMTP sender.

A notice carries a kind, the address it goes to and a time. It never carries a secret, a link, a
token, an address of the person other than the recipient, or any identifier (AC-POL-11).
Sending is best effort: a failing mail server never fails the request, and production sending
stays disabled until the provider decision (O15) is taken (``AUTH_NOTIFY_MODE=disabled``)."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from enum import StrEnum
from typing import Protocol

from app.auth.settings import AuthSettings

log = logging.getLogger(__name__)


class NoticeKind(StrEnum):
    PASSWORD_CHANGED = "PASSWORD_CHANGED"  # noqa: S105 - a notice name
    MFA_ENROLLED = "MFA_ENROLLED"
    MFA_REMOVED = "MFA_REMOVED"
    SESSIONS_REVOKED = "SESSIONS_REVOKED"
    PASSWORD_RESET_COMPLETED = "PASSWORD_RESET_COMPLETED"  # noqa: S105 - a notice name


@dataclass(frozen=True, slots=True)
class Notice:
    kind: NoticeKind
    to: str
    occurred_at: datetime


class SecurityNotifier(Protocol):
    def send(self, notice: Notice) -> None: ...


_WHAT = {
    NoticeKind.PASSWORD_CHANGED: (
        "Tu contraseña ha cambiado",
        "se cambió la contraseña de tu cuenta",
    ),
    NoticeKind.PASSWORD_RESET_COMPLETED: (
        "Tu contraseña se ha restablecido",
        "se restableció la contraseña de tu cuenta y se cerraron tus otras sesiones",
    ),
    NoticeKind.MFA_ENROLLED: (
        "Has añadido un segundo factor",
        "se añadió un segundo factor de autenticación a tu cuenta",
    ),
    NoticeKind.MFA_REMOVED: (
        "Se ha quitado un segundo factor",
        "se quitó un segundo factor de autenticación de tu cuenta",
    ),
    NoticeKind.SESSIONS_REVOKED: (
        "Se han cerrado sesiones de tu cuenta",
        "se cerraron sesiones activas de tu cuenta",
    ),
}  # fmt: skip


def render(notice: Notice) -> tuple[str, str]:
    """Subject and plain-text body. Only the kind and the UTC time are interpolated."""
    subject, what = _WHAT[notice.kind]
    when = notice.occurred_at.astimezone(UTC).strftime("%d/%m/%Y %H:%M UTC")
    body = (
        "Hola,\n\n"
        f"El {when} {what}.\n\n"
        "Si has sido tú, no tienes que hacer nada.\n"
        "Si no reconoces este cambio, restablece tu contraseña desde la pantalla de acceso y "
        "contacta con el soporte de AutoTramita.\n\n"
        "AutoTramita\n"
    )
    return f"AutoTramita: {subject}", body


class DisabledNotifier:
    """Sends nothing (the production default until the mail provider is decided)."""

    def send(self, notice: Notice) -> None:
        log.info("security notice not sent (disabled)", extra={"fields": {"kind": notice.kind}})


class SmtpNotifier:
    def __init__(self, settings: AuthSettings) -> None:
        assert settings.smtp_host and settings.smtp_from  # noqa: S101 - validated by the settings
        self._host, self._port = settings.smtp_host, settings.smtp_port
        self._from, self._starttls = settings.smtp_from, settings.smtp_starttls
        self._user = settings.smtp_user
        self._password = settings.smtp_password

    def send(self, notice: Notice) -> None:
        if any(ch in notice.to for ch in "\r\n"):
            log.warning("security notice refused: bad recipient")
            return
        subject, body = render(notice)
        message = EmailMessage()
        message["From"], message["To"], message["Subject"] = self._from, notice.to, subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=5) as smtp:
                if self._starttls:
                    smtp.starttls()
                if self._user and self._password:
                    smtp.login(self._user, self._password.get_secret_value())
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException):
            log.warning("security notice failed", extra={"fields": {"kind": notice.kind}})


def build_notifier(settings: AuthSettings) -> SecurityNotifier:
    return SmtpNotifier(settings) if settings.notify_mode == "smtp" else DisabledNotifier()


def send_quietly(notifier: SecurityNotifier, notice: Notice) -> None:
    """Never let a notification problem reach the caller."""
    try:
        notifier.send(notice)
    except Exception:
        log.warning("security notice failed", extra={"fields": {"kind": notice.kind}})
