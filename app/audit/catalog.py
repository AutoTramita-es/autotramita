"""Audit action catalog (F2-T03; AT-02 §9.2, D31).

Every action has a category and an allowlist of detail keys with their value kinds. Anything
not listed is rejected before it reaches the database, so a new detail needs a catalog change
and a review, never an ad-hoc dictionary. Values are short, plain and never contain secrets,
tokens, e-mail addresses or free text from users.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.audit.models import Category

Kind = Literal["code", "int", "bool", "uuid"]
CLIENT_TYPES = ("WEB", "ADMIN_WEB", "MOBILE")


@dataclass(frozen=True, slots=True)
class ActionSpec:
    category: Category
    details: dict[str, Kind]


def _spec(category: Category, **details: Kind) -> ActionSpec:
    return ActionSpec(category, details)


A, S, SS, Z, AD, AX, ID = (
    Category.AUTHN,
    Category.SESSION,
    Category.SECURITY_SETTING,
    Category.AUTHZ,
    Category.ADMIN,
    Category.ACCESS_DENIED,
    Category.IDENTITY,
)

CATALOG: dict[str, ActionSpec] = {
    # authentication
    "auth.login.succeeded": _spec(A, client_type="code", auth_level="code"),
    "auth.login.failed": _spec(A, client_id="code", error="code"),
    "auth.logout": _spec(A, client_type="code"),
    "auth.callback.rejected": _spec(A, reason="code"),
    "auth.token.invalid": _spec(A, reason="code"),
    # identity
    "identity.user.provisioned": _spec(ID, status="code"),
    "identity.link.conflict": _spec(ID),
    "identity.email.verified": _spec(ID),
    "identity.email.changed": _spec(ID),
    "identity.user.deactivated": _spec(ID, reason_code="code"),
    "identity.user.blocked": _spec(ID, reason_code="code"),
    "identity.user.reactivated": _spec(ID, reason_code="code"),
    # sessions
    "session.created": _spec(S, client_type="code", device_platform="code"),
    "session.revoked": _spec(S, revoked_reason="code", count="int"),
    "session.expired_detected": _spec(S, kind="code"),
    "session.context.changed": _spec(
        S,
        from_context_version="int",
        to_context_version="int",
        from_tenant_id="uuid",
        to_tenant_id="uuid",
        from_branch_id="uuid",
        to_branch_id="uuid",
    ),
    "session.theft_suspected": _spec(S, signal="code"),
    # security settings
    "security.password.changed": _spec(SS),
    "security.password.recovery.requested": _spec(SS),
    "security.password.recovery.limited": _spec(SS, limit="code"),
    "security.mfa.enrolled": _spec(SS, factor="code"),
    "security.mfa.removed": _spec(SS, factor="code"),
    "security.step_up.succeeded": _spec(SS, level="code"),
    "security.step_up.failed": _spec(SS, level="code"),
    "security.settings.changed": _spec(SS, setting="code"),
    # platform grants
    "authz.platform_grant.requested": _spec(Z, grant_type="code", grant_id="uuid"),
    "authz.platform_grant.approved": _spec(Z, grant_type="code", grant_id="uuid"),
    "authz.platform_grant.activated": _spec(Z, grant_type="code", grant_id="uuid"),
    "authz.platform_grant.revoked": _spec(Z, grant_type="code", grant_id="uuid"),
    "authz.platform_grant.used": _spec(Z, grant_type="code", grant_id="uuid"),
    "authz.platform_grant.expired": _spec(Z, grant_type="code", grant_id="uuid"),
    # unauthorised attempts
    "authz.denied": _spec(AX, reason="code", resource_type="code"),
    # central administration
    "admin.audit.viewed": _spec(AD, filter_category="code"),
    "admin.user.searched": _spec(AD, match_kind="code"),
}
