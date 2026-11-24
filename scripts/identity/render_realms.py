"""Render identity/keycloak/realm-{dev,prod,test}.json from realm-template.json (F2-T01, D01).

The committed files are generated, never edited by hand; tests fail on drift. Realm JSON holds
no secret: confidential clients use ${ENV} placeholders resolved by Keycloak at import time.

    python scripts/identity/render_realms.py          # write the files
    python scripts/identity/render_realms.py --check  # exit 1 if a committed file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

DIRECTORY = Path(__file__).resolve().parents[2] / "identity" / "keycloak"
TEMPLATE = DIRECTORY / "realm-template.json"

ENVIRONMENTS: dict[str, dict[str, Any]] = {
    "dev": {
        "__REALM__": "autotramita-dev",
        "__SSL__": "external",
        "__WEB_CALLBACK__": "https://dev.autotramita.es/api/v1/auth/callback",
        "__ADMIN_CALLBACK__": "https://admin.dev.autotramita.es/api/v1/auth/callback",
        "__WEB_HOME__": "https://dev.autotramita.es/",
        "__POST_LOGOUT__": "https://dev.autotramita.es/##https://admin.dev.autotramita.es/",
        "__BACKCHANNEL__": "https://dev.autotramita.es/api/v1/auth/oidc/backchannel-logout",
        "__MOBILE_REDIRECT__": "https://dev.autotramita.es/app/auth/callback",
        "__SMTP__": {},
    },
    "prod": {
        "__REALM__": "autotramita-prod",
        "__SSL__": "all",
        "__WEB_CALLBACK__": "https://autotramita.es/api/v1/auth/callback",
        "__ADMIN_CALLBACK__": "https://admin.autotramita.es/api/v1/auth/callback",
        "__WEB_HOME__": "https://autotramita.es/",
        "__POST_LOGOUT__": "https://autotramita.es/##https://admin.autotramita.es/",
        "__BACKCHANNEL__": "https://autotramita.es/api/v1/auth/oidc/backchannel-logout",
        "__MOBILE_REDIRECT__": "https://autotramita.es/app/auth/callback",
        "__SMTP__": {},
    },
    "test": {
        "__REALM__": "autotramita-test",
        "__SSL__": "none",
        "__WEB_CALLBACK__": "http://127.0.0.1:18080/api/v1/auth/callback",
        "__ADMIN_CALLBACK__": "http://127.0.0.1:18080/admin/api/v1/auth/callback",
        "__WEB_HOME__": "http://127.0.0.1:18080/",
        "__POST_LOGOUT__": "http://127.0.0.1:18080/##http://127.0.0.1:18080/admin/",
        "__BACKCHANNEL__": "http://127.0.0.1:18090/api/v1/auth/oidc/backchannel-logout",
        "__MOBILE_REDIRECT__": "http://127.0.0.1:18080/app/auth/callback",
        "__SMTP__": {
            "host": "127.0.0.1",
            "port": "18025",
            "from": "keycloak@autotramita.invalid",
            "fromDisplayName": "AutoTramita test",
        },
    },
}


def _fill(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, str):
        if node in values and not isinstance(values[node], str):
            return values[node]
        for token, value in values.items():
            if isinstance(value, str):
                node = node.replace(token, value)
        return node
    if isinstance(node, list):
        filled = [_fill(item, values) for item in node]
        unique: list[Any] = []
        for item in filled:
            if item not in unique:
                unique.append(item)
        return unique
    if isinstance(node, dict):
        return {key: _fill(value, values) for key, value in node.items()}
    return node


def render(environment: str) -> str:
    template = json.loads(TEMPLATE.read_text())
    rendered = _fill(template, ENVIRONMENTS[environment])
    return json.dumps(rendered, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for environment in ENVIRONMENTS:
        path = DIRECTORY / f"realm-{environment}.json"
        content = render(environment)
        if check:
            if not path.exists() or path.read_text() != content:
                stale.append(path.name)
        else:
            path.write_text(content)
    if stale:
        print("stale realm files: " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
