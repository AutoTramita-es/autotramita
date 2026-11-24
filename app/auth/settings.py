"""Authentication settings (F2-T02), read from the environment; no secrets live here.

Session lifetimes, the step-up window and the new endpoint limits are accepted decisions
D15/D38 and stay configuration, not constants. Importing this module performs no network
access. ``AuthSettings()`` fails loudly when the issuer is missing or insecure.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def _secure_url(value: str, name: str) -> str:
    parts = urlsplit(value)
    if parts.scheme == "https" and parts.hostname:
        return value
    # Plain http is accepted for the disposable loopback Keycloak of the tests only.
    if parts.scheme == "http" and parts.hostname in _LOOPBACK:
        return value
    raise ValueError(f"{name} must be an https URL")


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore", case_sensitive=True, env_file=None, hide_input_in_errors=True
    )

    # --- OIDC token validation (D05) ---
    issuer: str = Field(validation_alias="AUTH_OIDC_ISSUER")
    jwks_url: str | None = Field(default=None, validation_alias="AUTH_OIDC_JWKS_URL")
    audience: str = Field(default="at-api", min_length=1, validation_alias="AUTH_OIDC_AUDIENCE")
    allowed_azp: str = Field(default="at-mobile", validation_alias="AUTH_OIDC_ALLOWED_AZP")
    leeway_seconds: int = Field(
        default=30, ge=0, le=60, validation_alias="AUTH_TOKEN_LEEWAY_SECONDS"
    )
    max_token_bytes: int = Field(
        default=8192, ge=512, le=65536, validation_alias="AUTH_TOKEN_MAX_BYTES"
    )
    max_token_lifetime_seconds: int = Field(
        default=900, ge=60, le=3600, validation_alias="AUTH_TOKEN_MAX_LIFETIME_SECONDS"
    )
    jwks_cache_seconds: int = Field(default=600, ge=1, validation_alias="AUTH_JWKS_CACHE_SECONDS")
    jwks_min_refresh_seconds: int = Field(
        default=60, ge=0, validation_alias="AUTH_JWKS_MIN_REFRESH_SECONDS"
    )
    jwks_timeout_seconds: float = Field(
        default=3.0, gt=0, le=10, validation_alias="AUTH_JWKS_TIMEOUT_SECONDS"
    )

    # --- Session lifetimes (D15) ---
    web_idle_minutes: int = Field(default=30, ge=1, validation_alias="AUTH_WEB_IDLE_MINUTES")
    web_absolute_hours: int = Field(default=12, ge=1, validation_alias="AUTH_WEB_ABSOLUTE_HOURS")
    admin_idle_minutes: int = Field(default=15, ge=1, validation_alias="AUTH_ADMIN_IDLE_MINUTES")
    admin_absolute_hours: int = Field(default=8, ge=1, validation_alias="AUTH_ADMIN_ABSOLUTE_HOURS")
    mobile_idle_days: int = Field(default=7, ge=1, validation_alias="AUTH_MOBILE_IDLE_DAYS")
    mobile_absolute_days: int = Field(
        default=30, ge=1, validation_alias="AUTH_MOBILE_ABSOLUTE_DAYS"
    )
    step_up_window_minutes: int = Field(
        default=10, ge=1, validation_alias="AUTH_STEP_UP_WINDOW_MINUTES"
    )
    max_sessions_per_user: int = Field(
        default=10, ge=1, le=100, validation_alias="AUTH_MAX_SESSIONS_PER_USER"
    )

    # --- New endpoint limits (D38); the accepted brute-force/recovery values stay in
    # RateLimitSettings and are not duplicated here ---
    login_per_min_ip: int = Field(default=20, ge=1, validation_alias="AUTH_LOGIN_PER_MIN_IP")
    callback_per_min_ip: int = Field(default=30, ge=1, validation_alias="AUTH_CALLBACK_PER_MIN_IP")
    recovery_per_hour_ip: int = Field(
        default=10, ge=1, validation_alias="AUTH_RECOVERY_PER_HOUR_IP"
    )
    verification_resend_per_hour: int = Field(
        default=3, ge=1, validation_alias="AUTH_VERIFICATION_RESEND_PER_HOUR"
    )
    step_up_per_hour_session: int = Field(
        default=10, ge=1, validation_alias="AUTH_STEP_UP_PER_HOUR_SESSION"
    )
    platform_per_min_user: int = Field(
        default=60, ge=1, validation_alias="AUTH_PLATFORM_PER_MIN_USER"
    )

    @field_validator("issuer", mode="after")
    @classmethod
    def _issuer_secure(cls, value: str) -> str:
        return _secure_url(value.rstrip("/"), "AUTH_OIDC_ISSUER")

    @field_validator("jwks_url", mode="after")
    @classmethod
    def _jwks_secure(cls, value: str | None) -> str | None:
        return None if value is None else _secure_url(value, "AUTH_OIDC_JWKS_URL")

    @field_validator("allowed_azp", mode="after")
    @classmethod
    def _azp_not_empty(cls, value: str) -> str:
        if not [item for item in value.split(",") if item.strip()]:
            raise ValueError("AUTH_OIDC_ALLOWED_AZP must name at least one client")
        return value

    @model_validator(mode="after")
    def _admin_not_looser_than_web(self) -> AuthSettings:
        if self.admin_idle_minutes > self.web_idle_minutes:
            raise ValueError("central administration idle timeout must not exceed the web one")
        if self.admin_absolute_hours > self.web_absolute_hours:
            raise ValueError("central administration session must not outlive the web one")
        return self

    @property
    def authorized_parties(self) -> frozenset[str]:
        return frozenset(item.strip() for item in self.allowed_azp.split(",") if item.strip())

    @property
    def jwks_endpoint(self) -> str:
        return self.jwks_url or f"{self.issuer}/protocol/openid-connect/certs"


def _without_input(exc: ValidationError) -> ValidationError:
    return ValidationError.from_exception_data(
        exc.title,
        [
            {"type": "value_error", "loc": error["loc"], "input": "", "ctx": {"error": "invalid"}}
            for error in exc.errors()
        ],
    )


@lru_cache
def get_auth_settings() -> AuthSettings:
    try:
        return AuthSettings()  # type: ignore[call-arg]
    except ValidationError as exc:
        raise _without_input(exc) from None
