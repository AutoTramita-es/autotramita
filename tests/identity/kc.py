"""Helpers for the Keycloak integration tests (F2-T01 spike): admin API, a scripted browser,
an SMTP sink and a back-channel logout receiver. Test-only; nothing here ships with the app."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import socketserver
import struct
import threading
import time
import uuid
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

REALM = "autotramita-test"
# A second Keycloak instance (parallel test shard) has sinks of its own; its realm names them.
SMTP_PORT = int(os.environ.get("TEST_KEYCLOAK_SMTP_PORT", "18025"))
BACKCHANNEL_PORT = int(os.environ.get("TEST_KEYCLOAK_BACKCHANNEL_PORT", "18090"))
WEB_REDIRECT = "http://127.0.0.1:18080/api/v1/auth/callback"
MOBILE_REDIRECT = "http://127.0.0.1:18080/app/auth/callback"
GOOD_PASSWORD = "Correct-horse-battery-7"


@dataclass(frozen=True)
class Env:
    base_url: str
    admin_user: str
    admin_password: str
    web_secret: str
    svc_secret: str


def decode_jwt(token: str) -> dict[str, Any]:
    """Payload of a JWT without verification (the tests inspect claims Keycloak issued)."""
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    decoded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(payload))
    return decoded


def totp(secret_base32: str, *, at: float | None = None) -> str:
    key = base64.b32decode(
        secret_base32.replace(" ", "").upper() + "=" * (-len(secret_base32.replace(" ", "")) % 8)
    )
    counter = int((time.time() if at is None else at) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 10**6
    return f"{value:06d}"


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return verifier, challenge.decode()


@dataclass
class TestUser:
    __test__ = False
    id: str
    email: str
    password: str = GOOD_PASSWORD


class Admin:
    """Keycloak admin REST client. ``master`` uses the bootstrap admin (test setup only);
    ``service`` uses the least-privilege service account the application would use."""

    def __init__(self, env: Env) -> None:
        self.env = env
        self.http = httpx.Client(base_url=env.base_url, timeout=20)

    def close(self) -> None:
        self.http.close()

    def _master_token(self) -> str:
        r = self.http.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self.env.admin_user,
                "password": self.env.admin_password,
            },
        )
        r.raise_for_status()
        return str(r.json()["access_token"])

    def service_token(self) -> str:
        r = self.http.post(
            f"/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "at-admin-svc",
                "client_secret": self.env.svc_secret,
            },
        )
        r.raise_for_status()
        return str(r.json()["access_token"])

    def master(self, method: str, path: str, **kw: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._master_token()}"}
        return self.http.request(method, f"/admin/realms/{REALM}{path}", headers=headers, **kw)

    def server(self, method: str, path: str, **kw: Any) -> httpx.Response:
        """A call outside the realm (``/admin{path}``), for example the server information."""
        headers = {"Authorization": f"Bearer {self._master_token()}"}
        return self.http.request(method, f"/admin{path}", headers=headers, **kw)

    def service(self, method: str, path: str, **kw: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.service_token()}"}
        return self.http.request(method, f"/admin/realms/{REALM}{path}", headers=headers, **kw)

    def realm(self) -> dict[str, Any]:
        r = self.master("GET", "")
        r.raise_for_status()
        body: dict[str, Any] = r.json()
        return body

    def update_realm(self, **changes: Any) -> None:
        current = self.realm()
        current.update(changes)
        self.master("PUT", "", json=current).raise_for_status()

    def create_user(self, *, password: str = GOOD_PASSWORD) -> TestUser:
        email = f"u{uuid.uuid4().hex[:12]}@example.test"
        r = self.master(
            "POST",
            "/users",
            json={
                "username": email,
                "email": email,
                "enabled": True,
                "emailVerified": True,
                "firstName": "Spike",
                "lastName": "User",
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            },
        )
        r.raise_for_status()
        return TestUser(id=r.headers["Location"].rsplit("/", 1)[1], email=email, password=password)


@dataclass
class Page:
    """Result of one scripted browser step."""

    status: int
    text: str
    location: str | None = None

    @property
    def code(self) -> str | None:
        return parse_qs(urlparse(self.location or "").query).get("code", [None])[0]

    @property
    def summary(self) -> str:
        """Visible text of the page (tags, scripts and styles removed) for failure messages."""
        body = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", self.text)
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()[
            :400
        ] or str(self.location)

    def require_code(self) -> str:
        if not self.code:
            raise AssertionError(f"no authorization code: status={self.status} {self.summary}")
        return str(self.code)

    @property
    def query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.location or "").query)


_FORM_ACTION = re.compile(r"<form[^>]*\saction=\"([^\"]+)\"", re.I)
_INPUT = re.compile(r"<input[^>]*>", re.I)


def form_action(page_html: str) -> str:
    match = _FORM_ACTION.search(page_html)
    if not match:
        raise AssertionError("no <form action> in page: " + page_html[:400])
    return html.unescape(match.group(1))


def hidden_inputs(page_html: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in _INPUT.findall(page_html):
        name = re.search(r'name="([^"]+)"', tag)
        value = re.search(r'value="([^"]*)"', tag)
        kind = re.search(r'type="([^"]+)"', tag)
        if name and kind and kind.group(1) == "hidden":
            fields[name.group(1)] = html.unescape(value.group(1) if value else "")
    return fields


OPEN_BROWSERS: list[Browser] = []


class Browser:
    """A cookie-keeping client that follows Keycloak's own redirects but stops at the
    redirect URI of the application, so the authorization code can be inspected."""

    def __init__(self, env: Env) -> None:
        self.env = env
        # Keycloak marks its cookies Secure even on plain-http loopback, which a standard
        # cookie jar will not send back; this tiny jar keeps them for the single test host.
        self.cookies: dict[str, str] = {}
        self.http = httpx.Client(
            timeout=20,
            follow_redirects=False,
            event_hooks={"request": [self._send_cookies], "response": [self._store_cookies]},
        )
        OPEN_BROWSERS.append(self)
        self._last = ""
        self.verifier: str | None = None

    def close(self) -> None:
        self.http.close()

    def _send_cookies(self, request: httpx.Request) -> None:
        if self.cookies:
            request.headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def _store_cookies(self, response: httpx.Response) -> None:
        for header in response.headers.get_list("set-cookie"):
            name, _, rest = header.partition("=")
            value = rest.split(";", 1)[0]
            if value in ("", "deleted") or "Max-Age=0" in header:
                self.cookies.pop(name.strip(), None)
            else:
                self.cookies[name.strip()] = value

    def _settle(self, response: httpx.Response, stop_at: str) -> Page:
        for _ in range(15):
            if response.is_redirect:
                location = str(response.headers["location"])
                if location.startswith(stop_at):
                    return Page(response.status_code, "", location)
                response = self.http.get(httpx.URL(str(response.url)).join(location))
                continue
            return Page(response.status_code, response.text)
        raise AssertionError("too many redirects")

    def authorize(
        self,
        client_id: str,
        redirect_uri: str,
        *,
        challenge: str | None = None,
        no_pkce: bool = False,
        **extra: str,
    ) -> Page:
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid",
            "state": secrets.token_urlsafe(8),
            "nonce": secrets.token_urlsafe(8),
            **extra,
        }
        if challenge is None and "code_challenge" not in extra and not no_pkce:
            self.verifier, challenge = pkce_pair()
        if challenge:
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"
        response = self.http.get(
            f"{self.env.base_url}/realms/{REALM}/protocol/openid-connect/auth", params=params
        )
        self._last = redirect_uri
        return self._settle(response, redirect_uri)

    def submit(self, page: Page, data: dict[str, str], *, action: str | None = None) -> Page:
        target = action or form_action(page.text)
        response = self.http.post(target, data=data)
        return self._settle(response, self._last)

    def get(self, url: str) -> Page:
        target = url if url.startswith("http") else self.env.base_url + url
        return self._settle(self.http.get(target), self._last)

    def login(self, user: TestUser | str, password: str | None = None, **kw: Any) -> Page:
        """Authorize and fill the password form. Returns the next page (a redirect with a
        code on success, the login form with an error message on failure)."""
        email = user if isinstance(user, str) else user.email
        secret = password if password is not None else getattr(user, "password", "")
        client = kw.pop("client_id", "at-web")
        redirect = kw.pop("redirect_uri", WEB_REDIRECT)
        page = self.authorize(client, redirect, **kw)
        if page.location:
            return page  # an SSO session already satisfied the request
        return self.submit(page, {"username": email, "password": secret, "credentialId": ""})

    def sign_in_again(self, page: Page, user: TestUser) -> Page:
        """Keycloak asks to sign in again before a credential changes (``max_auth_age`` 0) once
        the earlier sign-in is a second old; answer it with the password when it is asked."""
        if (
            page.location is None
            and 'name="password"' in page.text
            and "password-new" not in page.text
        ):
            fields = {"password": user.password, "credentialId": ""}
            if 'name="username"' in page.text:
                fields["username"] = user.email
            return self.submit(page, fields)
        return page

    def token(
        self, client_id: str, code: str, redirect_uri: str, *, verifier: str | None = None
    ) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        verifier = verifier or self.verifier
        if verifier:
            data["code_verifier"] = verifier
        if client_id == "at-web":
            data["client_secret"] = self.env.web_secret
        r = self.http.post(
            f"{self.env.base_url}/realms/{REALM}/protocol/openid-connect/token", data=data
        )
        body: dict[str, Any] = r.json()
        body["_status"] = r.status_code
        return body

    def refresh(self, client_id: str, refresh_token: str) -> dict[str, Any]:
        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }
        if client_id == "at-web":
            data["client_secret"] = self.env.web_secret
        r = self.http.post(
            f"{self.env.base_url}/realms/{REALM}/protocol/openid-connect/token", data=data
        )
        body: dict[str, Any] = r.json()
        body["_status"] = r.status_code
        return body


class _SmtpHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        sink: SmtpSink = self.server.sink  # type: ignore[attr-defined]
        self.wfile.write(b"220 sink ESMTP\r\n")
        recipients: list[str] = []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            command = line.decode(errors="replace").strip()
            upper = command.upper()
            if upper.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250 sink\r\n")
            elif upper.startswith("MAIL FROM"):
                recipients = []
                self.wfile.write(b"250 OK\r\n")
            elif upper.startswith("RCPT TO"):
                recipients.append(command.split(":", 1)[1].strip().strip("<>"))
                self.wfile.write(b"250 OK\r\n")
            elif upper == "DATA":
                self.wfile.write(b"354 go\r\n")
                chunks: list[bytes] = []
                while True:
                    row = self.rfile.readline()
                    if row in (b".\r\n", b""):
                        break
                    chunks.append(row[1:] if row.startswith(b"..") else row)
                message = message_from_bytes(b"".join(chunks), policy=policy.default)
                body = message.get_body(preferencelist=("plain", "html"))
                sink.messages.append(
                    {
                        "to": recipients,
                        "subject": str(message["subject"]),
                        "body": body.get_content() if body else "",
                    }
                )
                self.wfile.write(b"250 queued\r\n")
            elif upper == "QUIT":
                self.wfile.write(b"221 bye\r\n")
                return
            else:
                self.wfile.write(b"250 OK\r\n")


class _ThreadedTcp(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


@dataclass
class SmtpSink:
    messages: list[dict[str, Any]] = field(default_factory=list)
    _server: _ThreadedTcp | None = None

    def start(self) -> None:
        self._server = _ThreadedTcp(("127.0.0.1", SMTP_PORT), _SmtpHandler)
        self._server.sink = self  # type: ignore[attr-defined]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def for_recipient(self, email: str, *, wait: float = 10.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            found = [m for m in self.messages if email in m["to"]]
            if found:
                return found
            time.sleep(0.2)
        return []


@dataclass
class BackchannelSink:
    bodies: list[dict[str, list[str]]] = field(default_factory=list)
    _server: HTTPServer | None = None

    def start(self) -> None:
        sink = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", 0))
                sink.bodies.append(parse_qs(self.rfile.read(length).decode()))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args: Any) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", BACKCHANNEL_PORT), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def logout_tokens(self, *, wait: float = 15.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            tokens = [decode_jwt(b["logout_token"][0]) for b in self.bodies if "logout_token" in b]
            if tokens:
                return tokens
            time.sleep(0.3)
        return []


def record_result(key: str, value: Any) -> None:
    """Append an informational spike observation to $SPIKE_RESULTS_PATH (printed by CI)."""
    path = os.environ.get("SPIKE_RESULTS_PATH")
    if not path:
        return
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        data = {}
    data[key] = value
    with open(path, "w") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
