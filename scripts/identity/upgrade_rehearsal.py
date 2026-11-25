"""F2-T09-REC: rehearsal of the Keycloak upgrade 26.4.7 -> 26.8.2 on disposable containers only.

It never touches a persistent database or an existing realm. It starts its own PostgreSQL 16 and
Keycloak containers (names ``at-t09-rehearsal-*``, loopback ports 15439 and 18291, throwaway
credentials), and removes them at the end. Nothing is published, nothing is pushed.

Images (built beforehand, without network):

    git archive <old revision> identity/keycloak | tar -x -C <dir>
    docker build --network none --no-cache --tag autotramita-keycloak:rehearsal-old \
        --build-arg KEYCLOAK_IMAGE=<26.4.7 pin> --build-arg JDK_IMAGE=<jdk pin> \
        <dir>/identity/keycloak
    docker build --network none --no-cache --tag autotramita-keycloak:rehearsal-new \
        --build-arg KEYCLOAK_IMAGE=<26.8.2 pin> --build-arg JDK_IMAGE=<jdk pin> identity/keycloak

    uv run --locked python scripts/identity/upgrade_rehearsal.py \
        --old-image autotramita-keycloak:rehearsal-old \
        --new-image autotramita-keycloak:rehearsal-new \
        --old-realm <dir>/identity/keycloak/realm-test.json --work <empty directory>

Steps: the old Keycloak on a new database (realm import, accounts with each factor, a session) ->
backup (pg_dump) -> the new Keycloak on the same database (its migration) -> checks -> restore of
the backup into a second database under the old Keycloak (rollback) -> the old Keycloak on the
migrated database (downgrade, unsupported: only observed). Result: ``<work>/rehearsal.json``.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.identity.accounts import (  # noqa: E402
    CODE_WINDOW_STEPS,
    CODES,
    OTP,
    PASSKEY,
    Account,
    account,
)
from tests.identity.kc import REALM, WEB_REDIRECT, Admin, Browser, Env  # noqa: E402

PG_IMAGE = "postgres:16@sha256:07abc3f43c9395b0bdbbab36bc25ddb0e8d83cd4fcafb5fb7d6abe14ff156dd8"
PREFIX = "at-t09-rehearsal"
PG_PORT = 15439
KC_PORT = 18291
THROWAWAY = "rehearsal-throwaway-password"
ENV = Env(
    f"http://127.0.0.1:{KC_PORT}",
    "rehearsal-admin",
    THROWAWAY,
    "rehearsal-web-secret",
    "rehearsal-svc-secret",
)


DOCKER = shutil.which("docker") or "/usr/bin/docker"
CURL = shutil.which("curl") or "/usr/bin/curl"


def run(
    command: list[str], check: bool, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    # fixed executables, argument lists only (no shell); values are this script's own constants
    return subprocess.run(command, check=check, capture_output=True, input=stdin)  # noqa: S603


def docker(*args: str, check: bool = True, stdin: bytes | None = None) -> str:
    return run([DOCKER, *args], check, stdin).stdout.decode(errors="replace")


def start_postgres() -> None:
    docker("rm", "-f", f"{PREFIX}-pg", check=False)
    docker(
        "run", "-d", "--name", f"{PREFIX}-pg", "--network", "host",
        "-e", f"POSTGRES_PASSWORD={THROWAWAY}", "--tmpfs", "/var/lib/postgresql/data",
        PG_IMAGE, "-c", "listen_addresses=127.0.0.1", "-p", str(PG_PORT),
    )  # fmt: skip
    for _ in range(60):
        probe = ["exec", f"{PREFIX}-pg", "pg_isready", "-h", "127.0.0.1", "-p", str(PG_PORT)]
        if "accepting" in docker(*probe, check=False):
            break
        time.sleep(1)
    for database in ("keycloak", "keycloak_restored"):
        docker(
            "exec", f"{PREFIX}-pg", "psql", "-h", "127.0.0.1", "-p", str(PG_PORT),
            "-U", "postgres", "-c", f"CREATE DATABASE {database}",
        )  # fmt: skip


def pg(database: str, sql: str) -> str:
    return docker(
        "exec", f"{PREFIX}-pg", "psql", "-h", "127.0.0.1", "-p", str(PG_PORT),
        "-U", "postgres", "-d", database, "-At", "-c", sql,
    ).strip()  # fmt: skip


def start_keycloak(image: str, database: str, realm: Path | None, wait: int = 240) -> bool:
    docker("rm", "-f", f"{PREFIX}-kc", check=False)
    args = [
        "run", "-d", "--name", f"{PREFIX}-kc", "--network", "host",
        "-e", f"KC_BOOTSTRAP_ADMIN_USERNAME={ENV.admin_user}",
        "-e", f"KC_BOOTSTRAP_ADMIN_PASSWORD={ENV.admin_password}",
        "-e", f"AT_WEB_CLIENT_SECRET={ENV.web_secret}",
        "-e", f"AT_ADMIN_SVC_CLIENT_SECRET={ENV.svc_secret}",
        "-v", f"{ROOT}/identity/keycloak/blacklists:/opt/keycloak/data/password-blacklists:ro",
    ]  # fmt: skip
    if realm is not None:
        args += ["-v", f"{realm}:/opt/keycloak/data/import/realm-test.json:ro"]
    args += [image, "start-dev", "--http-host=127.0.0.1", f"--http-port={KC_PORT}"]
    args += ["--hostname-strict=false", "--db=postgres", "--db-username=postgres"]
    args += [f"--db-url=jdbc:postgresql://127.0.0.1:{PG_PORT}/{database}"]
    args += [f"--db-password={THROWAWAY}"]
    if realm is not None:
        args.append("--import-realm")
    docker(*args)
    url = f"{ENV.base_url}/realms/{REALM}/.well-known/openid-configuration"
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        state = docker("inspect", "-f", "{{.State.Running}}", f"{PREFIX}-kc", check=False)
        if state.strip() != "true":
            return False
        if run([CURL, "-sf", "-o", "/dev/null", url], False).returncode == 0:
            return True
        time.sleep(2)
    return False


def stop_keycloak(work: Path, label: str) -> list[str]:
    logs = run([DOCKER, "logs", f"{PREFIX}-kc"], False)
    text = (logs.stdout + logs.stderr).decode(errors="replace")
    (work / f"keycloak-{label}.log").write_text(text)
    docker("stop", "-t", "30", f"{PREFIX}-kc", check=False)
    docker("rm", "-f", f"{PREFIX}-kc", check=False)
    keep = ("ERROR", "Updating database", "migrat", "Migrat", "newer", "version")
    return [line[:300] for line in text.splitlines() if any(k in line for k in keep)][:40]


def snapshot(admin: Admin, accounts: dict[str, Account], database: str) -> dict[str, Any]:
    """Users, credentials and attributes through the admin API, and the stored credential
    rows as hashes (no secret leaves the database)."""
    users: dict[str, Any] = {}
    rows = pg(
        database,
        "SELECT user_id || ':' || id || ':' || type || ':' || md5(coalesce(secret_data,'')) "
        "|| ':' || md5(coalesce(credential_data,'')) FROM credential ORDER BY 1",
    ).splitlines()
    for name, held in accounts.items():
        found = admin.master("GET", f"/users/{held.user.id}").json()
        credentials = admin.master("GET", f"/users/{held.user.id}/credentials").json()
        prefix = held.user.id + ":"
        stored = [r.removeprefix(prefix) for r in rows if r.startswith(prefix)]
        users[name] = {
            "enabled": found["enabled"],
            "attributes": {
                k: v for k, v in sorted((found.get("attributes") or {}).items())
                if k.startswith("at_")
            },
            "required_actions": sorted(found.get("requiredActions") or []),
            "credentials": sorted((c["id"], c["type"]) for c in credentials),
            "stored_rows": stored,
        }  # fmt: skip
    guard = pg(database, "SELECT user_id || ':' || changes FROM at_mfa_guard ORDER BY 1")
    return {"users": users, "guard_rows": guard.splitlines()}


def sign_in(held: Account, kind: str | None) -> str:
    browser = Browser(ENV)
    try:
        page = held.sign_in(browser, kind)
        return "code" if page.code else page.summary[:120]
    finally:
        browser.close()


def admin_api_status() -> int:
    admin = Admin(ENV)
    try:
        return admin.service("GET", "/users?max=1").status_code
    finally:
        admin.close()


def reconnect(accounts: dict[str, Account]) -> Admin:
    """A new admin client after a restart, shared by every account."""
    admin = Admin(ENV)
    admin.update_realm(otpPolicyLookAheadWindow=CODE_WINDOW_STEPS)
    for held in accounts.values():
        held.admin = admin
    return admin


def provider_version(admin: Admin) -> str:
    info = admin.server("GET", "/serverinfo").json()
    actions = info["providers"]["required-action"]["providers"]
    return str(actions["CONFIGURE_TOTP"]["operationalInfo"]["autotramita-guard"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--old-image", required=True)
    parser.add_argument("--new-image", required=True)
    parser.add_argument("--old-realm", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    options = parser.parse_args()
    work: Path = options.work
    work.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"old_image": options.old_image, "new_image": options.new_image}
    checks: dict[str, Any] = {}
    result["checks"] = checks
    try:
        start_postgres()
        # 1. the old Keycloak: realm import and accounts with every kind of factor
        if not start_keycloak(options.old_image, "keycloak", options.old_realm.resolve()):
            raise SystemExit("the old Keycloak did not start")
        admin = Admin(ENV)
        admin.update_realm(otpPolicyLookAheadWindow=CODE_WINDOW_STEPS)
        accounts = {
            "password_only": Account(admin, admin.create_user()),
            "otp": account(admin, OTP),
            "otp_and_codes": account(admin, OTP, CODES),
            "passkey": account(admin, PASSKEY),
            "mandatory": account(admin, OTP),
        }
        mandatory = admin.master("GET", f"/users/{accounts['mandatory'].user.id}").json()
        mandatory.setdefault("attributes", {})["at_mfa_mandatory"] = ["true"]
        admin.master("PUT", f"/users/{accounts['mandatory'].user.id}", json=mandatory)
        web = Browser(ENV)
        first = accounts["otp"].sign_in(web)
        tokens = web.token("at-web", first.require_code(), WEB_REDIRECT)
        checks["old_provider_version"] = provider_version(admin)
        checks["old_admin_api"] = admin_api_status()
        before = snapshot(admin, accounts, "keycloak")
        admin.close()
        stop_keycloak(work, "old")

        # 2. backup before the upgrade
        dump = docker(
            "exec", f"{PREFIX}-pg", "sh", "-c",
            f"pg_dump -h 127.0.0.1 -p {PG_PORT} -U postgres -Fc keycloak | base64 -w0",
        )  # fmt: skip
        raw = base64.b64decode(dump)
        (work / "keycloak-before-upgrade.dump").write_bytes(raw)
        result["backup"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

        # 3. the new Keycloak on the same database: Keycloak migrates it at start
        started = time.monotonic()
        checks["new_started_on_old_database"] = start_keycloak(options.new_image, "keycloak", None)
        checks["migration_seconds"] = round(time.monotonic() - started, 1)
        admin = reconnect(accounts)
        checks["model_versions"] = pg(
            "keycloak", "SELECT version FROM migration_model ORDER BY update_time"
        ).splitlines()
        after = snapshot(admin, accounts, "keycloak")
        checks["users_credentials_obligations_kept"] = after == before
        checks["new_provider_version"] = provider_version(admin)
        flows = admin.master("GET", "/authentication/flows/browser-loa/executions").json()
        checks["guard_in_flow"] = any(e.get("providerId") == "at-security-guard" for e in flows)
        checks["sign_in"] = {
            "password_only": sign_in(accounts["password_only"], None),
            "otp": sign_in(accounts["otp"], OTP),
            "passkey": sign_in(accounts["passkey"], PASSKEY),
            "recovery_code": sign_in(accounts["otp_and_codes"], CODES),
            "mandatory": sign_in(accounts["mandatory"], OTP),
        }
        sso = web.authorize("at-web", WEB_REDIRECT)
        checks["session_from_before"] = {
            "single_sign_on": "code" if sso.code else "sign-in asked",
            "refresh_token": web.refresh("at-web", tokens["refresh_token"])["_status"],
        }
        web.close()
        checks["admin_api_before_scope"] = admin_api_status()
        client = admin.master("GET", "/clients", params={"clientId": "at-admin-svc"}).json()[0]
        scope = next(
            s for s in admin.master("GET", "/client-scopes").json() if s["name"] == "kc-admin-api"
        )
        admin.master(
            "PUT", f"/clients/{client['id']}/default-client-scopes/{scope['id']}"
        ).raise_for_status()
        checks["admin_api_after_scope"] = admin_api_status()
        accounts["password_only"].enrol(OTP)
        enrolled = admin.master("GET", f"/users/{accounts['password_only'].user.id}").json()
        checks["first_factor_after_upgrade_sets_obligation"] = (
            enrolled.get("attributes") or {}
        ).get("at_mfa_required") == ["true"]
        checks["guard_rows_after_enrolment"] = len(
            pg("keycloak", "SELECT user_id FROM at_mfa_guard").splitlines()
        )
        admin.close()
        result["new_log"] = stop_keycloak(work, "new")

        # 4. rollback: restore the backup into another database under the old Keycloak
        docker("exec", "-i", f"{PREFIX}-pg", "pg_restore", "-h", "127.0.0.1", "-p", str(PG_PORT),
               "-U", "postgres", "-d", "keycloak_restored", "--no-owner", stdin=raw)  # fmt: skip
        checks["old_started_on_restored_backup"] = start_keycloak(
            options.old_image, "keycloak_restored", None
        )
        admin = reconnect(accounts)
        restored = snapshot(admin, accounts, "keycloak_restored")
        checks["restore_equals_state_before_upgrade"] = restored == before
        checks["restore_sign_in_otp"] = sign_in(accounts["otp"], OTP)
        admin.close()
        stop_keycloak(work, "restored")

        # 5. downgrade (unsupported): the old Keycloak on the migrated database, observed only
        checks["old_started_on_migrated_database"] = start_keycloak(
            options.old_image, "keycloak", None, wait=180
        )
        result["downgrade_log"] = stop_keycloak(work, "downgrade")
    finally:
        docker("rm", "-f", f"{PREFIX}-kc", check=False)
        docker("rm", "-f", f"{PREFIX}-pg", check=False)
        (work / "rehearsal.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(checks, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
