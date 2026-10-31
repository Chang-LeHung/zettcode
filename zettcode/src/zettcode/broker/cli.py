"""``zettcode broker``: start, stop, or restart the session broker by hand.

A broker is normally started by the first session that needs one and stops itself when the last session leaves, so
this command is for the person who wants to say so directly: after an upgrade, on a machine where a broker is stuck,
or before a session is opened. It decides nothing about messages; it only turns the process on and off.

The broker is found and watched by the lock it holds, never by the note alone (:mod:`zettcode.filelock`): a note can
outlive the process that wrote it, a held lock cannot. Stopping reuses the same ending as a broker of an older
protocol (:mod:`.process`), which recognises the process before touching it, asks it to stop, and waits for the lock.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ..filelock import is_held
from . import process
from .files import MODULE, Note, broker_dir, lock_path, log_path, read_note, remove_note
from .finder import spawn_broker

EXIT_OK = 0
EXIT_FAILED = 1

#: Seconds to wait for a broker that was just started to write the note that says where it listens.
START_WAIT = 8.0

#: How often the note and the lock are looked at while waiting.
POLL = 0.05


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for ``zettcode broker`` and the three things it can do."""
    parser = argparse.ArgumentParser(
        prog="zettcode broker",
        description=(
            "Start, stop, or restart the session broker: the background process that lets ZettCode sessions on this "
            "machine message each other. A broker starts by itself when a session needs one."
        ),
    )
    parser.add_argument(
        "action",
        choices=("start", "stop", "restart"),
        help="start a broker if there is none, stop the one there is, or do both",
    )
    return parser


def broker_program(argv: list[str] | None = None) -> int:
    """Entry point of ``zettcode broker``; the exit status is what the shell reads: 0 done, 1 failed."""
    args = build_parser().parse_args(argv)
    directory = broker_dir()
    action = {"start": start, "stop": stop, "restart": restart}[args.action]
    return action(directory)


def running(directory: Path) -> bool:
    """Return whether a broker holds its lock in ``directory``, which is the only reliable sign that one is there."""
    return is_held(lock_path(directory))


def start(directory: Path) -> int:
    """Start a broker unless one is running, and say where it listens."""
    if running(directory):
        note = read_note(directory)
        where = f" (pid {note.pid}, port {note.port})" if note is not None else ""
        print(f"the broker is already running{where}")
        return EXIT_OK
    before = read_note(directory)
    try:
        spawn_broker(directory)
    except OSError as error:
        print(f"the broker could not be started: {error}", file=sys.stderr)
        return EXIT_FAILED
    note = _wait_for_note(directory, before)
    if note is None:
        print(f"the broker did not start; the log is {log_path(directory)}", file=sys.stderr)
        return EXIT_FAILED
    print(f"broker {note.pid} listening on port {note.port}")
    return EXIT_OK


def stop(directory: Path) -> int:
    """Stop the broker that is running, and say what happened.

    A note whose broker has gone is removed rather than reported: it is what the next session would read, and a
    stale one only sends it to a port nobody is on.

    An explicit ``stop`` does not compare the broker's protocol version: that rule (never end a newer broker) is for
    a session replacing one automatically, so two versions do not end each other's in turn; a person who asks for
    this wants it stopped, whatever it says it speaks.
    """
    note = read_note(directory)
    if not running(directory):
        if note is not None:
            remove_note(directory, note.token)
        print("the broker is not running")
        return EXIT_OK
    if note is None:
        print("a broker holds the lock but left no note, so it cannot be identified", file=sys.stderr)
        return EXIT_FAILED
    if process.end(note.pid, MODULE, released=lambda: not running(directory)):
        print(f"stopped broker {note.pid}")
        return EXIT_OK
    print(f"broker {note.pid} did not stop; it was not recognised as one, or it took too long", file=sys.stderr)
    return EXIT_FAILED


def restart(directory: Path) -> int:
    """Stop the broker if one is running, then start one."""
    if running(directory) and stop(directory) != EXIT_OK:
        return EXIT_FAILED
    return start(directory)


def _wait_for_note(directory: Path, before: Note | None) -> Note | None:
    """Wait for a broker to say where it listens: a note different from the one that was there before it started.

    The token is new on every start, so a note left by a broker that died is not mistaken for the new one; another
    session that won the race to start a broker also writes a new one, and either answer is the broker to report.
    """
    deadline = time.monotonic() + START_WAIT
    while time.monotonic() < deadline:
        note = read_note(directory)
        if note is not None and (before is None or note.token != before.token) and running(directory):
            return note
        time.sleep(POLL)
    return None


__all__ = ["broker_program", "build_parser", "restart", "running", "start", "stop"]
