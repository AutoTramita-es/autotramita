"""Cookies of the web sign-in (F2-T06, D12). Session: HttpOnly, Secure, SameSite=Lax, Path=/,
no Domain (host-only), ``__Host-`` prefixed. Flow: the same, valid for the sign-in only."""

from __future__ import annotations

from app.auth.settings import AuthSettings
from starlette.responses import Response

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def no_store(response: Response) -> None:
    for name, value in NO_STORE.items():
        response.headers[name] = value


def set_session_cookie(
    response: Response, settings: AuthSettings, secret: str, *, max_age_seconds: int
) -> None:
    response.set_cookie(
        settings.cookie_name,
        secret,
        max_age=max(int(max_age_seconds), 1),
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(
        settings.cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax"
    )


def set_flow_cookie(response: Response, settings: AuthSettings, binder: str) -> None:
    response.set_cookie(
        settings.flow_cookie_name,
        binder,
        max_age=settings.flow_ttl_seconds,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_flow_cookie(response: Response, settings: AuthSettings) -> None:
    response.delete_cookie(
        settings.flow_cookie_name,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
