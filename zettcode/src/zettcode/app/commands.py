"""Slash commands shared by the application and coding agent."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias

from zettcode.registry import Provider
from zettcode.sdk.errors import ZettCodeError

from ..tui import Widget

#: What a command may fail with and have the reader told in words: a bad argument (``ValueError``), or the SDK saying
#: the session is locked, busy or missing. Anything else is a bug and is reported as one.
COMMAND_ERRORS = (ValueError, ZettCodeError)

if TYPE_CHECKING:  # pragma: no cover - annotations only; the agent and the config are not imported by this module
    from ..sdk.client import Client
    from ..sdk.types import ModelInfo
    from .agent.agent import TerminalAgent
    from .agent.conversation.transcript import Transcript


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


class CommandHost(Protocol):
    """What a command that acts on the application, and not only on the agent, may ask of the shell.

    A command that opens a panel, switches the session or changes the model needs more than a place to write:
    it needs the agent, the transcript it is drawn into, and the few shell operations that change what is on
    screen. This is that list and no more. The shell is what a plugin's command gets (it is the object the
    context calls ``host``), so a plugin can provide ``/resume`` or ``/model`` without importing the shell, and
    the shell stays free to change everything that is not named here.

    Attributes:
        agent: The application agent: models, sessions, effort, permission, the context report.
        client: The SDK client over that agent, which is how a command reaches what the SDK offers.
        transcript: The conversation as drawn; a command reports into it with ``notice`` and ``error``.
        commands: Every command the shell knows, in the order ``/help`` lists them.
    """

    agent: TerminalAgent
    client: Client
    transcript: Transcript
    commands: tuple[Command, ...]

    def close_page(self) -> None:
        """Close the page a command presented and return to the composer."""

    def request_layout(self) -> None:
        """Ask for the screen to be laid out again, after a change in what it shows."""

    async def wait_for_frame(self) -> None:
        """Wait until the next frame has reached the terminal.

        A command that has just put a row on screen and is about to start work
        with no ``await`` in it asks for this first: the row is drawn before the
        work begins instead of after it.
        """

    def offer(self, command: str) -> None:
        """Put ``command`` and a space in the draft, which opens the menu of the words it takes."""

    def quit(self) -> None:
        """Leave the application."""

    def select_session(self, session_id: str) -> None:
        """Switch to a session picked in a panel: close the panel and resume behind the interface."""

    async def resume_session(self, session_id: str) -> None:
        """Restore a stored session without holding the event loop for the work."""

    async def fork_session(self) -> str:
        """Carry this conversation into a new session and continue there; return the new id."""

    async def rename_session(self, title: str) -> str:
        """Name the active session and return the name as stored."""

    async def run_continue(self) -> None:
        """Carry on the request that was interrupted."""

    async def run_side_question(self, question: str) -> None:
        """Answer a question that is kept out of the conversation."""

    async def prompt(self, text: str, *, shown: str | None = None) -> bool:
        """Run ``text`` as one turn of this conversation, exactly as if the reader had typed it.

        The text reaches the model the way a draft does: stored in the session, streamed as it is answered, and
        settled by the same row. ``@`` references are resolved.

        A command whose instructions are longer than what it wants to show passes the two apart: ``text`` is what
        the model reads, ``shown`` is what the transcript draws in its place. A reader who typed ``/code-review``
        sees that, not the brief it stands for — while the model reads the brief with that turn, then and in every
        later turn, because the brief is part of the message the session keeps. Only its display is short.

        The turn is awaited, so the command that asked for it holds the request slot until it has been answered,
        and the row the shell shows is the command's own.

        Args:
            text: What to ask. With no ``shown``, this is also what the reader sees.
            shown: What the transcript shows, when it differs from ``text``. The message the session keeps is
                the same either way: ``text`` is in it, and ``shown`` is what a reader is shown of it.

        Returns:
            Whether a turn was started and has ended. A request already running, a blank text and a session held
            by another process answer ``False``, and nothing is started. A command that means to be usable
            mid-request says ``when_busy="queue"``, and this then runs when the request in flight has ended.
        """

    def change_model(self, name: ModelInfo | str) -> ModelInfo:
        """Switch models and announce the change in the transcript."""

    def select_model(self, name: ModelInfo) -> None:
        """Apply a model picked in a panel and close the panel."""

    def change_effort(self, name: str) -> str:
        """Switch reasoning effort and announce the change."""

    def change_permission(self, name: str) -> str:
        """Set how much of the shell may run unasked and announce the change."""


@dataclass(frozen=True, slots=True)
class CommandContext:
    """What one command handler is handed.

    Attributes:
        argument: Trimmed text after the command name; ``""`` when none.
        ui: Surfaces the command may write to while it runs.
        host: The shell, for a command that acts on the application itself; ``None`` where there is no shell,
            such as a handler called directly in a test. Use :meth:`require_host` in a command that needs it.
    """

    argument: str
    ui: CommandUi
    host: CommandHost | None = None

    def require_host(self) -> CommandHost:
        """Return the shell, or raise ``RuntimeError`` when the command was run without one."""
        if self.host is None:
            raise RuntimeError("This command acts on the application and needs the shell to run it")
        return self.host


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


def subcommand_words(names: Sequence[str], notes: dict[str, str], current: str = "") -> tuple[Subcommand, ...]:
    """Offer each name a command takes, with its note and a mark on the one in force."""
    return tuple(Subcommand(name, notes.get(name, ""), current=name == current) for name in names)


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
            :class:`~zettcode.app.agent.TerminalAgent`; ``"plugin"`` comes from
            an installed plugin, registered through
            :class:`~zettcode.engine.plugins.context.PluginContext`.
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
