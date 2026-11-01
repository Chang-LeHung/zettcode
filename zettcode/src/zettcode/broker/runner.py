"""The broker as a process: ``python -m zettcode.broker``.

It takes the singleton lock before anything else, so that of two brokers started together only one serves; it writes
the note a session reads (:mod:`.files`) once it is listening; it stops on a signal; and it keeps checking that the
files that announce it are still there.

That last one is for the person who deletes the broker's directory while it runs. That removes both the note a session
reads to find it and the file the lock is on; the next session would then start a second broker and take a lock on the
new file. A broker that sees its lock file replaced steps aside; one that only lost its note writes it again.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import secrets
import signal
import sqlite3
from pathlib import Path

from .. import logging_setup
from ..filelock import SingletonLock
from .files import STORE_FILE, Note, broker_dir, ensure_directory, lock_path, read_note, remove_note, write_note
from .log import log
from .protocol import PROTOCOL_VERSION
from .server import IDLE_EXIT, Broker
from .store import Store, TooNew

logger = logging.getLogger("zettcode.broker")

#: Overrides :data:`~.server.IDLE_EXIT`; a test's way of not waiting half a minute. A value that is not a positive
#: number is ignored.
IDLE_VARIABLE = "ZETTCODE_BROKER_IDLE"

#: Seconds a lock that someone else holds is waited for at start-up (see :meth:`SingletonLock.acquire`).
LOCK_WAIT = 0.5

#: Seconds between the broker checking that the files that announce it are still there.
WATCH_INTERVAL = 2.0


async def run(
    directory: Path, *, idle_exit: float = IDLE_EXIT, port: int = 0, watch_interval: float = WATCH_INTERVAL
) -> int:
    """Run the broker for ``directory`` until it is idle or told to stop.

    Returns:
        ``0``, including when another broker already holds the lock and this one has nothing to do; ``1`` when the
        broker could not start at all (the log says why).
    """
    ensure_directory(directory)
    logger.info("start", extra={"directory": str(directory), "idle_exit": idle_exit})
    lock = SingletonLock(lock_path(directory))
    if not lock.acquire(wait=LOCK_WAIT):
        log("another broker is already running; exiting")
        logger.info("already_running", extra={"directory": str(directory)})
        return 0
    token = secrets.token_urlsafe(24)
    store = _open_store(directory)
    broker = Broker(token, port=port, idle_exit=idle_exit, store=store)
    watcher: asyncio.Task[None] | None = None
    try:
        try:
            listening = await broker.start()
            write_note(directory, Note(os.getpid(), listening, token, PROTOCOL_VERSION))
        except OSError as error:
            logger.exception("start.failed", extra={"directory": str(directory)})
            log(f"the broker could not start: {error}")
            return 1
        log(f"broker {os.getpid()} listening on {broker.host}:{listening}")
        logger.info("listening", extra={"directory": str(directory), "port": listening})
        _stop_on_signals(broker)
        watcher = asyncio.ensure_future(_watch(directory, lock, broker, watch_interval))
        await broker.wait_closed()
    finally:
        if watcher is not None:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        await broker.aclose()
        store.close()
        remove_note(directory, token)
        lock.release()
        log("broker exiting")
        logger.info("stop", extra={"directory": str(directory)})
    return 0


def _open_store(directory: Path) -> Store:
    """Open the file the broker remembers in; a file that cannot be used leaves it remembering in memory only."""
    try:
        return Store(directory / STORE_FILE)
    except TooNew as error:
        logger.warning("store.too_new", extra={"directory": str(directory)})
        log(f"{error}; it is left alone and messages will not be remembered this time")
        return Store()
    except (OSError, sqlite3.Error):
        logger.exception("store.unavailable", extra={"directory": str(directory)})
        log("the history file could not be opened; messages will not be remembered this time")
        return Store()


def _stop_on_signals(broker: Broker) -> None:
    loop = asyncio.get_running_loop()
    for name in ("SIGTERM", "SIGINT"):
        number = getattr(signal, name, None)
        if number is not None:
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.add_signal_handler(number, broker.stop)  # Windows has none: the process is just ended


async def _watch(directory: Path, lock: SingletonLock, broker: Broker, interval: float) -> None:
    """Keep checking that the broker is still what the files on disk say it is."""
    while True:
        await asyncio.sleep(interval)
        if not lock.still_ours():
            log("the lock file was removed or replaced; stepping aside for a new broker")
            broker.stop()
            return
        current = read_note(directory)
        if current is None or current.token != broker.token:
            log("the broker's note was removed; writing it again")
            with contextlib.suppress(OSError):
                write_note(directory, Note(os.getpid(), broker.port, broker.token, PROTOCOL_VERSION))


def idle_seconds() -> float:
    """Return how long an idle broker waits before exiting: :data:`~.server.IDLE_EXIT`, or the environment's.

    A value that is missing, not a number, not finite or not positive is ignored: a typo must not turn into a broker
    that never exits.
    """
    try:
        value = float(os.getenv(IDLE_VARIABLE, ""))
    except ValueError:
        return IDLE_EXIT
    return value if math.isfinite(value) and value > 0 else IDLE_EXIT


def main() -> int:
    """Entry point of ``python -m zettcode.broker``.

    Any failure is written to the log with its traceback and ends the process with a nonzero status: a broker that
    dies is replaced by the next session that needs one, but only if the reason it died is somewhere a person can read.
    """
    logging_setup.setup("broker")
    try:
        return asyncio.run(run(broker_dir(), idle_exit=idle_seconds()))
    except KeyboardInterrupt:
        return 0
    except Exception as error:  # noqa: BLE001 - the log is the only place anyone will see this
        logger.exception("crashed")
        log(f"the broker failed: {type(error).__name__}")
        return 1


__all__ = ["IDLE_VARIABLE", "idle_seconds", "main", "run"]
