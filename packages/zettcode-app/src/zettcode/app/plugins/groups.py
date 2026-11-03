"""The group a plugin registers what only the terminal can hold into: ``ctx.tui``.

The terminal is the one front end with a screen, so its contributions live apart from what every process shares: the
commands that open a page or need the shell, the palettes, the pets, the presenters, the header and status rows, the
line a request ends on, and the command providers that add commands dynamically. A process without a terminal has
``ctx.tui is None``, and a plugin that only adds these should start its ``activate`` with ``if ctx.tui is None:
return``.

The terminal's loader attaches one of these to the context it builds, so the context type itself says nothing about a
screen: :class:`~zettcode.engine.plugins.context.PluginContext` is the same object everywhere, and this is the group
only a terminal fills.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from zettcode.app.agent.conversation.entries import EntryKind
from zettcode.app.agent.conversation.presenters import Presenter
from zettcode.app.commands import Command, CommandList, CommandProvider
from zettcode.app.pets import PET_NAME, Pet, PetSource
from zettcode.engine.plugins.context import PluginContext
from zettcode.plugin_tui import TuiGroup
from zettcode.statusline import TURN_PREFIX
from zettcode.tui import RESERVED_THEMES, THEME_NAME, Theme, ThemeSource, file_theme

from .state import TurnBuilder, TurnSegment, UiBuilder, UiRegion, UiRow, UiSegment, UiSide

#: Rows and sides in paint order; the shell's frame, fixed by the application.
UI_REGIONS: tuple[UiRegion, ...] = ("header", "status")
UI_SIDES: tuple[UiSide, ...] = ("left", "right")

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from pathlib import Path

    from .state import UiBuilder, UiRegion


class UiSlots:
    """Named segments per row side, where a repeated name replaces in place."""

    def __init__(self) -> None:
        """Start with every slot empty."""
        self._slots: dict[tuple[UiRegion, UiSide], list[UiSegment]] = {}
        self._counter = 0

    def add(
        self,
        region: UiRegion,
        side: UiSide,
        name: str,
        builder: UiBuilder,
        *,
        override: bool = False,
    ) -> tuple[UiSegment, bool]:
        """Put one segment in a row, reporting whether it took a place.

        Args:
            region: Row the segment belongs to.
            side: Side used unless the name replaces a segment that has one.
            name: Identity within the row; blank means "always append".
            builder: Called once per paint with the current ``ShellContext``.
            override: Empty this side first, so the segment is the only one
                there. The other side of the row is untouched.

        Returns:
            The registered segment and whether it displaced another one: a
            replaced name or a cleared side counts, a plain append does not.
        """
        if override:
            displaced = bool(self._slots.get((region, side)))
            self._slots[(region, side)] = [UiSegment(name=name or self._auto_name(), builder=builder)]
            return self._slots[(region, side)][0], displaced
        if name:
            existing = self._find(region, name)
            if existing is not None:
                slots, index = existing
                slots[index] = UiSegment(name=name, builder=builder)
                return slots[index], True
        segment = UiSegment(name=name or self._auto_name(), builder=builder)
        self._slots.setdefault((region, side), []).append(segment)
        return segment, False

    def _auto_name(self) -> str:
        """Return the next name for a segment registered without one."""
        self._counter += 1
        return f"segment-{self._counter}"

    def rows(self) -> tuple[UiRow, ...]:
        """Return both rows with their sides in paint order, or nothing if empty."""
        if not self._slots:
            return ()
        return tuple(
            UiRow(
                region,
                tuple(self._slots.get((region, "left"), ())),
                tuple(self._slots.get((region, "right"), ())),
            )
            for region in UI_REGIONS
        )

    def take_from(self, other: UiSlots) -> None:
        """Start from a copy of ``other``, so later edits leave it untouched.

        The loader hands each plugin a registry seeded with what is already
        loaded: names and ``override`` then act on the real rows, and a plugin
        that fails can be dropped without disturbing them.
        """
        self._slots = {slot: list(segments) for slot, segments in other._slots.items()}
        self._counter = other._counter

    def _find(self, region: UiRegion, name: str) -> tuple[list[UiSegment], int] | None:
        """Return the slot holding ``name`` in ``region``, if any."""
        for (slot_region, _), segments in self._slots.items():
            if slot_region != region:
                continue
            for index, segment in enumerate(segments):
                if segment.name == name:
                    return segments, index
        return None


def require_tui(ctx: PluginContext) -> TuiGroup:
    """Return the terminal's group, or raise when this process has no screen.

    For a plugin whose whole purpose is the terminal — every builtin here — registering nothing silently would leave a
    session with no commands and no explanation. A third-party plugin that is useful in more than one process reads
    ``ctx.tui`` and returns early instead; this one is the loud version.
    """
    if ctx.tui is None:
        raise RuntimeError("this plugin needs the terminal, and this process has no screen")
    return ctx.tui


class TuiGroups(TuiGroup):
    """What only the terminal can hold: the registries behind ``ctx.tui``.

    Args:
        context: The context this plugin is activating with; the config and services are read through it, and the
            registries below belong to this activation.
    """

    def __init__(self, context: PluginContext) -> None:
        """Open the terminal's registries, all empty, for one plugin's activation."""
        self._context = context
        self._command_providers: list[CommandProvider] = []
        self._themes: list[ThemeSource] = []
        self._pets: list[PetSource] = []
        self._presenters: list[Presenter[Any]] = []
        self._slots = UiSlots()
        self._turn_segments: dict[str, TurnSegment] = {}
        self._focus_handlers: list[Callable[[bool], None]] = []
        self._turn_start_handlers: list[Callable[[], None]] = []
        self._turn_end_handlers: list[Callable[[bool], None]] = []

    @property
    def focus_handlers(self) -> tuple[Callable[[bool], None], ...]:
        """Return the handlers told when the terminal window gains or loses focus."""
        return tuple(self._focus_handlers)

    def register_focus_handler(self, handler: Callable[[bool], None]) -> Callable[[bool], None]:
        """Be told when the terminal gains (``True``) or loses (``False``) focus.

        The terminal asks for focus reports when it starts, so this is called for a reader who switched to another
        window and for one who came back; a terminal that does not report focus never calls it. It is a hook, not a
        row: what it does with the news — pause, notify, summarise — is the plugin's.
        """
        self._focus_handlers.append(handler)
        return handler

    @property
    def turn_start_handlers(self) -> tuple[Callable[[], None], ...]:
        """Return the handlers told when a turn of the conversation starts."""
        return tuple(self._turn_start_handlers)

    def register_turn_start_handler(self, handler: Callable[[], None]) -> Callable[[], None]:
        """Be told when a turn of the conversation starts, before its request is sent.

        The counterpart of :meth:`register_turn_end_handler`: a plugin that waits for the reader to stop asking
        cancels that wait here and arms it again when the turn ends. A side question and a resumed request are not
        turns; a turn a command starts with ``host.prompt`` is. A handler that raises is told once and the shell
        carries on.
        """
        self._turn_start_handlers.append(handler)
        return handler

    @property
    def turn_end_handlers(self) -> tuple[Callable[[bool], None], ...]:
        """Return the handlers told when a turn of the conversation ends."""
        return tuple(self._turn_end_handlers)

    def register_turn_end_handler(self, handler: Callable[[bool], None]) -> Callable[[bool], None]:
        """Be told when a turn of the conversation ends, after the row it ended on is settled.

        ``handler(completed)`` says whether the request was answered or was stopped or failed. A request the reader
        sent is a turn, and so is one a command started with ``host.prompt``; running a command is not itself a turn,
        and neither is a side question or a resumed request. This is called from inside the run that just ended,
        before the shell is free again, and nothing guards two turns at once: a handler that starts work schedules it
        rather than running a turn from here. A handler that raises is told once and the shell carries on.
        """
        self._turn_end_handlers.append(handler)
        return handler

    @property
    def turn_segments(self) -> tuple[TurnSegment, ...]:
        """Return the items of the line a request ends on registered so far, in the order they stand."""
        return tuple(self._turn_segments.values())

    def register_turn_segment(self, name: str, summary: str, builder: TurnBuilder) -> TurnSegment:
        """Add one item to the line a request ends on (``Processed for 12s \u00b7 22:53 \u00b7 ...``), after those already there.

        Each item is a segment of its own, joined to the others by the line's separator, and a switch of its own:
        ``[statusline] <name> = false`` and ``/statusline hide <name>`` leave it out. A name that exists replaces
        that item where it stands, which is how a plugin changes one of the program's.

        Args:
            name: Starts with ``turn-``; the switch's name.
            summary: What it shows, in one line, for the ``/statusline`` panel.
            builder: Called when a request ends with a :class:`~zettcode.app.plugins.state.TurnContext`; returns the
                text, or nothing to leave the item out this time. One that raises is left out.

        Raises:
            ValueError: The name does not start with ``turn-``.
        """
        if not name.startswith(TURN_PREFIX) or name == TURN_PREFIX:
            raise ValueError(f"A turn segment is named {TURN_PREFIX}<something>, not {name!r}")
        segment = TurnSegment(name, summary, builder)
        self._turn_segments[name] = segment
        return segment

    @property
    def registered_commands(self) -> tuple[Command, ...]:
        """Return the commands registered so far, in registration order."""
        return tuple(command for provider in self._command_providers for command in provider.items)

    @property
    def command_providers(self) -> tuple[CommandProvider, ...]:
        """Return the command sources registered so far, in registration order."""
        return tuple(self._command_providers)

    @property
    def slots(self) -> UiSlots:
        """Return the slot registry, so the loader can merge declared segments in."""
        return self._slots

    @property
    def presenters(self) -> tuple[Presenter[Any], ...]:
        """Return the presenters registered so far, in registration order."""
        return tuple(self._presenters)

    @property
    def themes(self) -> tuple[ThemeSource, ...]:
        """Return the palettes registered so far, in registration order."""
        return tuple(self._themes)

    @property
    def pets(self) -> tuple[PetSource, ...]:
        """Return the pets registered so far, in registration order."""
        return tuple(self._pets)

    @property
    def rows(self) -> tuple[UiRow, ...]:
        """Return both rows with the segments registered so far."""
        return self._slots.rows()

    def register_header_left(
        self, builder: UiBuilder, *, name: str = "", override: bool = False
    ) -> tuple[UiSegment, bool]:
        """Draw a segment on the header's left side.

        Returns:
            The segment, and whether it displaced one already there.
        """
        return self._slots.add("header", "left", name, builder, override=override)

    def register_header_right(
        self, builder: UiBuilder, *, name: str = "", override: bool = False
    ) -> tuple[UiSegment, bool]:
        """Draw a segment on the header's right side.

        Returns:
            The segment, and whether it displaced one already there.
        """
        return self._slots.add("header", "right", name, builder, override=override)

    def register_status_left(
        self, builder: UiBuilder, *, name: str = "", override: bool = False
    ) -> tuple[UiSegment, bool]:
        """Draw a segment on the status line's left side.

        Returns:
            The segment, and whether it displaced one already there.
        """
        return self._slots.add("status", "left", name, builder, override=override)

    def register_status_right(
        self, builder: UiBuilder, *, name: str = "", override: bool = False
    ) -> tuple[UiSegment, bool]:
        """Draw a segment on the status line's right side.

        Returns:
            The segment, and whether it displaced one already there.
        """
        return self._slots.add("status", "right", name, builder, override=override)

    def register_command(
        self,
        name: str,
        description: str,
        handler: Any,
        *,
        when_busy: Any = "refuse",
        subcommands: Any = (),
    ) -> Any:
        """Register one slash command the shell will offer and run.

        The leading slash is optional, so ``"deploy"`` and ``"/deploy"`` are the
        same command. ``description`` is the one line shown by the completion
        menu and ``/help``. ``handler`` is handed a
        :class:`~zettcode.app.commands.CommandContext`: the trimmed argument and
        the UI surfaces it may write to while it works
        (``context.ui.markdown``, ``.notice``, ``.error``, ``.notify``). It
        returns a :class:`~zettcode.app.commands.CommandResult` for anything left
        to show — a page to open, a re-layout. Raising ``ValueError`` reports a
        usage error instead of changing state.

        Args:
            name: Command as typed; a leading ``/`` is added when missing.
            description: One-line summary shown in the menu and in ``/help``.
            handler: Coroutine taking a
                :class:`~zettcode.app.commands.CommandContext` and returning the
                result.
            when_busy: What happens when the command is typed while a request is
                running. ``"refuse"`` (the default) turns it away; ``"queue"`` runs
                it when the request ends; ``"now"`` runs it at once, beside the
                request. Say ``"now"`` only for a command that does not touch what
                a running request is built on — it reads or reports, or changes a
                setting the request reads when it needs it — because it is run
                without the busy state to itself.
            subcommands: The words the command takes first, offered by the completion menu
                once the command and a space are typed: names, or
                :class:`~zettcode.app.commands.Subcommand` for a name with a description. A
                function returning them is asked each time the menu opens. They only suggest;
                the handler gets whatever was typed as ``context.argument``.

        Returns:
            The registered command, in case the plugin wants to keep it.

        Raises:
            ValueError: When the name is blank, or a command with that name was
                already registered by this plugin.
        """
        name = name.strip()
        if not name or name == "/":
            raise ValueError("Command name cannot be empty")
        name = name if name.startswith("/") else f"/{name}"
        if any(command.name == name for command in self.registered_commands):
            raise ValueError(f"Command already registered: {name}")
        return self.register_command_provider(
            CommandList(
                (
                    Command(
                        name=name,
                        description=description,
                        type="plugin",
                        handler=handler,
                        when_busy=when_busy,
                        subcommands=subcommands,
                    ),
                )
            )
        ).items[0]

    def register_command_provider(self, provider: CommandProvider) -> CommandProvider:
        """Register one source of slash commands.

        The singular :meth:`register_command` is the common case; a plugin that
        builds its commands together registers them as one provider instead.

        Args:
            provider: Source whose commands the shell will offer and run.

        Returns:
            The registered provider, in case the plugin wants to keep it.

        Raises:
            ValueError: When a command name is blank, or already registered by
                this plugin.
        """
        registered = {command.name for command in self.registered_commands}
        for command in provider.items:
            if not command.name.strip() or command.name == "/":
                raise ValueError("Command name cannot be empty")
            if command.name in registered:
                raise ValueError(f"Command already registered: {command.name}")
        self._command_providers.append(provider)
        return provider

    def register_theme(
        self,
        name: str,
        theme: Theme | Callable[[], Theme] | Path,
        *,
        description: str | Callable[[], str] = "",
    ) -> ThemeSource:
        """Offer a palette by name, so ``/theme <name>`` switches to it and the menu lists and previews it.

        The palette is a :class:`~zettcode.tui.Theme`, a function that builds one (called when the palette is
        first asked for, so offering many costs nothing until one is picked), or the path of a theme ``.toml``
        file, read the same way. A file of the reader's in ``~/.zettcode/themes`` with the same name replaces it.
        The name is one word and cannot be ``dark`` or ``light``, which are the program's own.

        Args:
            name: What ``/theme`` is typed with: letters, digits, ``.``, ``_`` and ``-``.
            theme: The palette, a function that returns it, or a path to its file.
            description: One line shown beside the name in the menu (or a function returning it). A path's own
                ``description`` key is used when this is left out.

        Returns:
            The registered source, in case the plugin wants to keep it.

        Raises:
            ValueError: When the name is not one word, is reserved, or this plugin already registered it.
        """
        name = name.strip()
        if not THEME_NAME.fullmatch(name):
            raise ValueError(f"Theme name must be one word of letters, digits, '.', '_' or '-': {name!r}")
        if name in RESERVED_THEMES:
            raise ValueError(f"Theme name is reserved: {name}")
        if any(existing.name == name for existing in self._themes):
            raise ValueError(f"Theme already registered: {name}")
        if isinstance(theme, Theme):
            fixed = theme
            source = ThemeSource(name, lambda: fixed, description)
        elif callable(theme):
            source = ThemeSource(name, theme, description)
        else:
            source = file_theme(name, theme)
            if description:
                source = ThemeSource(name, source.load, description)
        self._themes.append(source)
        return source

    def register_pet(
        self,
        name: str,
        pet: Pet | Callable[[], Pet],
        *,
        description: str | Callable[[], str] = "",
    ) -> PetSource:
        """Offer a pet by name, so ``/pet <name>`` switches to it and the menu lists and previews it.

        The pet is a :class:`~zettcode.app.pets.Pet`, or a function that builds one (called when the pet is
        first asked for, so offering many costs nothing until one is picked). The name is one word, and the
        ones the program ships (``slime``, ``cat``, ``sprout``) are taken: a pet that shares a name with an
        earlier one is not offered.

        Args:
            name: What ``/pet`` is typed with: letters, digits, ``.``, ``_`` and ``-``.
            pet: The pet, or a function that returns it.
            description: One line shown beside the name in the menu (or a function returning it).

        Returns:
            The registered source, in case the plugin wants to keep it.

        Raises:
            ValueError: When the name is not one word, or this plugin already registered it.
        """
        name = name.strip()
        if not PET_NAME.fullmatch(name):
            raise ValueError(f"Pet name must be one word of letters, digits, '.', '_' or '-': {name!r}")
        if any(existing.name == name for existing in self._pets):
            raise ValueError(f"Pet already registered: {name}")
        if isinstance(pet, Pet):
            fixed = pet
            source = PetSource(name, lambda: fixed, description)
        elif callable(pet):
            source = PetSource(name, pet, description)
        else:
            raise ValueError("A pet must be a zettcode.app.pets.Pet or a function that returns one")
        self._pets.append(source)
        return source

    def register_presenter(self, presenter: Presenter[Any]) -> Presenter[Any]:
        """Draw a kind of entry, or one family inside a kind, instead of the way it is drawn now.

        A presenter names a ``kind`` (one member of :class:`EntryKind`), or an ``entry_type`` when it
        draws one family of a kind — the edit row inside the tool rows, say. It is placed by its own
        :attr:`Presenter.priority`: the highest wins, and an equal priority goes to the later
        registration, so the built-in presenters (priority 0, registered first) are the default any
        plugin's presenter replaces. A plugin that wants to beat another plugin raises the
        ``priority`` on its presenter's class. A presenter registered for a whole kind draws every
        row of that kind unless a family outranks it.

        Args:
            presenter: The presenter.

        Returns:
            The presenter, in case the plugin wants to keep it.

        Raises:
            ValueError: When the object is not a presenter, or names neither a kind nor an entry
                class.
        """
        if not isinstance(presenter, Presenter):
            raise ValueError("A presenter must be a zettcode.app.agent.conversation.presenters.Presenter")
        if not isinstance(presenter.kind, EntryKind):
            raise ValueError("A presenter must name the kind of entry it draws")
        self._presenters.append(presenter)
        return presenter
