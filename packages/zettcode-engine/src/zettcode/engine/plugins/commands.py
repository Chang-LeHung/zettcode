"""The commands a plugin may offer that say nothing about a front end.

A plugin registers a *plain* command on :attr:`~zettcode.engine.plugins.context.PluginContext.commands` when the
result is text: a paragraph to show and a one-line remark, or a request to start a turn. No widget, no page, no question put to a person — those
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
    "TextCommandResult",
    "TurnCommandResult",
]


@dataclass(frozen=True, slots=True)
class PlainCommandContext:
    """What a plain command's handler is handed.

    Attributes:
        argument: The words typed after the command's name.
        level: The shell level the session is running at (``deny``, ``ask``, ``safe`` or ``full``), filled by the
            front end that runs the command. A command that decides what to ask the model says it in these terms
            rather than reaching for a shell it may not have.
    """

    argument: str = ""
    level: str = "ask"


@dataclass(frozen=True, slots=True)
class TextCommandResult:
    """Words: Markdown for the conversation, an optional document, and a one-line remark.

    ``message`` is what the conversation keeps, as before. ``markdown`` is a document for the front end to show on its
    own — the terminal opens it as a page, the editor as a preview — for an answer too long to sit between two turns
    or one a reader means to read rather than scroll past. It is a new field and not a new result type, so a front end
    that predates it still runs the command and still shows ``message``.

    Attributes:
        message: Markdown added to the conversation.
        notification: A one-line remark, as a toast.
        markdown: A Markdown document shown by the front end in its own view; empty when there is none.
    """

    message: str = ""
    notification: str = ""
    markdown: str = ""


@dataclass(frozen=True, slots=True)
class TurnCommandResult:
    """A request to start rather than an answer: the text the model reads, and what the reader sees for it.

    A command that is a preset for a turn — `/code-review` is the first — says so by returning this. The front end
    that ran the command starts the turn with ``prompt``; ``shown`` is the short form the conversation keeps, which is
    what the reader typed.

    Attributes:
        prompt: What the model reads.
        shown: What the conversation keeps, when it is not ``prompt``.
        notification: A one-line remark, as a toast.
        cache: How the turn may use the provider's prompt cache: ``"read"`` for a one-off whose answer nobody will
            follow, ``"read_write"`` to extend the cached prefix, ``"off"`` for no directive at all. Empty leaves the
            front end's own default, which is ``"read_write"`` for a turn.
    """

    prompt: str
    shown: str = ""
    notification: str = ""
    cache: str = ""


#: What a plain command's handler answers with. A failure is not a third case: it raises ``ValueError``, which every
#: front end already reports as the command's error line.
PlainCommandResult: TypeAlias = TextCommandResult | TurnCommandResult


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
