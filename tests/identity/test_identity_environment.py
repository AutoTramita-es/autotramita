"""F2-T01 / AC-KC-06: the Keycloak image is pinned by digest and the disposable environment
cannot touch shared infrastructure. No Keycloak needed."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "identity" / "docker-compose.keycloak-test.yml").read_text()
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
COMPOSE_MAIN = (ROOT / "docker-compose.yml").read_text()
IMAGE = re.compile(r"quay\.io/keycloak/keycloak:(\d+\.\d+\.\d+)@sha256:([0-9a-f]{64})")


def test_test_image_is_pinned_by_digest_to_the_version_in_compose() -> None:
    version = re.search(r"quay\.io/keycloak/keycloak:(\d+\.\d+\.\d+)", COMPOSE_MAIN)
    assert version
    for text in (COMPOSE, CI):
        found = IMAGE.findall(text)
        assert found, "image must carry a digest"
        assert {v for v, _ in found} == {version.group(1)}
    assert {d for _, d in IMAGE.findall(COMPOSE)} == {d for _, d in IMAGE.findall(CI)}


def test_disposable_compose_has_no_persistent_state_and_no_shared_services() -> None:
    assert "volumes:" in COMPOSE and ":ro" in COMPOSE  # only read-only bind mounts
    assert not re.search(r"^volumes:", COMPOSE, re.M)  # no named volume survives
    for forbidden in ("postgres", "traefik", "proxy", "KC_DB:", "restart:", "ports:"):
        assert forbidden not in COMPOSE, forbidden
    assert "start-dev" in COMPOSE and "--import-realm" in COMPOSE
    assert "realm-test.json" in COMPOSE and "realm-prod.json" not in COMPOSE
    assert "127.0.0.1" in COMPOSE  # loopback only


def test_ci_job_uses_only_the_test_realm_and_throwaway_credentials() -> None:
    assert "realm-test.json" in CI and "realm-prod.json" not in CI and "realm-dev.json" not in CI
    assert "-m keycloak" in CI
    assert "ci-throwaway" in CI
    assert "${{ secrets." not in CI
