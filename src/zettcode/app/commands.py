"""Slash commands shared by the application and coding agent."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What a command wants the application to display or open.

    A handler returns this instead of touching widgets, so a command describes
    its effect and the application decides when and how to paint it. Every field
    is optional; the default result changes nothing.

    Attributes:
        messages: Transcript lines to append, in order, as muted notices.
        notification: One-line toast shown after a successful run; ``None``
            shows no toast.
        page: Full-screen page to open after the result; the only page today is
            ``"models"``, which opens the model picker.
        relayout: Re-measure the widget tree after applying the result. Set it
            when the change affects geometry a fixed-height row already
            measured, such as the header showing a new model name.
    """

    messages: tuple[str, ...] = ()
    notification: str | None = None
    page: Literal["models"] | None = None
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
