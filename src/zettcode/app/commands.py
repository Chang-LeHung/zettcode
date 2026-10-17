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

#: What the shell does with a command typed while a request is in flight.
#:
#: ``"refuse"`` is the default: the draft is turned away, exactly as a prompt
#: that cannot steer is. ``"queue"`` takes the draft and runs it the moment the
#: request in flight finishes — for a command whose whole point is to be usable
#: mid-reply, such as ``/btw``. ``"now"`` runs it at once, beside the request: for a
#: command that only looks at the session or changes a setting the request reads when it
#: needs it, so waiting for the request to end would be waiting for nothing (``/context``,
#: ``/title``, ``/theme``). A command that touches what a running request is built on — the
#: transcript it is writing into, the session, the model it started with — must not say
#: ``"now"``; it never gets the busy state to itself, because it runs without taking it.
BusyPolicy: TypeAlias = Literal["refuse", "queue", "now"]


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
class Subcommand:
    """One word a command takes first, offered by the completion menu once the command is typed.

    Attributes:
        name: The word as typed (``"add"``); it replaces what the reader has typed after the command.
        description: One-line summary shown beside it in the menu.
        needs_more: The word is only the start of an argument (``/config add`` still asks which
            provider). Enter on it fills it in and leaves the rest to the reader; without this,
            Enter on it runs the command with it, as for a model or a level that says everything.
        current: The word names what is in force now. The menu marks it and opens with it highlighted,
            so Enter straight after the space changes nothing.
    """

    name: str
    description: str = ""
    needs_more: bool = False
    current: bool = False


#: What a command offers after its name: a fixed list, or a function asked each time the menu opens, for a
#: list that depends on the session (the models configured, the reasoning levels the model takes). A bare
#: string is a subcommand with no description.
Subcommands: TypeAlias = Sequence[Subcommand | str] | Callable[[], Sequence[Subcommand | str]]


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
        when_busy: What the shell does when the command is typed while a
            request is in flight: ``"refuse"`` (the default) turns the draft
            away, ``"queue"`` holds it and runs it as soon as that request ends,
            and ``"now"`` runs it at once without disturbing the request (see
            :data:`BusyPolicy` for what that is safe for).
        subcommands: The words the command takes first (``/config add``), offered by the
            completion menu once the command and a space are typed. A function is asked each
            time the menu opens. They only suggest: the handler still receives whatever was
            typed as its ``argument`` and decides what it means.
        preview: Called with the highlighted word as the reader walks the subcommand menu, to show its effect without
            choosing it (``/theme`` repaints in the palette), and with ``None`` when the menu goes away without the
            word having been run, to put things back. Only the menu's own movement calls it; a command typed out in
            full is simply run.
    """

    name: str
    description: str
    type: Literal["app", "agent", "plugin"]
    handler: CommandHandler
    when_busy: BusyPolicy = "refuse"
    subcommands: Subcommands = ()
    preview: Callable[[str | None], None] | None = None

    def options(self) -> tuple[Subcommand, ...]:
        """Return the subcommands to offer now."""
        source = self.subcommands
        return tuple(
            Subcommand(item) if isinstance(item, str) else item for item in (source() if callable(source) else source)
        )


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
