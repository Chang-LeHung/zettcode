"""What a plugin receives when it activates, and how it registers.

The container is the plugin's only channel to the application: it exposes the
resolved configuration and collects the slash commands and row segments the
plugin registers. They are accumulated here rather than returned, so a plugin
can decide what to register from the configuration it is given.

Row segments are registered into one of the four slots — a row and a side — by
the method that names it, so a plugin never passes a side around. A segment
whose name already exists in the row replaces it in place; a new name appends
after the segments already in the slot. The builtin rows register first, so
reusing its segment names is what taking a slot over means.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..app.commands import Command, CommandHandler, CommandList, CommandProvider
from .state import UiRow, UiSegment

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from ..app.agent.mentions import MentionProvider
    from ..config import ZettCodeConfig
    from .state import UiBuilder, UiRegion, UiSide


#: Rows and sides in paint order; the shell's frame, fixed by the application.
UI_REGIONS: tuple[UiRegion, ...] = ("header", "status")
UI_SIDES: tuple[UiSide, ...] = ("left", "right")


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


class PluginContainer:
    """What a plugin is handed when it activates.

    The container is the plugin's only channel to the application: it exposes
    the resolved configuration, and collects the commands and row segments the
    plugin registers. They are accumulated here rather than returned, so a
    plugin can decide what to register from the configuration it is given.
    """

    def __init__(self, config: ZettCodeConfig) -> None:
        """Keep the resolved settings and open an empty command list."""
        self.config = config
        self.workspace = config.workspace
        self._command_providers: list[CommandProvider] = []
        self._mentions: list[MentionProvider] = []
        self._slots = UiSlots()

    @property
    def commands(self) -> tuple[Command, ...]:
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
    def mentions(self) -> tuple[MentionProvider, ...]:
        """Return the ``@`` resource providers registered so far."""
        return tuple(self._mentions)

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

    def register_command(self, name: str, description: str, handler: CommandHandler) -> Command:
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
        if any(command.name == name for command in self.commands):
            raise ValueError(f"Command already registered: {name}")
        return self.register_command_provider(
            CommandList(
                (
                    Command(
                        name=name,
                        description=description,
                        type="plugin",
                        handler=handler,
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
        registered = {command.name for command in self.commands}
        for command in provider.items:
            if not command.name.strip() or command.name == "/":
                raise ValueError("Command name cannot be empty")
            if command.name in registered:
                raise ValueError(f"Command already registered: {command.name}")
        self._command_providers.append(provider)
        return provider

    def register_mention(self, provider: MentionProvider) -> MentionProvider:
        """Register one kind of ``@`` resource the composer can offer.

        A provider lists candidates for the completion menu and expands a
        token into the text the model sees; the builtin provider offers skills,
        and a plugin adds its own kind the same way it adds a command.

        Args:
            provider: Provider that owns one resource kind. Its ``kind`` must be
                unique across the application, because a token has no prefix to
                say which provider should resolve it.

        Returns:
            The registered provider, in case the plugin wants to keep it.

        Raises:
            ValueError: When the kind is blank or already registered.
        """
        kind = getattr(provider, "kind", "").strip()
        if not kind:
            raise ValueError("Mention provider kind cannot be empty")
        if kind in {existing.kind for existing in self._mentions}:
            raise ValueError(f"Mention provider already registered: {kind}")
        self._mentions.append(provider)
        return provider
