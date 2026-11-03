"""The page ``/bash`` opens: a command line over the workspace, with the history and the Tab completion of a shell."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence

from zettcode.app.commandline import CommandHistory, CommandRunner, ShellCompleter
from zettcode.tui import ConsolePanel

from .. import labels

#: What ends the page when typed, as it ends a shell.
LEAVING = frozenset({"exit", "quit"})

#: What empties the output, under the names shells use for it.
CLEARING = frozenset({"clear", "cls"})


class BashPage(ConsolePanel):
    """Run commands one at a time in the workspace and show what they print.

    The screen is :class:`~zettcode.tui.ConsolePanel`; this joins it to a :class:`CommandRunner`, which starts the
    processes, the reader's shell histories, which Up and Ctrl-R walk, and a :class:`ShellCompleter`, which Tab
    asks. Commands the reader types here are appended to ZettCode's own history file, so they are there the next
    time, whichever shell they were meant for.

    Args:
        runner: Starts the commands and keeps the directory they run in.
        history: Where earlier commands are read from and new ones are written.
        entries: The earlier commands, oldest first (read beforehand, off the event loop).
        on_close: Called when the reader leaves, instead of the page popping itself.
        initial: A command to run as soon as the page is on screen.
    """

    def __init__(
        self,
        runner: CommandRunner,
        history: CommandHistory,
        entries: Sequence[str] = (),
        *,
        on_close: Callable[[], None] | None = None,
        initial: str = "",
    ) -> None:
        self.completer = ShellCompleter(lambda: runner.cwd, entries)
        super().__init__(
            title=f"Shell ({runner.launcher.name})" if runner.launcher.name else "Shell",
            location=labels.compact_path(runner.cwd, limit=None),
            prompt=runner.launcher.prompt,
            completer=self.completer,
            history=entries,
            on_submit=self.run,
            on_interrupt=runner.stop,
            on_close=on_close,
        )
        self.runner = runner
        self.history = history
        self.initial = initial
        self._task: asyncio.Task[None] | None = None

    def on_mount(self) -> None:
        """Run the command ``/bash`` was given, now that the page has a clock to time it by."""
        if self.initial:
            command, self.initial = self.initial, ""
            self.run(command)

    def run(self, command: str) -> None:
        """Run a command the way Enter does: the page's own words first, then the reader's shell."""
        word = command.strip()
        if word in CLEARING:
            self.clear()
            return
        if word in LEAVING:
            self.close()
            return
        self.history.record(command)
        self.completer.history = (*self.completer.history, command)
        self.echo(command)
        self.begin()
        self._task = asyncio.ensure_future(self._execute(command))

    async def _execute(self, command: str) -> None:
        """Run to the end, then say how it went and where the next command will run."""
        result = await self.runner.run(command, self.write)
        self.set_location(labels.compact_path(self.runner.cwd, limit=None))
        self.finish(result.text)

    def on_unmount(self) -> None:
        """Stop what is still running when the page goes, so no command outlives the screen that shows it."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
