"""The commands a plugin may offer that say nothing about a front end.

A plugin registers a *plain* command on :attr:`~zettcode.engine.plugins.container.PluginContext.commands` when the
result is text: a paragraph to show and a one-line remark. No widget, no page, no question put to a person — those
belong to the terminal, which registers its own kind of command on ``ctx.tui`` (see
:class:`zettcode.app.plugins.groups.TuiGroups`). Keeping the two apart is what lets a command be shown by a front end
that has no terminal: the handler cannot reach for a shell it will not have.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeAlias

__all__ = [
    "CommandGroups",
    "PlainCommand",
    "PlainCommandContext",
    "PlainCommandResult",
    "PlainHandler",
]


@dataclass(frozen=True, slots=True)
class PlainCommandContext:
    """What a plain command's handler is handed: the words typed after its name, and nothing else."""

    argument: str = ""


@dataclass(frozen=True, slots=True)
class PlainCommandResult:
    """What a plain command reports: Markdown for the conversation, a toast, or a failure line.

    Every front end can show these three; that is the whole contract, which is why it is spelled here rather than
    borrowed from the terminal's richer ``CommandResult``.
    """

    message: str = ""
    notification: str = ""
    error: str = ""


#: A plain command's handler: sync or async, and it never needs a UI.
PlainHandler: TypeAlias = Callable[[PlainCommandContext], Awaitable[PlainCommandResult] | PlainCommandResult]


@dataclass(frozen=True, slots=True)
class PlainCommand:
    """One registered plain command: the name typed, the summary shown, and what runs it.

    ``when_busy`` is what a front end does with the command while a request is in flight (``"refuse"``,
    ``"queue"`` or ``"now"``), and ``subcommands`` are the words it takes first, for a menu that offers them. Both are
    the shell's vocabulary rather than a second one: a command that a process without a screen runs later should not
    need a different spelling.
    """

    name: str
    summary: str
    handler: PlainHandler
    when_busy: str = "refuse"
    subcommands: tuple[object, ...] = ()


class CommandGroups:
    """The plain commands one plugin offers, kept in registration order and unique by name."""

    def __init__(self) -> None:
        self._commands: dict[str, PlainCommand] = {}

    @property
    def commands(self) -> tuple[PlainCommand, ...]:
        """Return the commands registered so far, in registration order."""
        return tuple(self._commands.values())

    def register(
        self,
        name: str,
        summary: str,
        handler: PlainHandler,
        *,
        when_busy: str = "refuse",
        subcommands: tuple[object, ...] = (),
    ) -> PlainCommand:
        """Add one command that any front end can run.

        Args:
            name: The way it is typed, with its leading slash (``"/usage"``).
            summary: One line for the command list.
            handler: Runs with a :class:`PlainCommandContext` and returns a :class:`PlainCommandResult`.
            when_busy: What a front end does when it is typed while a request is in flight.
            subcommands: The words it takes first, offered by a menu that has one.

        Raises:
            ValueError: When the name or the summary is blank, or the name is already taken.
        """
        command = name.strip()
        if not command or not command.startswith("/"):
            raise ValueError(f"A command is typed with a leading slash, not {name!r}")
        if not summary.strip():
            raise ValueError(f"Command {command} needs a summary")
        if command in self._commands:
            raise ValueError(f"Command already registered: {command}")
        registered = PlainCommand(command, summary.strip(), handler, when_busy, tuple(subcommands))
        self._commands[command] = registered
        return registered
