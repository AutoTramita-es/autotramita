"""F2-T10: static guarantees of the platform-grant code (no database needed)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sources(*folders: str) -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_text()
        for folder in folders
        for path in (ROOT / folder).rglob("*.py")
    }


def test_only_the_platform_module_names_the_grant_authority_or_a_bootstrap_person() -> None:
    """The second step of the platform context and the bootstrap lookup are set in exactly one
    place each (as AC-CTX-03 for the sign-in bootstrap)."""
    found = sources("app", "scripts")
    assert sorted(n for n, s in found.items() if "set_config('app.grant_authority'" in s) == [
        "app/platform/repository.py"
    ]
    assert sorted(n for n, s in found.items() if "set_config('app.bootstrap_email'" in s) == [
        "app/platform/bootstrap.py"
    ]
    assert sorted(n for n, s in found.items() if "set_authority(" in s) == [
        "app/platform/authz.py",
        "app/platform/repository.py",
    ]


def test_no_route_reads_a_platform_grant_outside_the_platform_scope() -> None:
    """Every platform route opens ``platform_scope``; nothing else in the API touches the
    platform database role or the grant table."""
    api = sources("app/api")
    assert sorted(n for n, s in api.items() if "platform_factory" in s) == ["app/api/v1/guards.py"]
    assert sorted(n for n, s in api.items() if "platform_grants" in s.replace("platform_grants.py", "")
                  and "FROM platform_grants" in s) == []  # fmt: skip
    routes = api["app/api/v1/platform_grants.py"]
    assert routes.count("@router.") == routes.count("with platform_scope(") == 6


def test_the_platform_module_never_reads_a_token_or_a_cookie() -> None:
    """Authority comes from the database only (AC-AUTHZ-02): the grant code does not even
    import the token or cookie handling."""
    for name, text in sources("app/platform").items():
        for forbidden in ("app.auth.tokens", "VerifiedToken", "app.auth.web", "request.cookies"):
            assert forbidden not in text, (name, forbidden)
