"""Step-up authentication (F2-T06, D23): purposes of a step-up and the freshness check that
protected operations call (the pipeline wires it in F2-T08)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.auth.errors import StepUpRequired
from app.auth.sessions.models import AuthLevel, UserSession


class StepUpPurpose(StrEnum):
    REAUTHENTICATE = "REAUTHENTICATE"  # fresh password check (no MFA is forced on anybody, I07)
    MFA = "MFA"  # password and second factor (LoA2)


@dataclass(frozen=True, slots=True)
class StepUpAuthRequest:
    acr_values: str
    prompt: str | None
    max_age: int | None


def authorization_params(purpose: StepUpPurpose) -> StepUpAuthRequest:
    if purpose is StepUpPurpose.MFA:
        return StepUpAuthRequest(acr_values="loa2", prompt=None, max_age=None)
    return StepUpAuthRequest(acr_values="loa1", prompt="login", max_age=0)


def level_from_acr(acr: str | None) -> AuthLevel:
    return AuthLevel.LOA2 if acr == "loa2" else AuthLevel.LOA1


def require_step_up(
    session: UserSession, *, level: AuthLevel, max_age_seconds: int, now: datetime
) -> None:
    """Raise ``StepUpRequired`` (401, RFC 9470) unless the session reached ``level`` within
    ``max_age_seconds``. Without a recorded step-up, the sign-in time counts for ``LOA1``."""
    reference = session.step_up_at or session.auth_time
    if level is AuthLevel.LOA2 and (
        session.auth_level is not AuthLevel.LOA2 or session.step_up_at is None
    ):
        raise StepUpRequired(acr_values="loa2", max_age=max_age_seconds)
    if now - reference > timedelta(seconds=max_age_seconds):
        raise StepUpRequired(acr_values=level.value.lower(), max_age=max_age_seconds)
