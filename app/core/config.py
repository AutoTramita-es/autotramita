"""Central application settings, read from the environment.

Names follow ``docker-compose.yml``: the runtime database role is passed as
``POSTGRES_USER``/``POSTGRES_PASSWORD`` (app role for the API, worker role for Celery).
The four PostgreSQL roles are separate configurations (ADR-002):

* ``app``      runtime of the API: ``POSTGRES_USER``/``POSTGRES_PASSWORD`` (required);
* ``owner``    migrations only: ``APP_DB_OWNER_USER``/``APP_DB_OWNER_PASSWORD`` (optional);
* ``worker``   background worker: ``APP_DB_WORKER_USER``/``APP_DB_WORKER_PASSWORD`` (optional);
* ``platform`` authorised central access: ``APP_DB_PLATFORM_USER``/``APP_DB_PLATFORM_PASSWORD``.

Optional roles are never derived from, and never fall back to, another role. A user without a
password (or the reverse), an empty value, or two roles sharing a user name or password is
rejected. All credentials and the Redis URL are ``SecretStr``; validation errors never echo
input. There are no default secrets, no env/secrets files are read, and importing this module
or building ``Settings`` performs no network access.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

Environment = Literal["dev", "prod", "test"]
DatabaseRole = Literal["owner", "app", "worker", "platform"]

_REDIS_SCHEMES = frozenset({"redis", "rediss", "unix"})


class DatabaseCredentials(BaseModel):
    """One PostgreSQL role. The password is a secret and never rendered."""

    model_config = ConfigDict(frozen=True, hide_input_in_errors=True)

    user: str
    password: SecretStr


class Settings(BaseSettings):
    """Application settings. Unknown environment variables are ignored."""

    model_config = SettingsConfigDict(
        extra="ignore", case_sensitive=True, env_file=None, hide_input_in_errors=True
    )

    environment: Environment = Field(validation_alias="ENVIRONMENT")

    postgres_host: str = Field(min_length=1, validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, ge=1, le=65535, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(min_length=1, validation_alias="POSTGRES_DB")
    # Runtime role (app for the API, worker in the worker container); see module docstring.
    postgres_user: str = Field(min_length=1, validation_alias="POSTGRES_USER")
    postgres_password: SecretStr = Field(validation_alias="POSTGRES_PASSWORD")

    # Optional roles: owner (migrations), worker, platform. No role falls back to another.
    owner_user: str | None = Field(default=None, validation_alias="APP_DB_OWNER_USER")
    owner_password: SecretStr | None = Field(default=None, validation_alias="APP_DB_OWNER_PASSWORD")
    worker_user: str | None = Field(default=None, validation_alias="APP_DB_WORKER_USER")
    worker_password: SecretStr | None = Field(
        default=None, validation_alias="APP_DB_WORKER_PASSWORD"
    )
    platform_user: str | None = Field(default=None, validation_alias="APP_DB_PLATFORM_USER")
    platform_password: SecretStr | None = Field(
        default=None, validation_alias="APP_DB_PLATFORM_PASSWORD"
    )

    # HMAC key for pagination cursors (F1-T06). Optional here so that processes which never
    # paginate need no extra secret; ``CursorCodec.from_settings`` fails closed without it.
    cursor_signing_key: SecretStr | None = Field(
        default=None, validation_alias="CURSOR_SIGNING_KEY"
    )

    # May carry authentication data, hence a secret. Read it through ``redis_url``.
    redis_secret: SecretStr = Field(validation_alias="REDIS_URL")

    def __init__(self, **values: Any) -> None:
        try:
            super().__init__(**values)
        except ValidationError as exc:
            raise _without_input(exc) from None

    @field_validator("postgres_host", "postgres_db", "postgres_user", mode="after")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("owner_user", "worker_user", "platform_user", mode="after")
    @classmethod
    def _optional_user_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be empty when set")
        return value

    @field_validator("postgres_password", mode="after")
    @classmethod
    def _password_not_empty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value():
            raise ValueError("password must not be empty")
        return value

    @field_validator("owner_password", "worker_password", "platform_password", mode="after")
    @classmethod
    def _optional_password_not_empty(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and not value.get_secret_value():
            raise ValueError("password must not be empty when set")
        return value

    @field_validator("cursor_signing_key", mode="after")
    @classmethod
    def _cursor_key_strong(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().encode("utf-8")) < 32:
            raise ValueError("CURSOR_SIGNING_KEY must be at least 32 bytes")
        return value

    @field_validator("redis_secret", mode="after")
    @classmethod
    def _valid_redis_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        try:
            parts = urlsplit(raw)
            _ = parts.port  # raises for a non-numeric or out-of-range port
        except ValueError:
            raise ValueError("REDIS_URL is not a valid URL") from None
        if parts.scheme not in _REDIS_SCHEMES:
            raise ValueError("REDIS_URL must use the redis, rediss or unix scheme")
        if parts.scheme != "unix" and not parts.hostname:
            raise ValueError("REDIS_URL must contain a host")
        return value

    @model_validator(mode="after")
    def _roles_complete_and_separate(self) -> Settings:
        pairs = {
            "owner": (self.owner_user, self.owner_password),
            "worker": (self.worker_user, self.worker_password),
            "platform": (self.platform_user, self.platform_password),
        }
        for name, (user, password) in pairs.items():
            if (user is None) != (password is None):
                raise ValueError(f"The {name} database role needs both user and password")
        configured: dict[str, tuple[str, str]] = {
            "app": (self.postgres_user, self.postgres_password.get_secret_value())
        }
        for name, (user, password) in pairs.items():
            if user is not None and password is not None:
                configured[name] = (user, password.get_secret_value())
        users = [u for u, _ in configured.values()]
        passwords = [p for _, p in configured.values()]
        if len(set(users)) != len(users):
            raise ValueError("Database roles must use distinct user names")
        if len(set(passwords)) != len(passwords):
            raise ValueError("Database roles must use distinct passwords")
        return self

    @property
    def redis_url(self) -> str:
        """The Redis URL in clear text, for creating the client only. Never log it."""
        return self.redis_secret.get_secret_value()

    @property
    def runtime_role(self) -> DatabaseCredentials:
        return DatabaseCredentials(user=self.postgres_user, password=self.postgres_password)

    @property
    def app_role(self) -> DatabaseCredentials:
        """The API runtime role; the same configuration as ``runtime_role``."""
        return self.runtime_role

    @property
    def owner_role(self) -> DatabaseCredentials:
        return _optional_role("owner", self.owner_user, self.owner_password)

    @property
    def worker_role(self) -> DatabaseCredentials:
        return _optional_role("worker", self.worker_user, self.worker_password)

    @property
    def platform_role(self) -> DatabaseCredentials:
        return _optional_role("platform", self.platform_user, self.platform_password)

    def role_credentials(self, role: DatabaseRole) -> DatabaseCredentials:
        """Credentials of one role; raises ``RuntimeError`` if it is not configured."""
        return {
            "owner": lambda: self.owner_role,
            "app": lambda: self.app_role,
            "worker": lambda: self.worker_role,
            "platform": lambda: self.platform_role,
        }[role]()

    def database_url(self, role: DatabaseRole) -> SecretStr:
        """SQLAlchemy URL for one role. Special characters are escaped; it is a secret.

        This only builds a string; engines and sessions belong to the database layer.
        """
        credentials = self.role_credentials(role)
        url = URL.create(
            "postgresql+psycopg",
            username=credentials.user,
            password=credentials.password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )
        return SecretStr(url.render_as_string(hide_password=False))


def _without_input(exc: ValidationError) -> ValidationError:
    """Rebuild a validation error with every offending input removed.

    Pydantic keeps the raw input (for a model-level check, all environment values) on each
    error. Settings hold credentials, so no input may be reachable from the exception.
    """
    lines: list[Any] = []
    for err in exc.errors(include_input=False, include_url=False):
        line: dict[str, Any] = {"type": err["type"], "loc": err["loc"], "input": "<hidden>"}
        if "ctx" in err:
            line["ctx"] = {
                k: ValueError(str(v)) if k == "error" else v for k, v in err["ctx"].items()
            }
        lines.append(line)
    return ValidationError.from_exception_data(exc.title, lines, hide_input=True)


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
    # Known deviation: O02 (Redis fail closed) conflicts with this fail-open default;
    # behaviour is deliberately unchanged here and is resolved in F1-T07.
    fail_open: bool = Field(default=True, validation_alias="RATE_LIMIT_FAIL_OPEN")
    # Number of trusted reverse proxies in front of the API; 0 ignores X-Forwarded-For.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5, validation_alias="TRUSTED_PROXY_HOPS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
