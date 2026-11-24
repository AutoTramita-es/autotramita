"""F2-T04 / AC-USR-05, AC-USR-09, AC-USR-10 (unit part): e-mail normalisation, the status
model and the account gate. No database needed."""

import itertools
import uuid
from datetime import UTC, datetime

import pytest
from app.auth.email import normalize_email
from app.auth.errors import AccountDisabled, EmailNotVerified
from app.auth.users.models import ALLOWED_TRANSITIONS, User, UserStatus
from app.auth.users.service import require_active

S = UserStatus


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" User@Example.COM ", "user@example.com"),
        (
            "\uff35\uff33\uff25\uff32@example.com",
            "user@example.com",
        ),  # full-width forms fold (NFKC)
        ("first.last@example.com", "first.last@example.com"),  # dots are kept
        ("user+tag@example.com", "user+tag@example.com"),  # plus tags are kept
        ("user@sub.Example.com", "user@sub.example.com"),
        ("ñandú@example.es", "ñandú@example.es"),
    ],
)
def test_normalisation_is_deterministic_and_does_not_merge_mailboxes(
    raw: str, expected: str
) -> None:
    assert normalize_email(raw) == expected
    assert normalize_email(expected) == expected  # idempotent


def test_plus_tags_and_dots_stay_different_mailboxes() -> None:
    assert normalize_email("a.b@example.com") != normalize_email("ab@example.com")
    assert normalize_email("a+x@example.com") != normalize_email("a@example.com")


@pytest.mark.parametrize(
    "bad",
    ["", " ", "a", "a@b", "@example.com", "a@", "a@@example.com", "a b@example.com",
     "a@exam ple.com", "a@example..com", "a@.example.com", "a@example.com.", "a\n@example.com",
     "a\x00@example.com", "a@" + "x" * 320 + ".com"],
)  # fmt: skip
def test_implausible_addresses_are_rejected_without_echoing_them(bad: str) -> None:
    with pytest.raises(ValueError, match="valid e-mail") as caught:
        normalize_email(bad)
    assert len(bad.strip()) < 6 or bad not in str(caught.value)


def test_non_strings_are_rejected() -> None:
    with pytest.raises(ValueError, match="string"):
        normalize_email(None)  # type: ignore[arg-type]


def test_transition_table_is_exactly_the_specified_one() -> None:
    assert {
        (S.PENDING_VERIFICATION, S.ACTIVE), (S.PENDING_VERIFICATION, S.BLOCKED),
        (S.ACTIVE, S.DEACTIVATED), (S.ACTIVE, S.BLOCKED),
        (S.DEACTIVATED, S.ACTIVE), (S.DEACTIVATED, S.BLOCKED),
        (S.BLOCKED, S.ACTIVE), (S.BLOCKED, S.DEACTIVATED),
    } == ALLOWED_TRANSITIONS  # fmt: skip
    everything = set(itertools.product(S, S))
    forbidden = everything - ALLOWED_TRANSITIONS - {(s, s) for s in S}
    assert (S.ACTIVE, S.PENDING_VERIFICATION) in forbidden  # no way back to pending
    assert (S.DEACTIVATED, S.PENDING_VERIFICATION) in forbidden
    assert (S.PENDING_VERIFICATION, S.DEACTIVATED) in forbidden


def user(status: UserStatus) -> User:
    now = datetime.now(UTC)
    return User(
        id=uuid.uuid4(), auth_subject="s", email="a@b.co", email_normalized="a@b.co",
        email_verified_at=now if status is not S.PENDING_VERIFICATION else None, status=status,
        status_reason=None, status_changed_at=now, status_changed_by=None, display_name=None,
        preferred_language="es", last_login_at=None, created_at=now, updated_at=now, version=1,
    )  # fmt: skip


def test_account_gate_distinguishes_unverified_from_disabled() -> None:
    require_active(user(S.ACTIVE))
    with pytest.raises(EmailNotVerified) as unverified:
        require_active(user(S.PENDING_VERIFICATION))
    assert (unverified.value.status, unverified.value.code) == (403, "EMAIL_NOT_VERIFIED")
    for status in (S.DEACTIVATED, S.BLOCKED):
        with pytest.raises(AccountDisabled) as disabled:
            require_active(user(status))
        assert (disabled.value.status, disabled.value.code) == (403, "ACCOUNT_DISABLED")
