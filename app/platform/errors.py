"""Problems of the platform-grant routes (catalog of AT-02 section 10.4)."""

from __future__ import annotations

from app.core.errors import Conflict


class GrantConflict(Conflict):
    """409 GRANT_CONFLICT: the grant is not in a state that allows this (already decided, a live
    grant of that type exists, expired, the beneficiary cannot hold a grant, ...)."""

    code = "GRANT_CONFLICT"
    title = "The grant does not allow this now"


class LastGrantAdmin(Conflict):
    """409 LAST_GRANT_ADMIN: the last active grant administrator is never revoked (anti-lockout;
    the way out is the bootstrap command, D30)."""

    code = "LAST_GRANT_ADMIN"
    title = "The last grant administrator cannot be revoked"
