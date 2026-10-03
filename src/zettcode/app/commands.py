"""Slash commands shared by the application and coding agent."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from ..tui import Page


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What a command wants the application to display or open.

    A handler returns this instead of touching widgets, so a command describes
    its effect and the application decides when and how to paint it. Every field
    is optional; the default result changes nothing.

    Attributes:
        messages: Markdown documents appended to the transcript, in order. Each
            is parsed and rendered like an answer, so a command can report with
            headings, lists, and inline code instead of plain text.
        notification: One-line toast shown after a successful run; ``None``
            shows no toast.
        page: :class:`~zettcode.tui.Page` to present over the conversation after
            the result; the handler builds it, and its ``overlay_rows`` decides
            between a bottom panel and the whole screen.
        relayout: Re-measure the widget tree after applying the result. Set it
            when the change affects geometry a fixed-height row already
            measured, such as the header showing a new model name.
    """

    messages: tuple[str, ...] = ()
    notification: str | None = None
    page: Page | None = None
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
            :class:`~zettcode.app.agent.ZettCodeAgent`.
        handler: Runs the command, receiving the trimmed text after the name
            (``""`` when the user typed none) and returning a
            :class:`CommandResult` describing what to show next. Raising
            ``ValueError`` reports a usage error instead of changing state.
    """

    name: str
    description: str
    type: Literal["app", "agent"]
    handler: Callable[[str], Awaitable[CommandResult]]
