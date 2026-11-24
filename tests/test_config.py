import pytest
from app.core.config import Settings
from pydantic import ValidationError

BASE = {
    "ENVIRONMENT": "test",
    "POSTGRES_HOST": "localhost",
    "POSTGRES_DB": "autotramita_test",
    "POSTGRES_USER": "autotramita_test_app",
    "POSTGRES_PASSWORD": "s3cret-runtime-password",
    "REDIS_URL": "redis://localhost:6379/0",
}


def make(monkeypatch: pytest.MonkeyPatch, **extra: str) -> Settings:
    for key in [*BASE, "APP_DB_OWNER_USER", "APP_DB_OWNER_PASSWORD", "POSTGRES_PORT"]:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASE, **extra}.items():
        monkeypatch.setenv(key, value)
    return Settings()  # type: ignore[call-arg]


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch)
    assert s.environment == "test"
    assert s.postgres_port == 5432
    assert s.runtime_role.user == "autotramita_test_app"


def test_missing_required_value_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    make(monkeypatch)
    monkeypatch.delenv("POSTGRES_PASSWORD")
    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]


def test_invalid_environment_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValidationError):
        make(monkeypatch, ENVIRONMENT="staging")


def test_secrets_are_not_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch, APP_DB_OWNER_USER="o", APP_DB_OWNER_PASSWORD="owner-secret-value")
    rendered = repr(s) + str(s) + repr(s.runtime_role) + repr(s.owner_role) + s.model_dump_json()
    assert "s3cret-runtime-password" not in rendered
    assert "owner-secret-value" not in rendered


def test_owner_role_absent_in_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch)
    with pytest.raises(RuntimeError):
        _ = s.owner_role


def test_unknown_variables_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    s = make(monkeypatch, SOMETHING_ELSE="x")
    assert s.environment == "test"
