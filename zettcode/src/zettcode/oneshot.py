"""Ask one question from the command line and print the answer: what ``zettcode prompt`` does.

The same agent as the terminal, run once through the SDK, for scripts and pipes. What goes where is fixed:

* **stdout** is the answer and nothing else, streamed, with one final newline.
* **stderr** is the rest: a line per tool used, notices, and the session id.
* **exit status**: 0 answered, 1 failed or stopped early, 2 unusable arguments, 3 nothing to continue, 130 interrupted.

Nobody can be asked, so the shell permission is always ``auto`` and a question from the model is declined. With
``--continue`` there is no prompt: the request of the session ``--session`` names that was cut short is picked up, as
``/continue`` does. The session is never guessed.
"""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from .cli import Options
    from .config import ZettCodeConfig
    from .sdk.client import Client
    from .sdk.session import RunStream

#: The shell permission of every run: nobody can be asked, and a level that asks would only make commands fail.
PERMISSION = "auto"

#: The exit statuses documented above.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NOTHING = 3
EXIT_INTERRUPTED = 130


class NoPrompt(ValueError):
    """There was no prompt to send."""


def read_prompt(text: str | None, stdin: TextIO | None = None) -> str:
    """Return the prompt: the argument as given, or standard input when there is none or it is ``-``.

    A terminal is never waited on, and standard input is not read when the argument is given.

    Raises:
        NoPrompt: There is nothing to send.
    """
    if text is not None and text != "-":
        piece = text
    else:
        stream = stdin if stdin is not None else sys.stdin
        if text is None and stream.isatty():
            raise NoPrompt("no prompt: give one after the command, or pipe one in")
        piece = stream.read()
    if not piece.strip():
        raise NoPrompt("the prompt is empty")
    return piece


def _note(err: TextIO, text: str) -> None:
    """Write one line about the run to stderr."""
    err.write(text + "\n")
    err.flush()


async def run_prompt(
    options: Options, text: str, out: TextIO, err: TextIO, *, config: ZettCodeConfig | None = None
) -> int:
    """Send ``text``, stream the answer to ``out``, and return the exit status; ``config`` replaces the file (tests)."""
    return await _run(options, lambda client: client.prompt(text), out, err, config)


async def run_continue(options: Options, out: TextIO, err: TextIO, *, config: ZettCodeConfig | None = None) -> int:
    """Pick up the cut-short request of the session ``options.resume`` names; it is required, and never guessed."""
    if options.resume is None:
        _note(err, "zettcode: --continue needs --session: name the session whose request was cut short")
        return EXIT_USAGE
    return await _run(options, lambda client: client.session.resume_stream(), out, err, config)


async def _run(
    options: Options,
    begin: Callable[[Client], RunStream],
    out: TextIO,
    err: TextIO,
    config: ZettCodeConfig | None,
) -> int:
    """Make a client, start the run ``begin`` makes on it, stream the answer to ``out``, and return the exit status."""
    from .sdk import Client
    from .sdk.errors import (
        ClientClosedError,
        ConfigurationError,
        NothingToDoError,
        RunError,
        SessionBusyError,
        SessionLockedError,
        SessionNotFoundError,
        WorkspaceConflictError,
    )
    from .sdk.events import Notice, TextDelta, ToolFinished, ToolStarted

    try:
        client = Client(
            options.workspace,
            model=options.model,
            effort=options.effort,
            permission=PERMISSION,
            resume=options.resume,
            config=config,
        )
    except (ConfigurationError, SessionNotFoundError, SessionLockedError, WorkspaceConflictError) as error:
        _note(err, f"zettcode: {error}")
        return EXIT_USAGE
    streamed = False
    try:
        async with client:
            try:
                async with begin(client) as run:
                    async for event in run:
                        if isinstance(event, TextDelta):
                            out.write(event.text)
                            out.flush()
                            streamed = True
                        elif isinstance(event, ToolStarted):
                            _note(err, f"[{event.name}]")
                        elif isinstance(event, ToolFinished) and not event.ok and not event.skipped:
                            _note(err, f"[{event.name}] failed")
                        elif isinstance(event, Notice):
                            _note(err, f"zettcode: {event.text}")
                result = run.result
            except RunError as error:
                if error.partial_text and not streamed:
                    out.write(error.partial_text)
                    streamed = True
                _finish_line(out, streamed)
                _note(err, f"zettcode: {error}")
                return EXIT_FAILED
            except NothingToDoError as error:
                _note(err, f"zettcode: nothing to continue: {error}")
                return EXIT_NOTHING
            except (ConfigurationError, SessionBusyError, ClientClosedError) as error:
                _note(err, f"zettcode: {error}")
                return EXIT_USAGE
            if result is not None and not streamed:
                out.write(result.text)
                streamed = bool(result.text)
            _finish_line(out, streamed)
            if result is not None:
                _note(err, f"session: {result.session_id}")
                if not result.ok:
                    reason = f"{result.stop}: {result.stop_message}" if result.stop_message else str(result.stop)
                    _note(err, f"zettcode: the model stopped before it finished ({reason})")
                    return EXIT_FAILED
            return EXIT_OK
    except SessionLockedError as error:
        _note(err, f"zettcode: {error}")
        return EXIT_USAGE


def _finish_line(out: TextIO, written: bool) -> None:
    """End the answer with a newline, so the shell's prompt does not land on its last line."""
    if written:
        out.write("\n")
        out.flush()


def prompt_program(
    options: Options,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    config: ZettCodeConfig | None = None,
) -> int:
    """Run ``zettcode prompt`` for ``options`` and return the exit status.

    With ``options.continue_request`` there is no prompt, and standard input is not read.
    """
    out = stdout if stdout is not None else sys.stdout
    err = stderr if stderr is not None else sys.stderr
    if options.continue_request:
        return _until_interrupted(lambda: run_continue(options, out, err, config=config), err)
    try:
        text = read_prompt(options.prompt, stdin)
    except NoPrompt as error:
        _note(err, f"zettcode: {error}")
        return EXIT_USAGE
    return _until_interrupted(lambda: run_prompt(options, text, out, err, config=config), err)


def _until_interrupted(run: Callable[[], Coroutine[Any, Any, int]], err: TextIO) -> int:
    """Run the coroutine ``run`` makes to its end and return its status; an interrupt is 130, with a newline."""
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        _note(err, "")
        return EXIT_INTERRUPTED
