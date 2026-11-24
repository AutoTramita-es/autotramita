import importlib
import logging
import socket
from typing import Any

import app.core.config as config_module
import pytest
from app.core.config import DatabaseRole, RateLimitSettings, Settings
from pydantic import ValidationError
from sqlalchemy.engine import make_url

# Synthetic values only.
RUNTIME_PW = "s3cret-runtime-password"
OWNER_PW = "owner-secret-value"
WORKER_PW = "worker-secret-value"
PLATFORM_PW = "platform-secret-value"
REDIS_PW = "redis-secret-value"
REDIS_URL = f"redis://:{REDIS_PW}@localhost:6379/0"

BASE = {
    "ENVIRONMENT": "test",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "synthetic_db",
    "POSTGRES_USER": "synthetic_app",
    "POSTGRES_PASSWORD": RUNTIME_PW,
    "REDIS_URL": REDIS_URL,
}
ALL_ROLES = {
    "APP_DB_OWNER_USER": "synthetic_owner",
    "APP_DB_OWNER_PASSWORD": OWNER_PW,
    "APP_DB_WORKER_USER": "synthetic_worker",
    "APP_DB_WORKER_PASSWORD": WORKER_PW,
    "APP_DB_PLATFORM_USER": "synthetic_platform",
    "APP_DB_PLATFORM_PASSWORD": PLATFORM_PW,
}
ROLES: tuple[DatabaseRole, ...] = ("owner", "app", "worker", "platform")
SECRETS = (RUNTIME_PW, OWNER_PW, WORKER_PW, PLATFORM_PW, REDIS_PW)
ALIASES = {*BASE, *ALL_ROLES, "POSTGRES_PORT"}


def make(monkeypatch: pytest.MonkeyPatch, **extra: str) -> Settings:
    for key in ALIASES:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASE, **extra}.items():
        monkeypatch.setenv(key, value)
    return Settings()


def error_text(monkeypatch: pytest.MonkeyPatch, **extra: str) -> str:
    with pytest.raises(ValidationError) as info:
        make(monkeypatch, **extra)
    return str(info.value) + repr(info.value) + str(info.value.errors())


# --- valid configuration and compatibility -------------------------------------------------


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch)
    assert s.environment == "test"
    assert s.postgres_port == 5432
    assert s.runtime_role.user == "synthetic_app"
    assert s.app_role == s.runtime_role
    assert s.redis_url == REDIS_URL  # existing consumers keep a plain string


@pytest.mark.parametrize("env", ["dev", "prod", "test"])
def test_supported_environments(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    assert make(monkeypatch, ENVIRONMENT=env).environment == env


@pytest.mark.parametrize("env", ["staging", "", "PROD", "production", " dev"])
def test_invalid_environment_fails(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, ENVIRONMENT=env)


def test_environment_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    make(monkeypatch)
    monkeypatch.delenv("ENVIRONMENT")
    with pytest.raises(ValidationError):
        Settings()


def test_unknown_variables_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make(monkeypatch, SOMETHING_ELSE="x").environment == "test"


# --- missing, empty and malformed values ---------------------------------------------------


@pytest.mark.parametrize(
    "key", ["ENVIRONMENT", "POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD"]
)
def test_missing_required_value_fails(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    make(monkeypatch)
    monkeypatch.delenv(key)
    with pytest.raises(ValidationError):
        Settings()


def test_missing_redis_url_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    make(monkeypatch)
    monkeypatch.delenv("REDIS_URL")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "key", ["POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "REDIS_URL"]
)
def test_empty_required_value_fails(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, **{key: ""})


@pytest.mark.parametrize("key", ["POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "REDIS_URL"])
def test_blank_required_value_fails(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, **{key: "   "})


@pytest.mark.parametrize("port", ["0", "65536", "-1", "abc", "", "54.32"])
def test_invalid_port_fails(monkeypatch: pytest.MonkeyPatch, port: str) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, POSTGRES_PORT=port)


def test_valid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    assert make(monkeypatch, POSTGRES_PORT="6543").postgres_port == 6543


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "http://localhost:6379/0",
        "redis://",
        "redis://:pw-in-url@",
        "redis://:pw-in-url@localhost:notaport/0",
        "redis://:pw-in-url@localhost:99999/0",
        "localhost:6379",
    ],
)
def test_invalid_redis_url_fails_without_echo(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    text = error_text(monkeypatch, REDIS_URL=url)
    assert "pw-in-url" not in text
    assert url not in text


@pytest.mark.parametrize(
    "url", ["redis://localhost/0", "rediss://u:p@host:6380/1", "unix:///r.sock"]
)
def test_valid_redis_urls(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    assert make(monkeypatch, REDIS_URL=url).redis_url == url


# --- four separate database roles ----------------------------------------------------------


def test_four_roles_are_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch, **ALL_ROLES)
    roles = {r: s.role_credentials(r) for r in ROLES}
    assert [roles[r].user for r in roles] == [
        "synthetic_owner",
        "synthetic_app",
        "synthetic_worker",
        "synthetic_platform",
    ]
    assert [roles[r].password.get_secret_value() for r in roles] == [
        OWNER_PW,
        RUNTIME_PW,
        WORKER_PW,
        PLATFORM_PW,
    ]
    urls = {s.database_url(r).get_secret_value() for r in ROLES}
    assert len(urls) == 4
    for role in ROLES:
        parsed = make_url(s.database_url(role).get_secret_value())
        assert parsed.username == f"synthetic_{role}"
        assert (parsed.host, parsed.port, parsed.database) == ("localhost", 5432, "synthetic_db")


def test_app_runtime_needs_no_privileged_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch)  # only POSTGRES_* and REDIS_URL are set
    assert s.owner_user is s.worker_user is s.platform_user is None
    assert s.owner_password is s.worker_password is s.platform_password is None
    assert (
        s.database_url("app").get_secret_value().startswith("postgresql+psycopg://synthetic_app:")
    )


@pytest.mark.parametrize("role", ["owner", "worker", "platform"])
def test_unconfigured_role_has_no_url_and_no_fallback(
    monkeypatch: pytest.MonkeyPatch, role: DatabaseRole
) -> None:
    s = make(monkeypatch)
    with pytest.raises(RuntimeError) as info:
        s.database_url(role)
    assert RUNTIME_PW not in str(info.value)
    with pytest.raises(RuntimeError):
        s.role_credentials(role)


def test_worker_does_not_use_app_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch, APP_DB_OWNER_USER="synthetic_owner", APP_DB_OWNER_PASSWORD=OWNER_PW)
    with pytest.raises(RuntimeError):
        _ = s.worker_role
    with pytest.raises(RuntimeError):
        _ = s.platform_role
    # Configuring one optional role does not enable another.
    assert s.owner_role.user == "synthetic_owner"


@pytest.mark.parametrize("role", ["OWNER", "WORKER", "PLATFORM"])
def test_user_without_password_rejected(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    text = error_text(monkeypatch, **{f"APP_DB_{role}_USER": "synthetic_x"})
    assert "needs both" in text


@pytest.mark.parametrize("role", ["OWNER", "WORKER", "PLATFORM"])
def test_password_without_user_rejected(monkeypatch: pytest.MonkeyPatch, role: str) -> None:
    text = error_text(monkeypatch, **{f"APP_DB_{role}_PASSWORD": "pw-without-user-1"})
    assert "needs both" in text
    assert "pw-without-user-1" not in text


@pytest.mark.parametrize("role", ["OWNER", "WORKER", "PLATFORM"])
@pytest.mark.parametrize("which", ["USER", "PASSWORD"])
def test_empty_optional_credentials_rejected(
    monkeypatch: pytest.MonkeyPatch, role: str, which: str
) -> None:
    creds: dict[str, str] = {
        f"APP_DB_{role}_USER": "synthetic_x",
        f"APP_DB_{role}_PASSWORD": "pw-9",
    }
    creds[f"APP_DB_{role}_{which}"] = ""
    with pytest.raises(ValidationError):
        make(monkeypatch, **creds)


def test_roles_must_not_share_user_or_password(monkeypatch: pytest.MonkeyPatch) -> None:
    same_user = {**ALL_ROLES, "APP_DB_WORKER_USER": "synthetic_app"}
    assert "distinct user names" in error_text(monkeypatch, **same_user)
    same_pw = {**ALL_ROLES, "APP_DB_WORKER_PASSWORD": RUNTIME_PW}
    text = error_text(monkeypatch, **same_pw)
    assert "distinct passwords" in text
    assert RUNTIME_PW not in text


def test_special_characters_in_password(monkeypatch: pytest.MonkeyPatch) -> None:
    nasty = "p@ss:w/o?r#d%40&=+ \"'\\ž"
    s = make(monkeypatch, POSTGRES_PASSWORD=nasty)
    url = s.database_url("app").get_secret_value()
    assert nasty not in url  # escaped on the wire
    parsed = make_url(url)
    assert parsed.password == nasty
    assert (parsed.host, parsed.port, parsed.database) == ("localhost", 5432, "synthetic_db")


# --- environment isolation -----------------------------------------------------------------


def test_environments_are_loaded_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    dev = make(monkeypatch, ENVIRONMENT="dev", POSTGRES_DB="synthetic_dev", **ALL_ROLES)
    prod = make(monkeypatch, ENVIRONMENT="prod", POSTGRES_DB="synthetic_prod")
    assert (dev.environment, dev.postgres_db) == ("dev", "synthetic_dev")
    assert (prod.environment, prod.postgres_db) == ("prod", "synthetic_prod")
    # Nothing from the dev instance (or the earlier process environment) reaches prod.
    assert prod.owner_user is None
    assert prod.worker_user is None
    assert prod.platform_user is None
    with pytest.raises(RuntimeError):
        prod.database_url("owner")


def test_no_defaults_for_secrets_and_no_files_read(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("postgres_password", "redis_secret"):
        assert config_module.Settings.model_fields[name].is_required()
    for name in ("owner", "worker", "platform"):
        assert config_module.Settings.model_fields[f"{name}_password"].default is None
        assert config_module.Settings.model_fields[f"{name}_user"].default is None
    assert Settings.model_config.get("env_file") is None
    assert Settings.model_config.get("secrets_dir") is None


def test_dotenv_file_is_not_loaded(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    (tmp_path / ".env").write_text("APP_DB_OWNER_USER=from_file\nAPP_DB_OWNER_PASSWORD=file-pw\n")
    monkeypatch.chdir(tmp_path)
    s = make(monkeypatch)
    assert s.owner_user is None


def test_no_network_access_on_import_or_load(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    importlib.reload(config_module)
    s = make(monkeypatch, **ALL_ROLES)
    for role in ROLES:
        s.database_url(role)
    config_module.RateLimitSettings()
    importlib.reload(config_module)  # restore a clean module for other tests


# --- secret protection ---------------------------------------------------------------------


def test_secrets_are_not_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch, **ALL_ROLES)
    rendered = "".join(
        [
            repr(s),
            str(s),
            s.model_dump_json(),
            str(s.model_dump()),
            repr(s.runtime_role),
            repr(s.owner_role),
            repr(s.worker_role),
            repr(s.platform_role),
            repr(s.database_url("owner")),
            str(s.database_url("worker")),
            f"{s!r:>5}{s.redis_secret!s}",
        ]
    )
    for secret in SECRETS:
        assert secret not in rendered
    assert "**********" in rendered


@pytest.mark.parametrize(
    "extra",
    [
        {"ENVIRONMENT": "staging"},
        {"POSTGRES_PORT": "abc"},
        {"POSTGRES_HOST": ""},
        {"REDIS_URL": "http://:redis-secret-value@h/0"},
        {"APP_DB_WORKER_USER": "synthetic_worker"},
        {"APP_DB_OWNER_PASSWORD": OWNER_PW},
        {**ALL_ROLES, "APP_DB_PLATFORM_PASSWORD": OWNER_PW},
        {"APP_DB_OWNER_USER": "", "APP_DB_OWNER_PASSWORD": OWNER_PW},
    ],
)
def test_validation_errors_do_not_leak_secrets(
    monkeypatch: pytest.MonkeyPatch, extra: dict[str, str]
) -> None:
    text = error_text(monkeypatch, **extra)
    for secret in SECRETS:
        assert secret not in text


def test_logging_does_not_expose_secrets(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    s = make(monkeypatch, **ALL_ROLES)
    logging.getLogger("test").info("settings=%s role=%r", s, s.owner_role)
    with pytest.raises(ValidationError):
        make(monkeypatch, POSTGRES_PORT="x")
    for secret in SECRETS:
        assert secret not in caplog.text


def test_missing_role_error_names_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch)
    with pytest.raises(RuntimeError, match="not configured"):
        _ = s.owner_role


# --- reserved rate limit configuration -----------------------------------------------------


def test_rate_limit_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for field in RateLimitSettings.model_fields.values():
        assert isinstance(field.validation_alias, str)
        monkeypatch.delenv(field.validation_alias, raising=False)
    s = RateLimitSettings()
    assert s.public_per_min == 60
    assert s.authenticated_per_min == 300
    assert s.tenant_per_min == 3000
    assert s.upload_per_min == 30
    assert s.export_per_min == 5
    # Reserved for F2 (enforced by Keycloak, not by this application layer).
    assert s.keycloak_max_failed_logins == 5
    assert s.keycloak_failure_window_minutes == 15
    assert s.password_recovery_per_hour == 3


def test_rate_limit_fail_open_current_default_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Known deviation from O02 (fail closed); the behaviour change belongs to F1-T07."""
    monkeypatch.delenv("RATE_LIMIT_FAIL_OPEN", raising=False)
    assert RateLimitSettings().fail_open is True
