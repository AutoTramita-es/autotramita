"""Step-up authentication (F2-T06, D23): purposes of a step-up and the freshness check that
protected operations call (the pipeline wires it in F2-T08).

Freshness is always measured from an authentication that really happened: the password sign-in
(``auth_time``) or the moment the provider checked a second factor (``second_factor_time``).
The time the application learned about it is never used, so neither single sign-on nor a new
token can extend a window (F2-T09-REC F-2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.auth.errors import StepUpRequired
from app.auth.sessions.models import AuthLevel, UserSession
from app.auth.tokens import VerifiedToken


class StepUpPurpose(StrEnum):
    REAUTHENTICATE = "REAUTHENTICATE"  # fresh password check (no MFA is forced on anybody, I07)
    MFA = "MFA"  # password and second factor (LoA2)


@dataclass(frozen=True, slots=True)
class StepUpAuthRequest:
    acr_values: str
    prompt: str | None
    max_age: int | None


def authorization_params(purpose: StepUpPurpose) -> StepUpAuthRequest:
    """Both purposes ask the provider to authenticate now (``prompt=login``), never to answer
    from the single sign-on session."""
    level = "loa2" if purpose is StepUpPurpose.MFA else "loa1"
    return StepUpAuthRequest(acr_values=level, prompt="login", max_age=0)


def level_from_acr(acr: str | None) -> AuthLevel:
    return AuthLevel.LOA2 if acr == "loa2" else AuthLevel.LOA1


def second_factor_time(
    acr: str | None, proven_at: int | None, *, now: datetime, leeway_seconds: int
) -> datetime | None:
    """When the second factor behind this authentication was proven, or ``None`` if there is no
    usable evidence: the level is not two, the provider sent no time (for example a realm without
    the ``loa_map`` mapper), or the time lies in the future. ``None`` means level one."""
    if level_from_acr(acr) is not AuthLevel.LOA2 or proven_at is None:
        return None
    if proven_at > now.timestamp() + leeway_seconds:
        return None
    return min(datetime.fromtimestamp(proven_at, tz=UTC), now)


def require_step_up(
    session: UserSession, *, level: AuthLevel, max_age_seconds: int, now: datetime
) -> None:
    """Raise ``StepUpRequired`` (401, RFC 9470) unless the session reached ``level`` within
    ``max_age_seconds``. For ``LOA2`` only the recorded second-factor time counts; for ``LOA1``
    the newest recorded authentication does."""
    if level is AuthLevel.LOA2:
        if session.auth_level is not AuthLevel.LOA2 or session.step_up_at is None:
            raise StepUpRequired(acr_values="loa2", max_age=max_age_seconds)
        reference = session.step_up_at
    else:
        reference = max(session.auth_time, session.step_up_at or session.auth_time)
    if now - reference > timedelta(seconds=max_age_seconds):
        raise StepUpRequired(acr_values=level.value.lower(), max_age=max_age_seconds)


def require_token_step_up(
    token: VerifiedToken,
    *,
    level: AuthLevel,
    max_age_seconds: int,
    now: datetime,
    leeway_seconds: int = 30,
) -> None:
    """Step-up for bearer (mobile) callers: the access token carries when the person signed in
    (``auth_time``) and when a second factor was proven. Refreshing the token changes neither. A
    client that needs more re-authenticates with the identity provider and presents the new
    token."""
    proven = second_factor_time(
        token.acr, token.second_factor_at, now=now, leeway_seconds=leeway_seconds
    )
    if level is AuthLevel.LOA2:
        reference = proven
    else:
        signed_in = (
            None if token.auth_time is None else datetime.fromtimestamp(token.auth_time, tz=UTC)
        )
        reference = max((t for t in (signed_in, proven) if t is not None), default=None)
    if reference is None or now - reference > timedelta(seconds=max_age_seconds):
        raise StepUpRequired(acr_values=level.value.lower(), max_age=max_age_seconds)
