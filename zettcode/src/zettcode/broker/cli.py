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
from abc import ABC, abstractmethod
from collections.abc import Callable
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


class Companions(ABC):
    """Processes that live on the broker and cannot survive its being replaced, which a restart has to deal with.

    The broker knows nothing of what they are (background agents, in practice: :mod:`zettcode.daemon`); the command
    that starts it hands one in. A new broker may speak another protocol, and a session still running the old code
    then waits for ever, so they are stopped before the broker and started again after it.
    """

    @abstractmethod
    def listing(self) -> list[str]:
        """Return one line for each process that is running now; empty when there is none."""

    @abstractmethod
    def stop(self) -> list[str]:
        """Stop every one of them, remember what is needed to start them again, and return a line for each."""

    @abstractmethod
    def start(self) -> list[tuple[bool, str]]:
        """Start again what :meth:`stop` stopped; return, for each, whether it worked and a line to show."""


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
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="restart: do not ask before stopping and starting again the background agents running on the broker",
    )
    return parser


def broker_program(argv: list[str] | None = None, companions: Companions | None = None) -> int:
    """Entry point of ``zettcode broker``; the exit status is what the shell reads: 0 done, 1 failed.

    Args:
        argv: The arguments after ``broker``.
        companions: What has to be stopped and started again with the broker on a ``restart``, if anything.
    """
    args = build_parser().parse_args(argv)
    directory = broker_dir()
    if args.action == "restart":
        return restart(directory, companions, assume_yes=args.yes)
    action = {"start": start, "stop": stop}[args.action]
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


def restart(
    directory: Path,
    companions: Companions | None = None,
    *,
    assume_yes: bool = False,
    ask: Callable[[str], str] = input,
    interactive: Callable[[], bool] = lambda: sys.stdin.isatty(),
) -> int:
    """Stop the broker if one is running, then start one; with ``companions`` running, only once the person agrees.

    Those are stopped first and started again after the broker, because a session that outlives its broker is cut off
    from the new one when the protocol changed. Saying no (or not being able to say anything: no terminal and no
    ``--yes``) changes nothing at all.

    Args:
        directory: The broker's directory.
        companions: What lives on the broker, or ``None`` for nothing.
        assume_yes: Do not ask.
        ask: Reads the answer, injectable for tests.
        interactive: Whether anybody can be asked.
    """
    running_now = companions.listing() if companions is not None else []
    if companions is not None and running_now and not _agreed(running_now, assume_yes, ask, interactive):
        return EXIT_FAILED
    if companions is not None and running_now:
        for line in companions.stop():
            print(line)
    if running(directory) and stop(directory) != EXIT_OK:
        # The broker is still the old one, so what was stopped for it is brought back rather than left off.
        return _bring_back(companions, running_now, EXIT_FAILED)
    status = start(directory)
    if status != EXIT_OK:
        return _bring_back(companions, running_now, status)
    return _bring_back(companions, running_now, EXIT_OK)


def _agreed(
    running_now: list[str], assume_yes: bool, ask: Callable[[str], str], interactive: Callable[[], bool]
) -> bool:
    """Show what a restart will stop, and return whether the person agreed to it."""
    count = len(running_now)
    print(f"{count} background agent{'s are' if count != 1 else ' is'} running on the broker:")
    for line in running_now:
        print(f"  {line}")
    print(
        "They are stopped, and started again from their own sessions after the broker is: nothing they wrote is lost."
    )
    if assume_yes:
        return True
    if not interactive():
        print("not restarting: nobody can be asked here. Run it in a terminal, or add --yes.", file=sys.stderr)
        return False
    try:
        answer = ask("Stop them and restart the broker? [y/N] ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if answer.strip().lower() in ("y", "yes"):
        return True
    print("not restarting; nothing was changed.")
    return False


def _bring_back(companions: Companions | None, running_now: list[str], status: int) -> int:
    """Start again what a restart stopped and report each; the status is the broker's unless one of them failed."""
    if companions is None or not running_now:
        return status
    failed = False
    for worked, line in companions.start():
        print(line, file=sys.stdout if worked else sys.stderr)
        failed = failed or not worked
    return EXIT_FAILED if failed else status


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


__all__ = ["Companions", "broker_program", "build_parser", "restart", "running", "start", "stop"]
