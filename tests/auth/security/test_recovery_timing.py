"""AC-POL-04: how long the recovery answer takes does not depend on the account. The identity
provider is made slow for existing accounts only, and the time until the complete answer has
left the application is measured at the ASGI boundary (the test client would also wait for the
work that runs after the answer)."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from typing import Any

from app.auth.idp import IdpUser
from tests.auth.security.test_security_policies import API, EMAIL, Rig
from tests.auth.web_harness import WEB_HOST

pytest_plugins = ["tests.auth.security.test_security_policies"]
PROVIDER_DELAY = 0.4


def answered_after(app: Any, address: str) -> tuple[float, int, bytes]:
    body = json.dumps({"email": address}).encode()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": f"{API}/auth/password-recovery",
        "raw_path": f"{API}/auth/password-recovery".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", WEB_HOST.encode()),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("192.0.2.10", 40000),
        "server": (WEB_HOST, 443),
        "state": {},
    }
    seen: dict[str, Any] = {"body": b""}

    async def run() -> None:
        sent = False
        start = time.perf_counter()

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if sent:
                await asyncio.sleep(3600)
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                seen["status"] = message["status"]
            elif message["type"] == "http.response.body":
                seen["body"] += message.get("body", b"")
                if not message.get("more_body"):
                    seen["elapsed"] = time.perf_counter() - start

        await app(scope, receive, send)

    asyncio.run(run())
    return seen["elapsed"], seen["status"], seen["body"]


def test_the_time_to_answer_does_not_depend_on_the_account(rig: Rig) -> None:
    real = rig.admin.find_user_by_email
    looked_up: list[str] = []

    def slow(email: str) -> IdpUser | None:
        looked_up.append(email)
        found = real(email)
        if found is not None:
            time.sleep(PROVIDER_DELAY)
        return found

    rig.admin.find_user_by_email = slow  # type: ignore[method-assign]
    known: list[float] = []
    unknown: list[float] = []
    answers: set[tuple[int, bytes]] = set()
    answered_after(rig.web.app, "warm-up@example.test")
    for number in range(3):  # three per account and hour: all of them send a real mail
        for address, bucket in ((EMAIL, known), (f"no-{number}@example.test", unknown)):
            elapsed, status, body = answered_after(rig.web.app, address)
            bucket.append(elapsed)
            answers.add((status, body))
    assert answers == {(202, b'{"status":"accepted"}')}
    assert looked_up.count(EMAIL) == 3 and len(rig.admin.sent) == 3  # the slow work did happen
    assert max(known) < PROVIDER_DELAY / 2, known
    assert abs(statistics.median(known) - statistics.median(unknown)) < PROVIDER_DELAY / 4
