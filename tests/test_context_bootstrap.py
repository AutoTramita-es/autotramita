"""F2-T03 / AC-CTX-01..03: the authentication bootstrap context (decision D17).

Unit tests need no database; the rest runs on the throwaway PostgreSQL 16 of ``role_env``."""

import re
import uuid
from pathlib import Path

import pytest
from app.core.db import RequestContext, create_session_factory, session_scope
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from tests.conftest import RoleEnv
from tests.test_roles_and_migrations import migrate

ROOT = Path(__file__).resolve().parents[1]
HASH_1, HASH_2 = bytes(range(32)), bytes(range(32, 64))


# --- RequestContext validation (unit) ---------------------------------------------------------
def test_new_fields_default_to_none_and_old_usage_is_unchanged() -> None:
    context = RequestContext(tenant_id=uuid.uuid4())
    assert context.auth_subject is None and context.session_hash is None
    assert RequestContext() == RequestContext(auth_subject=None, session_hash=None)


@pytest.mark.parametrize("subject", ["7b2f0c1e-6f9e-4f0e-9a52-0d4b6b2f8a11", "kc.sub:1_a-B"])
def test_valid_subjects_are_accepted(subject: str) -> None:
    assert RequestContext(auth_subject=subject).auth_subject == subject


@pytest.mark.parametrize("subject", ["", "a b", "x'; DROP", "é", "a" * 129, "a\nb", "a,b"])
def test_invalid_subject_formats_are_rejected(subject: str) -> None:
    with pytest.raises(ValueError, match="auth_subject"):
        RequestContext(auth_subject=subject)


def test_subject_and_hash_types_are_checked() -> None:
    with pytest.raises(TypeError):
        RequestContext(auth_subject=123)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RequestContext(session_hash="ab" * 32)  # type: ignore[arg-type]
    for bad in (b"", b"x" * 31, b"x" * 33):
        with pytest.raises(ValueError, match="session_hash"):
            RequestContext(session_hash=bad)


# --- AC-CTX-03 only the auth module may use the bootstrap fields (static) ---------------------
def test_bootstrap_fields_are_used_nowhere_outside_the_auth_module_and_the_db_layer() -> None:
    pattern = re.compile(r"auth_subject\s*=|session_hash\s*=|app\.auth_subject|app\.session_hash")
    allowed_dir, allowed_file = ROOT / "app" / "auth", ROOT / "app" / "core" / "db.py"
    offenders = [
        str(path.relative_to(ROOT))
        for path in (ROOT / "app").rglob("*.py")
        if allowed_dir not in path.parents and path != allowed_file
        if pattern.search(path.read_text())
    ]
    assert offenders == []


# --- database ---------------------------------------------------------------------------------
@pytest.fixture
def env(role_env: RoleEnv) -> RoleEnv:
    migrate(role_env.engine("owner"), "upgrade", "head")
    return role_env


def settings(env: RoleEnv, context: RequestContext, kind: str = "app") -> tuple[object, object]:
    factory = create_session_factory(env.engine(kind))
    with session_scope(factory, context) as s:
        row = s.execute(text("SELECT app_auth_subject(), app_session_hash()")).one()
    return row[0], row[1]


def test_functions_return_null_when_unset_and_the_values_when_set(env: RoleEnv) -> None:
    assert settings(env, RequestContext()) == (None, None)
    subject, digest = settings(env, RequestContext(auth_subject="sub-1", session_hash=HASH_1))
    assert subject == "sub-1" and bytes(digest) == HASH_1  # type: ignore[call-overload]


@pytest.mark.parametrize("kind", ["app", "worker", "platform"])
def test_every_runtime_role_can_call_the_helpers(env: RoleEnv, kind: str) -> None:
    assert settings(env, RequestContext(auth_subject="s"), kind)[0] == "s"


# --- AC-CTX-02 no leakage across pooled connections and transactions --------------------------
def test_bootstrap_context_does_not_leak_through_the_pool(env: RoleEnv) -> None:
    base = env.engine("app")
    engine = create_engine(base.url, pool_size=1, max_overflow=0)
    factory = create_session_factory(engine)
    try:
        with session_scope(factory, RequestContext(auth_subject="sub-1", session_hash=HASH_1)):
            pass
        with session_scope(factory, RequestContext()) as s:
            row = s.execute(text("SELECT app_auth_subject(), app_session_hash()")).one()
        assert tuple(row) == (None, None)
        with (
            pytest.raises(RuntimeError),
            session_scope(factory, RequestContext(auth_subject="sub-2", session_hash=HASH_2)),
        ):
            raise RuntimeError("rolled back")
        with session_scope(factory, RequestContext(user_id=uuid.uuid4())) as s:
            row = s.execute(text("SELECT app_auth_subject(), app_session_hash()")).one()
        assert tuple(row) == (None, None)
    finally:
        engine.dispose()


# --- AC-CTX-03 a policy built on the helpers shows only the row the caller can prove ---------
PROBE = """
CREATE TABLE bootstrap_probe (id int PRIMARY KEY, auth_subject text, token_hash bytea, note text);
ALTER TABLE bootstrap_probe ENABLE ROW LEVEL SECURITY;
ALTER TABLE bootstrap_probe FORCE ROW LEVEL SECURITY;
CREATE POLICY prove ON bootstrap_probe
    USING (auth_subject = app_auth_subject() OR token_hash = app_session_hash());
"""


def test_policy_on_the_helpers_reveals_only_matching_rows(env: RoleEnv) -> None:
    with env.engine("owner").begin() as c:
        c.execute(text(PROBE))
    with env.admin_engine().connect() as c:  # seed as superuser (bypasses row security)
        for row_id, subject, digest in ((1, "sub-1", HASH_1), (2, "sub-2", HASH_2)):
            c.execute(
                text("INSERT INTO bootstrap_probe VALUES (:i, :s, :h, 'n')"),
                {"i": row_id, "s": subject, "h": digest},
            )
    factory = create_session_factory(env.engine("app"))

    def ids(context: RequestContext) -> list[int]:
        with session_scope(factory, context) as s:
            return [r[0] for r in s.execute(text("SELECT id FROM bootstrap_probe ORDER BY id"))]

    assert ids(RequestContext()) == []
    assert ids(RequestContext(auth_subject="sub-1")) == [1]
    assert ids(RequestContext(session_hash=HASH_2)) == [2]
    assert ids(RequestContext(auth_subject="sub-1", session_hash=HASH_2)) == [1, 2]
    assert ids(RequestContext(auth_subject="unknown", session_hash=bytes(32))) == []
    assert ids(RequestContext(user_id=uuid.uuid4(), tenant_id=uuid.uuid4())) == []
    with (
        pytest.raises(DBAPIError),
        session_scope(factory, RequestContext(auth_subject="sub-1")) as s,
    ):  # cannot write a row that belongs to somebody else
        s.execute(text("INSERT INTO bootstrap_probe VALUES (3, 'sub-2', NULL, 'forged')"))
