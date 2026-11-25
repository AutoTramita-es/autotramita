"""Reconcile the second-factor obligation of the accounts of an existing realm before the
AutoTramita security provider and its flows are switched on there (identity/README.md).

It reads every account through the admin API and sorts it:

* ``permanent``: holds a one-time code or passkey; marked ``at_mfa_required`` if not yet;
* ``codes_only``: holds recovery codes only; marked too (unmarked, the new flow refuses it);
* ``locked``: marked but holds no second factor; left as it is (controlled recovery, T10/T11);
* ``never``: neither marked nor any second factor; left as it is. Keycloak keeps no history of
  removed credentials, so this does not prove the account never had one: review by hand;
* ``pending``: has a pending credential set-up or removal; withdrawn (a pending action would run
  for the holder of any e-mail link without a factor).

Nothing is deleted and no obligation is lifted. Without ``--apply`` it only reports. Never point it
at a realm with real users without a separate authorization; tests run it on a disposable one.

    uv run python scripts/identity/reconcile_mfa_obligation.py --base-url URL --realm NAME [--apply]

Credentials of a realm administrator come from KEYCLOAK_ADMIN_USER / KEYCLOAK_ADMIN_PASSWORD (the
master realm's ``admin-cli``)."""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx

PERMANENT = frozenset({"otp", "webauthn", "webauthn-passwordless"})
CODES = "recovery-authn-codes"
OBLIGATION = "at_mfa_required"
CREDENTIAL_SETUPS = frozenset(
    {
        "CONFIGURE_TOTP",
        "CONFIGURE_RECOVERY_AUTHN_CODES",
        "webauthn-register",
        "webauthn-register-passwordless",
        "delete_credential",
    }
)
PAGE = 100


@dataclass
class Report:
    counts: Counter[str] = field(default_factory=Counter)
    changed: list[tuple[str, str]] = field(default_factory=list)  # (user id, what changed)
    review: list[str] = field(default_factory=list)  # user ids left for a person to look at


def classify(user: dict[str, Any], credentials: list[dict[str, Any]]) -> str:
    types = {str(c.get("type")) for c in credentials}
    marked = (user.get("attributes") or {}).get(OBLIGATION) == ["true"]
    if types & PERMANENT:
        return "permanent"
    if CODES in types:
        return "codes_only"
    return "locked" if marked else "never"


def reconcile(
    client: httpx.Client, realm: str, *, apply: bool, only: frozenset[str] | None = None
) -> Report:
    """``only`` limits it to the given account ids (tests share one disposable realm)."""
    report = Report()
    base = f"/admin/realms/{realm}/users"
    first = 0
    while True:
        users = client.get(
            base, params={"first": first, "max": PAGE, "briefRepresentation": "false"}
        )
        users.raise_for_status()
        batch: list[dict[str, Any]] = users.json()
        for summary in batch:
            user_id = str(summary["id"])
            if only is not None and user_id not in only:
                continue
            user = client.get(f"{base}/{user_id}")
            user.raise_for_status()
            representation = user.json()
            if representation.get("serviceAccountClientId"):
                continue
            found = client.get(f"{base}/{user_id}/credentials")
            found.raise_for_status()
            kind = classify(representation, found.json())
            report.counts[kind] += 1
            attributes = dict(representation.get("attributes") or {})
            pending = list(representation.get("requiredActions") or [])
            kept = [action for action in pending if action not in CREDENTIAL_SETUPS]
            update: dict[str, Any] = {}
            if kind in ("permanent", "codes_only") and attributes.get(OBLIGATION) != ["true"]:
                attributes[OBLIGATION] = ["true"]
                update["attributes"] = attributes
                report.changed.append((user_id, "marked"))
            if kept != pending:
                update["requiredActions"] = kept
                report.counts["pending"] += 1
                report.changed.append((user_id, "pending set-up withdrawn"))
            if kind in ("locked", "never"):
                report.review.append(user_id)
            if update and apply:
                written = client.put(f"{base}/{user_id}", json={**representation, **update})
                written.raise_for_status()
        if len(batch) < PAGE:
            return report
        first += PAGE


def admin_client(base_url: str, user: str, password: str) -> httpx.Client:
    token = httpx.post(
        f"{base_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": user,
            "password": password,
        },
        timeout=20,
    )
    token.raise_for_status()
    return httpx.Client(
        base_url=base_url,
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
        timeout=20,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--realm", required=True)
    parser.add_argument("--apply", action="store_true", help="write the changes (default: report)")
    options = parser.parse_args(argv)
    user, password = (
        os.environ.get("KEYCLOAK_ADMIN_USER"),
        os.environ.get("KEYCLOAK_ADMIN_PASSWORD"),
    )
    if not user or not password:
        print("KEYCLOAK_ADMIN_USER and KEYCLOAK_ADMIN_PASSWORD must be set", file=sys.stderr)
        return 2
    with admin_client(options.base_url.rstrip("/"), user, password) as client:
        report = reconcile(client, options.realm, apply=options.apply)
    print(
        ("applied" if options.apply else "dry run")
        + ": "
        + dict(sorted(report.counts.items())).__repr__()
    )
    print(f"changes: {len(report.changed)}; accounts to review by hand: {len(report.review)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
