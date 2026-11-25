"""Step-up for actions on the account itself (F2-T09-REC F-3): changing the e-mail address or
the password, adding a second factor, signing out everywhere.

What counts as a sufficient authentication depends on the account, so the identity provider is
asked on every such request; nothing about second factors is taken from the client or cached:

* no second factor: a fresh authentication (password);
* any second factor (one-time code, passkey or recovery codes): a fresh authentication that
  proved it (level two).

If the provider cannot say, the action is refused (fail closed). Recovery of a forgotten
password is a separate flow and never comes through here."""

from __future__ import annotations

from datetime import datetime

from app.auth.errors import AuthNotConfigured, IdentityProviderUnavailable
from app.auth.idp import SECOND_FACTOR_TYPES, IdpAdminError
from app.auth.runtime import AuthRuntime
from app.auth.sessions.models import AuthLevel, UserSession
from app.auth.tokens import VerifiedToken
from app.auth.web.stepup import require_step_up, require_token_step_up


def window_seconds(rt: AuthRuntime, requested: int) -> int:
    """The step-up window of an action: never longer than the configured one (ten minutes)."""
    return min(requested, rt.settings.step_up_window_minutes * 60)


def second_factor_enrolled(rt: AuthRuntime, subject: str) -> bool:
    if rt.admin is None:
        raise AuthNotConfigured("Security endpoints are not configured.")
    try:
        found = rt.admin.list_credentials(subject)
    except IdpAdminError:
        raise IdentityProviderUnavailable() from None
    return any(credential.type in SECOND_FACTOR_TYPES for credential in found)


def enforce(
    rt: AuthRuntime,
    *,
    session: UserSession,
    token: VerifiedToken | None,
    level: AuthLevel,
    max_age_seconds: int,
    now: datetime,
) -> None:
    """One step-up check, for a bearer caller (the token) or a cookie session."""
    window = window_seconds(rt, max_age_seconds)
    if token is not None:
        require_token_step_up(
            token,
            level=level,
            max_age_seconds=window,
            now=now,
            leeway_seconds=rt.settings.leeway_seconds,
        )
    else:
        require_step_up(session, level=level, max_age_seconds=window, now=now)


def enforce_for_account(
    rt: AuthRuntime,
    *,
    subject: str,
    session: UserSession,
    token: VerifiedToken | None,
    max_age_seconds: int,
    now: datetime,
) -> bool:
    """Raise ``StepUpRequired`` unless the authentication matches the account. Returns whether
    the person has a second factor."""
    enrolled = second_factor_enrolled(rt, subject)
    enforce(
        rt,
        session=session,
        token=token,
        level=AuthLevel.LOA2 if enrolled else AuthLevel.LOA1,
        max_age_seconds=max_age_seconds,
        now=now,
    )
    return enrolled
