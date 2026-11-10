"""The one daemon the bridge owns: started when it is needed, again when it goes away, never twice.

The daemon is a background ZettCode session with a fixed id, so every message a chat sends is one more turn of
the same conversation. The id is learned the first time a daemon is started and then kept: a start afterwards
resumes that session.

Two things here are about failing well. A start that fails is not retried on the next message as if nothing had
happened — the wait between attempts grows, and while it is running the bridge says how long it will be rather
than starting a second process that would fight the first for the session lock. And a lock somebody else holds is
not a failure to retry at all: the daemon would only be refused again, so the reader is told once and the bridge
carries on answering with what it has.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from .state import BridgeState

#: How long to wait after the first failed start, and the most it grows to. A daemon that cannot start because
#: its model credentials are wrong will not start in a minute either, and the bridge should not spend the day
#: spawning processes to find that out.
FIRST_WAIT = 5.0
MAX_WAIT = 300.0

#: What a daemon record says about a process that is there. Anything else — ``dead``, or no record at all — is a
#: daemon the bridge may start.
ALIVE = frozenset({"starting", "idle", "working", "stopping"})


class DaemonUnavailable(RuntimeError):
    """The daemon could not be started, and the message says what to tell the reader."""

    def __init__(self, message: str, *, retry_in: float = 0.0) -> None:
        super().__init__(message)
        self.retry_in = retry_in


@dataclass
class DaemonGuard:
    """Keeps one daemon reachable, and remembers the session it runs.

    Args:
        workspace: The directory the daemon works in.
        state: Where the session id lives between runs; the guard writes it when it learns one.
        model: The model by name, or ``None`` for the first configured.
        effort: The reasoning level, or ``None`` for the middle of the ones the model takes — providers do not all
            accept every level, and a daemon nobody is watching should reason as much as its model will by default.
        permission: The shell level the daemon gets: ``deny``, ``safe`` or ``full``. ``full`` by default, the same
            one ``zettcode daemon spawn`` starts with: there is nobody to answer a sandbox's questions from a chat.
        name: The label recorded beside the daemon, so a reader finds it in ``zettcode daemon list``.
        waits: The waits between failed starts, in order; the last one repeats.
    """

    workspace: Path
    state: BridgeState
    model: str | None = None
    effort: str | None = None
    permission: str = "full"
    name: str = "chat bridge"
    waits: tuple[float, ...] = ()
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _failures: int = field(default=0, init=False, repr=False)
    _next_try: float = field(default=0.0, init=False, repr=False)
    _said: str = field(default="", init=False, repr=False)

    # -- what the bridge asks -------------------------------------------------------------------------
    async def ensure(self) -> str:
        """Return the session the daemon runs, starting it when it is not there.

        Raises:
            DaemonUnavailable: The last attempt failed and its wait has not passed, or this attempt did.
        """
        async with self._lock:
            session = str(getattr(self.state, "session_id", ""))
            running = await asyncio.to_thread(self._running, session)
            if running:
                self._ok()
                return session
            wait = self._next_try - time.monotonic()
            if wait > 0:
                raise DaemonUnavailable(self._said or "the daemon is not up yet", retry_in=wait)
            try:
                session = await self._start(session or None)
            except Exception as error:  # noqa: BLE001 - every way a start fails is the reader's sentence
                wait = self._failed(str(error) or error.__class__.__name__)
                raise DaemonUnavailable(str(error) or "the daemon did not start", retry_in=wait) from error
            self._ok()
            self.state.session_id = session
            self.state.save()
            return session

    def forget(self) -> None:
        """Drop the failure count, so the next message tries at once."""
        self._ok()

    def wait_left(self) -> float:
        """Return how many seconds the next attempt has to wait, or zero when it may try now."""
        return max(0.0, self._next_try - time.monotonic())

    @property
    def failures(self) -> int:
        """How many starts have failed in a row."""
        return self._failures

    # -- what it does ---------------------------------------------------------------------------------
    @staticmethod
    def _running(session: str) -> bool:
        """Return whether a daemon for ``session`` is up, read from its record."""
        if not session:
            return False
        from zettcode.sdk.daemons import list_daemons

        for info in list_daemons():
            if info.session_id == session:
                return str(info.status) in ALIVE
        return False

    async def _start(self, session: str | None) -> str:
        """Start a daemon, resuming ``session`` when there is one, and return its session id."""
        from zettcode.sdk.daemons import default_effort, spawn_daemon

        info = await spawn_daemon(
            Path(self.workspace),
            model=self.model,
            effort=self.effort or default_effort(self.model) or None,
            resume=session,
            name=self.name,
            permission=self.permission,
        )
        return info.session_id

    def _wait(self) -> float:
        """Return how long the next attempt waits, and remember it: five seconds, doubling, up to five minutes."""
        if self.waits:
            return self.waits[min(self._failures, len(self.waits) - 1)]
        return min(FIRST_WAIT * (2**self._failures), MAX_WAIT)

    def _failed(self, said: str) -> float:
        """Count a failed attempt, wait longer before the next, and return how long that is."""
        self._failures += 1
        wait = self._wait()
        self._next_try = time.monotonic() + wait
        self._said = said
        return wait

    def _ok(self) -> None:
        self._failures = 0
        self._next_try = 0.0
        self._said = ""


__all__ = ["ALIVE", "DaemonGuard", "DaemonUnavailable", "FIRST_WAIT", "MAX_WAIT"]
