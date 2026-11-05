"""Triggers: something a plugin watches for that starts work no prompt asked for.

A trigger is a long-running coroutine (a timer, a file watcher, a socket) that calls ``fire`` whenever its event
happens; the handler the plugin registered with it is what runs then. The host starts the triggers with the runtime and
stops them when it closes.

How many copies of a trigger run is the trigger's own say, as its :attr:`~Trigger.scope`:

* :attr:`TriggerScope.PROCESS` -- one instance per process. Two runtimes in one process (two SDK clients) do not both
  run it: the second is skipped, and says so in its status.
* :attr:`TriggerScope.MACHINE` -- one instance on the whole machine, whatever number of ZettCode processes are open.
  The one that holds an operating-system lock on a file runs it (:class:`~zettcode.filelock.SingletonLock`, which the
  system lets go of when the holder dies, so a killed process never leaves a stale claim); the others stand by and
  take over, within ``retry`` seconds, when the holder exits.

A trigger that raises is recorded as failed and not restarted, so a defect cannot become a hot loop; a handler that
raises costs only that event.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path
from typing import ClassVar

from zettcode.filelock import SingletonLock

__all__ = [
    "RETRY_SECONDS",
    "Fire",
    "Trigger",
    "TriggerEvent",
    "TriggerHandler",
    "TriggerHost",
    "TriggerRegistration",
    "TriggerScope",
    "TriggerState",
    "TriggerStatus",
]

logger = logging.getLogger("zettcode.plugins")

#: How often a process that stands by for a machine-wide trigger looks at the lock again.
RETRY_SECONDS = 5.0

#: A trigger's name is also the name of its lock file, so it is one plain word.
_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


class TriggerScope(str, Enum):
    """How many instances of a trigger run."""

    #: One per process.
    PROCESS = "process"
    #: One per machine, decided by a lock on a file.
    MACHINE = "machine"


class TriggerState(str, Enum):
    """Where one trigger is."""

    PENDING = "pending"
    #: Waiting for the machine-wide lock another process holds.
    STANDBY = "standby"
    RUNNING = "running"
    #: Not started here: another runtime of this process runs it.
    SKIPPED = "skipped"
    #: ``run`` returned: the trigger has nothing more to say.
    FINISHED = "finished"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class TriggerEvent:
    """One occurrence of a trigger.

    Attributes:
        trigger: The name of the trigger that fired.
        payload: What it knows about this occurrence (the path that changed, the time that was due).
        at: Wall-clock seconds since the epoch.
    """

    trigger: str
    payload: Mapping[str, object]
    at: float


#: What a plugin hands a trigger: called with each event, plain or ``async``.
TriggerHandler = Callable[[TriggerEvent], "Awaitable[None] | None"]

#: What a trigger calls to say its event happened, with whatever it knows about it.
Fire = Callable[["Mapping[str, object] | None"], Awaitable[None]]


class Trigger(ABC):
    """Something that fires events for as long as it runs.

    A subclass names itself, says its scope, and implements :meth:`run`.
    """

    #: One lowercase word (letters, digits, ``.``, ``_``, ``-``): it names the lock file of a machine-wide trigger.
    name: ClassVar[str] = ""
    scope: ClassVar[TriggerScope] = TriggerScope.PROCESS

    @abstractmethod
    async def run(self, fire: Fire) -> None:
        """Watch for the event and ``await fire(payload)`` each time it happens.

        This runs until the host stops it, which cancels it: let the cancellation propagate, and release what the
        trigger holds in a ``finally``. Returning means the trigger is done.
        """


@dataclass(frozen=True, slots=True)
class TriggerRegistration:
    """A trigger and the handler its plugin gave it."""

    trigger: Trigger
    handler: TriggerHandler

    @property
    def name(self) -> str:
        """Return the trigger's name."""
        return self.trigger.name


@dataclass(frozen=True, slots=True)
class TriggerStatus:
    """What one trigger is doing, for a front end that lists them."""

    name: str
    scope: TriggerScope
    state: TriggerState
    detail: str = ""


def check_name(trigger: Trigger) -> str:
    """Return the trigger's name, or raise ``ValueError`` when it cannot be one (it is a file name too)."""
    name = trigger.name
    if not _NAME.fullmatch(name):
        raise ValueError(f"A trigger needs a name of lowercase letters, digits, '.', '_' or '-'; got {name!r}")
    return name


#: The triggers of this process that are running, by name, and the host that runs each.
_OWNERS: dict[str, TriggerHost] = {}
_OWNERS_LOCK = threading.Lock()


class TriggerHost:
    """Run the registered triggers on the running event loop, once per their scope.

    Args:
        registrations: The triggers the loaded plugins registered.
        lock_dir: Where the lock files of machine-wide triggers live.
        retry: Seconds between looks at a lock somebody else holds.
    """

    def __init__(
        self, registrations: Iterable[TriggerRegistration], lock_dir: Path, *, retry: float = RETRY_SECONDS
    ) -> None:
        self._registrations = tuple(registrations)
        self._lock_dir = lock_dir
        self._retry = retry
        self._tasks: list[asyncio.Task[None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._status = {
            reg.name: TriggerStatus(reg.name, reg.trigger.scope, TriggerState.PENDING) for reg in self._registrations
        }

    @property
    def statuses(self) -> tuple[TriggerStatus, ...]:
        """Return where each trigger is, in registration order."""
        return tuple(self._status.values())

    def start(self) -> None:
        """Start every trigger as a task on the running loop; a host started twice does nothing the second time."""
        if self._tasks:
            return
        loop = asyncio.get_running_loop()
        self._loop = loop
        self._tasks = [loop.create_task(self._supervise(reg)) for reg in self._registrations]

    async def stop(self) -> None:
        """Cancel the triggers and wait until they have let go of their locks."""
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _set(self, reg: TriggerRegistration, state: TriggerState, detail: str = "") -> None:
        self._status[reg.name] = TriggerStatus(reg.name, reg.trigger.scope, state, detail)

    def _claim(self, name: str) -> bool:
        """Take the one instance this process may run of ``name``."""
        with _OWNERS_LOCK:
            owner = _OWNERS.get(name)
            # A host whose loop is gone (abandoned without ``stop``) holds nothing any more: its tasks can never run
            # again, so the claim is free rather than permanent.
            if owner is not None and owner is not self and not owner._abandoned():
                return False
            _OWNERS[name] = self
            return True

    def _abandoned(self) -> bool:
        """Return whether the loop this host started on is closed, so that nothing of it can still run."""
        return self._loop is not None and self._loop.is_closed()

    def _unclaim(self, name: str) -> None:
        with _OWNERS_LOCK:
            if _OWNERS.get(name) is self:
                del _OWNERS[name]

    async def _supervise(self, reg: TriggerRegistration) -> None:
        """Decide whether this process runs the trigger, run it, and give back what it took."""
        name = reg.name
        if not self._claim(name):
            self._set(reg, TriggerState.SKIPPED, "another runtime in this process runs it")
            return
        lock: SingletonLock | None = None
        try:
            if reg.trigger.scope is TriggerScope.MACHINE:
                lock = SingletonLock(self._lock_dir / f"{name}.lock")
                try:
                    while not lock.acquire():
                        self._set(reg, TriggerState.STANDBY, "another process on this machine runs it")
                        await asyncio.sleep(self._retry)
                except OSError as error:  # the lock file cannot be opened: a read-only home, a full disk
                    logger.warning("triggers.failed", extra={"trigger": name, "error": repr(error)})
                    self._set(reg, TriggerState.FAILED, f"cannot take the machine lock: {error}")
                    return
            self._set(reg, TriggerState.RUNNING)
            try:
                await reg.trigger.run(partial(self._fire, reg))
            except asyncio.CancelledError:
                self._set(reg, TriggerState.STOPPED)
                raise
            except Exception as error:  # noqa: BLE001 - a trigger's defect must not take the runtime with it
                logger.warning("triggers.failed", extra={"trigger": name, "error": repr(error)})
                self._set(reg, TriggerState.FAILED, repr(error))
            else:
                self._set(reg, TriggerState.FINISHED)
        except asyncio.CancelledError:
            if self._status[name].state is not TriggerState.STOPPED:
                self._set(reg, TriggerState.STOPPED)
            raise
        finally:
            if lock is not None:
                lock.release()
            self._unclaim(name)

    async def _fire(self, reg: TriggerRegistration, payload: Mapping[str, object] | None = None) -> None:
        """Deliver one event to the plugin's handler; what the handler raises costs only this event."""
        event = TriggerEvent(reg.name, dict(payload or {}), time.time())
        try:
            outcome = reg.handler(event)
            if inspect.isawaitable(outcome):
                await outcome
        except Exception as error:  # noqa: BLE001 - one bad event must not stop the trigger
            logger.warning("triggers.handler_failed", extra={"trigger": reg.name, "error": repr(error)})
