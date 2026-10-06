"""Slash commands shared by the application and coding agent."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeAlias

from ..tui import Widget
from .registry import Provider


class CommandUi(ABC):
    """The surfaces a command may write to while it runs.

    A handler used to describe everything it wanted to show in the
    :class:`CommandResult` it returned, which meant a long command could not say
    anything until it finished. With this it can report as it goes — a heading
    before the slow part, a failure the moment one happens — and still return a
    result for whatever is left to do (a page to open, a re-layout).
    """

    @abstractmethod
    def markdown(self, text: str) -> None:
        """Append Markdown to the transcript, parsed like an answer."""

    @abstractmethod
    def notice(self, text: str) -> None:
        """Append a muted one-line remark."""

    @abstractmethod
    def error(self, text: str) -> None:
        """Append a one-line failure, painted as an error."""

    @abstractmethod
    def notify(self, text: str, *, level: str = "info") -> None:
        """Show a one-off toast, replacing any that is still on screen."""


@dataclass(frozen=True, slots=True)
class CommandContext:
    """What one command handler is handed.

    Attributes:
        argument: Trimmed text after the command name; ``""`` when none.
        ui: Surfaces the command may write to while it runs.
    """

    argument: str
    ui: CommandUi


#: Signature of a slash-command handler: its context in, what to show next out.
CommandHandler: TypeAlias = Callable[[CommandContext], Awaitable["CommandResult"]]


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What a command wants the application to display or open.

    A handler returns this instead of touching widgets, so a command describes
    its effect and the application decides when and how to paint it. Every field
    is optional; the default result changes nothing.

    Attributes:
        message: Markdown appended to the transcript when the command wants to
            report something. It is parsed and rendered like an answer, so a
            command can use headings, lists, and inline code instead of plain
            text.
        notification: One-line toast shown after a successful run; ``None``
            shows no toast.
        widget: Widget to present over the conversation after the result. The
            handler composes it, including its own panel or full-screen layout,
            and the application only pushes it as a screen.
        relayout: Re-measure the widget tree after applying the result. Set it
            when the change affects geometry a fixed-height row already
            measured, such as the header showing a new model name.
    """

    message: str = ""
    notification: str | None = None
    widget: Widget | None = None
    relayout: bool = False


@dataclass(frozen=True, slots=True)
class Command:
    """One slash command: how the menu shows it and what runs it.

    Attributes:
        name: The command as typed, including the leading slash (``"/model"``);
            it is also the completion value inserted into the composer.
        description: One-line summary shown in the completion menu and in
            ``/help``.
        type: Which layer owns the command. ``"app"`` is a local UI action such
            as ``/theme`` or ``/quit``; ``"agent"`` acts on the conversation,
            its sessions, or the model, and is handled by
            :class:`~zettcode.app.agent.ZettCodeAgent`; ``"plugin"`` comes from
            an installed plugin, registered through
            :class:`~zettcode.plugins.PluginContainer`.
        handler: Runs the command with a :class:`CommandContext` — the trimmed
            argument and the UI surfaces it may write to while it works — and
            returns a :class:`CommandResult` describing anything left to show.
            Raising ``ValueError`` reports a usage error instead of changing
            state.
    """

    name: str
    description: str
    type: Literal["app", "agent", "plugin"]
    handler: CommandHandler


class CommandProvider(Provider[Command]):
    """One source of slash commands, merged with the others by the shell."""

    @property
    def commands(self) -> tuple[Command, ...]:
        """Return this source's commands, in display order."""
        return tuple(self.items)


class CommandList(CommandProvider):
    """A provider over commands that already exist."""

    def __init__(self, commands: Sequence[Command] = ()) -> None:
        """Keep the commands exactly as given, order included."""
        self._commands = tuple(commands)

    @property
    def items(self) -> Sequence[Command]:
        """Return the stored commands."""
        return self._commands
