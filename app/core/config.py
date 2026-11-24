"""Central application settings, read from the environment.

Names follow ``docker-compose.yml``: the runtime database role is passed as
``POSTGRES_USER``/``POSTGRES_PASSWORD`` (app role for the API, worker role for Celery).
Owner (migrations) and platform credentials are optional and never present in runtime
containers. There are no default secrets and nothing is read from files in the repo.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "prod", "test"]


class DatabaseCredentials(BaseModel):
    """One PostgreSQL role. The password is a secret and never rendered."""

    model_config = ConfigDict(frozen=True)

    user: str
    password: SecretStr


class Settings(BaseSettings):
    """Application settings. Unknown environment variables are ignored."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=True, env_file=None)

    environment: Environment = Field(validation_alias="ENVIRONMENT")

    postgres_host: str = Field(validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, ge=1, le=65535, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(validation_alias="POSTGRES_DB")
    postgres_user: str = Field(validation_alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")

    # Only used by the migration runner and the platform review component.
    owner_user: str | None = Field(default=None, validation_alias="APP_DB_OWNER_USER")
    owner_password: SecretStr | None = Field(default=None, validation_alias="APP_DB_OWNER_PASSWORD")
    platform_user: str | None = Field(default=None, validation_alias="APP_DB_PLATFORM_USER")
    platform_password: SecretStr | None = Field(
        default=None, validation_alias="APP_DB_PLATFORM_PASSWORD"
    )

    redis_url: str = Field(validation_alias="REDIS_URL")

    @property
    def runtime_role(self) -> DatabaseCredentials:
        return DatabaseCredentials(user=self.postgres_user, password=self.postgres_password)

    @property
    def owner_role(self) -> DatabaseCredentials:
        return _optional_role("owner", self.owner_user, self.owner_password)

    @property
    def platform_role(self) -> DatabaseCredentials:
        return _optional_role("platform", self.platform_user, self.platform_password)


def _optional_role(name: str, user: str | None, password: SecretStr | None) -> DatabaseCredentials:
    if not user or password is None:
        raise RuntimeError(f"The {name} database role is not configured in this environment.")
    return DatabaseCredentials(user=user, password=password)


class RateLimitSettings(BaseSettings):
    """Rate limits (requests per minute unless stated). Configurable; business modules add
    their own policies in their phases. Health checks are never limited.

    The Keycloak brute-force and password-recovery values are reserved here as the agreed
    source of truth; they are enforced by Keycloak configuration in phase F2, not by this
    application layer.
    """

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=True, env_file=None)

    public_per_min: int = Field(default=60, ge=1, validation_alias="RATE_LIMIT_PUBLIC_PER_MIN")
    authenticated_per_min: int = Field(
        default=300, ge=1, validation_alias="RATE_LIMIT_AUTHENTICATED_PER_MIN"
    )
    tenant_per_min: int = Field(default=3000, ge=1, validation_alias="RATE_LIMIT_TENANT_PER_MIN")
    upload_per_min: int = Field(default=30, ge=1, validation_alias="RATE_LIMIT_UPLOAD_PER_MIN")
    export_per_min: int = Field(default=5, ge=1, validation_alias="RATE_LIMIT_EXPORT_PER_MIN")
    keycloak_max_failed_logins: int = Field(
        default=5, ge=1, validation_alias="RATE_LIMIT_KEYCLOAK_MAX_FAILED_LOGINS"
    )
    keycloak_failure_window_minutes: int = Field(
        default=15, ge=1, validation_alias="RATE_LIMIT_KEYCLOAK_FAILURE_WINDOW_MINUTES"
    )
    password_recovery_per_hour: int = Field(
        default=3, ge=1, validation_alias="RATE_LIMIT_PASSWORD_RECOVERY_PER_HOUR"
    )
    # If Redis is unreachable: allow requests (availability, logged) or answer 503.
    fail_open: bool = Field(default=True, validation_alias="RATE_LIMIT_FAIL_OPEN")
    # Number of trusted reverse proxies in front of the API; 0 ignores X-Forwarded-For.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5, validation_alias="TRUSTED_PROXY_HOPS")


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
