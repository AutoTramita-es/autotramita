"""The periodic recovery worker (approved scope: 60 s, PostgreSQL leases).

A daemon thread of the API process that does two things per interval under the dedicated worker
database role: the check for completed password resets (F-0), if one is given, and one bounded
D37 sweep. D37 state lives in PostgreSQL and the pending password changes in Redis, so any
instance, including a restarted one, continues where another stopped. A failure of one task
does not stop the other. It is not the general T11 outbox.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from app.auth.idp import IdentityProviderAdmin
from app.auth.security.email_change_worker import run_once
from app.auth.security.notify import SmtpNotifier
from sqlalchemy.orm import Session, sessionmaker

INTERVAL_SECONDS = 60.0
STOP_TIMEOUT_SECONDS = 25.0

log = logging.getLogger(__name__)


class EmailChangeRecoveryWorker:
    def __init__(
        self,
        factory: sessionmaker[Session],
        admin: IdentityProviderAdmin,
        notifier: SmtpNotifier | None,
        *,
        on_cycle: Callable[[bool], None],
        password_check: Callable[[Callable[[], bool]], None] | None = None,
        interval_seconds: float = INTERVAL_SECONDS,
    ) -> None:
        self._factory, self._admin, self._notifier = factory, admin, notifier
        self._on_cycle = on_cycle
        self._password_check = password_check
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_cycle(self) -> bool:
        """One interval's work; reports whether the D37 sweep ran to the end (the D37 routes
        stay closed if not)."""
        if self._password_check is not None:  # first: it is what ends stolen sessions
            try:
                self._password_check(self._stop.is_set)
            except Exception:
                log.warning("password change sweep failed")
        try:
            run_once(self._factory, self._admin, self._notifier, should_stop=self._stop.is_set)
            ok = True
        except Exception:
            log.warning("email change recovery cycle failed")
            ok = False
        self._on_cycle(ok)
        return ok

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_cycle()
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="d37-recovery", daemon=True)
        self._thread.start()

    def stop(self) -> bool:
        """Ask the thread to end and wait; ``True`` once it has."""
        self._stop.set()
        if self._thread is None:
            return True
        self._thread.join(timeout=STOP_TIMEOUT_SECONDS)
        ended = not self._thread.is_alive()
        if ended:
            self._on_cycle(False)
        return ended
