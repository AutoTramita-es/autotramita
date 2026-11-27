"""INFRA-CI-02-REC-01 (REC-02): successive test rigs share no Redis state.

Redis keeps its keys between the tests of one worker. A namespace built from ``id()`` is given
out again as soon as the earlier object is freed, so a later rig inherited the earlier one's
recovery markers. The tests below force that reuse (``id`` returns a constant) instead of waiting
for it to happen."""

import ast
from contextlib import contextmanager
from pathlib import Path

import pytest
from tests.auth import web_harness
from tests.auth.fake_idp import NOW
from tests.auth.security import test_security_policies as policies
from tests.conftest import RoleEnv
from tests.identity import rig as identity_rig
from tests.identity.kc import Env

ROOT = Path(__file__).resolve().parents[1]
SUBJECT = "sub-p"


def reuse_every_object_id(monkeypatch: pytest.MonkeyPatch, *modules: object) -> None:
    for module in modules:
        monkeypatch.setattr(module, "id", lambda _: 1, raising=False)


def test_a_later_security_rig_sees_nothing_of_an_earlier_one(
    role_env: RoleEnv, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    reuse_every_object_id(monkeypatch, policies, web_harness)
    build = contextmanager(policies.security_rig)
    with build(role_env, redis_url) as first:
        markers = first.web.runtime.markers
        assert markers
        markers.mark(SUBJECT, NOW)
        markers.record_change(SUBJECT, NOW + 60)  # "already acted on": the state that hid F1
        assert [subject for subject, _ in markers.pending()] == [SUBJECT]
    with build(role_env, redis_url) as later:
        assert later.web.runtime.markers
        assert later.web.runtime.markers.pending() == []
        assert later.web.runtime.markers.get(SUBJECT) is None


def test_every_set_of_private_markers_has_a_namespace_of_its_own(
    redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    reuse_every_object_id(monkeypatch, web_harness)
    first, later = (web_harness.private_markers(redis_url, "ip") for _ in range(2))
    first.mark(SUBJECT, NOW)
    assert first.get(SUBJECT) is not None
    assert later.get(SUBJECT) is None and later.pending() == []


def test_a_later_keycloak_rig_sees_nothing_of_an_earlier_one(
    role_env: RoleEnv, redis_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Building the rig contacts no Keycloak: the address is never used.
    reuse_every_object_id(monkeypatch, identity_rig)
    env = Env("http://127.0.0.1:1", "admin", "unused", "unused-web", "unused-service")
    state = "s" * 32  # the length of a sign-in state
    first = identity_rig.Rig(env, role_env, redis_url)
    try:
        assert first.runtime.markers
        first.runtime.markers.mark(SUBJECT, NOW)
        first.runtime.flows.put(state, {"rig": "first"})
        assert first.runtime.jti.first_use("jti-1", ttl_seconds=60)
    finally:
        first.close()
    later = identity_rig.Rig(env, role_env, redis_url)
    try:
        assert later.runtime.markers
        assert later.runtime.markers.get(SUBJECT) is None
        assert later.runtime.markers.pending() == []
        assert later.runtime.flows.take(state) is None
        assert later.runtime.jti.first_use("jti-1", ttl_seconds=60)
    finally:
        later.close()


def identity_calls(tree: ast.AST) -> list[int]:
    """Lines that make a name from the identity of an object: ``id()`` or ``hash()`` inside an
    f-string, or in a value given to something called ``...namespace``."""
    values: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            values.append(node)
            continue
        if isinstance(node, ast.keyword):
            targets = [node.arg or ""]
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        else:
            continue
        if any("namespace" in target for target in targets):
            values.append(node.value)
    return sorted(
        {
            call.lineno
            for value in values
            for call in ast.walk(value)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in ("id", "hash")
        }
    )


def test_no_test_builds_a_name_from_the_identity_of_an_object() -> None:
    found = [
        f"{path.relative_to(ROOT)}:{line}"
        for path in sorted((ROOT / "tests").rglob("*.py"))
        for line in identity_calls(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert found == [], "use a uuid4: object identities are reused"


@pytest.mark.parametrize(
    "source",
    [
        'RecoveryMarkers(client, namespace=f"m{id(web)}")',
        'AuthRuntime.build(s, c, e, namespace=f"kc{id(self)}")',
        "RateLimiter(client, namespace=str(id(self)))",
        'namespace = "ip" + str(hash(web))',
        'key = f"pwchange:{id(web)}"',
    ],
)
def test_the_guard_recognises_an_identity_based_name(source: str) -> None:
    assert identity_calls(ast.parse(source)) == [1]


@pytest.mark.parametrize(
    "source",
    [
        'RecoveryMarkers(client, namespace=f"m{uuid.uuid4().hex}")',
        "ids = [id(item) for item in items]",
    ],
)
def test_the_guard_accepts_other_uses(source: str) -> None:
    assert identity_calls(ast.parse(source)) == []
