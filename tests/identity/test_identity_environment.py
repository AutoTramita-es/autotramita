"""F2-T01 / AC-KC-06: the Keycloak image is pinned by digest and the disposable environment
cannot touch shared infrastructure. No Keycloak needed."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "identity" / "docker-compose.keycloak-test.yml").read_text()
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
COMPOSE_MAIN = (ROOT / "docker-compose.yml").read_text()
PRODUCTION = (ROOT / "identity" / "docker-compose.keycloak-production.yml").read_text()
IMAGE = re.compile(r"quay\.io/keycloak/keycloak:(\d+\.\d+\.\d+)@sha256:([0-9a-f]{64})")


def test_test_image_is_pinned_by_digest_to_the_version_in_compose() -> None:
    # The tests run exactly the Keycloak prepared for production (version and digest). The live
    # definition (docker-compose.yml) changes only with a production authorization; until then it
    # may name nothing but the version the prepared file says it replaces (F2-T09-REC upgrade).
    prepared = IMAGE.findall(PRODUCTION)
    assert len(prepared) == 1, "the prepared production file must pin exactly one image"
    for text in (COMPOSE, CI):
        found = IMAGE.findall(text)
        assert found, "image must carry a digest"
        assert set(found) == set(prepared)
    live = re.search(r"quay\.io/keycloak/keycloak:(\d+\.\d+\.\d+)", COMPOSE_MAIN)
    assert live
    if live.group(1) != prepared[0][0]:
        assert f"replaces quay.io/keycloak/keycloak:{live.group(1)}" in PRODUCTION
        assert "PREPARED, NOT APPLIED" in PRODUCTION


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


# --- the AutoTramita Keycloak image (security provider order, 2026-11-25) ---------------------
DOCKERFILE = (ROOT / "identity" / "keycloak" / "Dockerfile").read_text()
BUILD = (ROOT / "identity" / "keycloak" / "provider" / "build.sh").read_text()
SOURCES = sorted((ROOT / "identity" / "keycloak" / "provider" / "src").rglob("*.java"))
PINNED = re.compile(r"(KEYCLOAK_IMAGE|JDK_IMAGE)[=:] ?([a-z0-9./_-]+:[\w.-]+@sha256:[0-9a-f]{64})")


def test_the_image_is_built_from_the_same_pinned_images_everywhere() -> None:
    dockerfile = dict(PINNED.findall(DOCKERFILE))
    assert set(dockerfile) == {"KEYCLOAK_IMAGE", "JDK_IMAGE"}
    assert dict(PINNED.findall(CI)) == dockerfile == dict(PINNED.findall(COMPOSE))
    assert dict(PINNED.findall(PRODUCTION)) == dockerfile
    assert IMAGE.search(dockerfile["KEYCLOAK_IMAGE"])
    assert "autotramita-keycloak:ci" in CI
    assert (
        "quay.io/keycloak/keycloak"
        not in CI.split("Without the security provider")[0]
        .split("Build the AutoTramita Keycloak image")[1]
        .split("--tag")[1]
    )  # after the build, every node runs the built image


def test_every_build_of_the_image_runs_without_network() -> None:
    # PROD-SEC-01 (D49, IR-06): no RUN instruction of the Dockerfile reaches a network, on
    # GitHub, in Local CI (the broker adds it as well) and in the prepared production build.
    builds = re.findall(r"run: >-\n\s+docker build(.*)\n", CI)
    assert builds == [" --network none", " --network none"]
    assert re.search(r"^    build:\n      context: [^\n]+\n      network: none\b", PRODUCTION, re.M)
    assert "network:" not in PRODUCTION.split("build:")[0].split("services:")[1]


def test_the_runtime_stage_adds_one_read_only_jar_and_stays_non_root() -> None:
    final = DOCKERFILE.split("FROM ${KEYCLOAK_IMAGE}\n")[-1]
    instructions = [line.split()[0] for line in final.splitlines() if line and line[0].isupper()]
    assert instructions == ["COPY", "USER"], instructions
    assert "--chmod=0444" in final and "/opt/keycloak/providers/" in final
    assert final.strip().endswith("USER 1000")
    assert "cmp /first.jar" in DOCKERFILE  # built twice, byte for byte the same


def test_the_provider_is_built_offline_from_keycloak_s_own_libraries() -> None:
    for tool in ("curl", "wget", "mvn", "gradle", "pip", "http://", "https://"):
        assert tool not in BUILD, tool
    assert '-cp "$lib/main/*:$lib/boot/*"' in BUILD and "-Werror" in BUILD
    assert "PolicyCheck" in BUILD and "unexpected jar entry" in BUILD
    allowed = ("java.", "jakarta.", "org.keycloak.", "org.jboss.logging.", "es.autotramita.")
    for source in SOURCES:
        for line in source.read_text().splitlines():
            if line.startswith("import "):
                name = line.removeprefix("import ").removeprefix("static ")
                assert name.startswith(allowed), (source.name, line)
