"""Export or verify the committed OpenAPI contract.

python -m app.api.export_openapi          # write openapi/openapi.json
python -m app.api.export_openapi --check  # fail if the committed file is out of date
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.api.app import create_app

TARGET = Path(__file__).resolve().parents[2] / "openapi" / "openapi.json"


def render() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    content = render()
    if "--check" in argv:
        if not TARGET.exists() or TARGET.read_text() != content:
            sys.stderr.write("openapi/openapi.json is out of date; run the export.\n")
            return 1
        return 0
    TARGET.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
