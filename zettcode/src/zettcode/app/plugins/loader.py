"""Load the plugins for the terminal: the engine's loader, plus the commands, palettes, pets, presenters and rows.

Everything the engine's :class:`~zettcode.engine.plugins.loader.Loader` checks and merges, this one does too, and in
addition it keeps command names, theme names and pet names unique and merges the header and status rows, so a plugin
that collides on any of them is skipped and reported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zettcode.engine.plugins.builtin_agent import AGENT_PLUGINS
from zettcode.engine.plugins.loader import Loader, run
from zettcode.engine.plugins.surfaces import TERMINAL_SURFACES
from zettcode.tui import RESERVED_THEMES

from .builtins import BUILTIN_PLUGINS
from .container import TerminalContainer, UiSlots
from .host import HOST_LINK, HostLink
from .plugin import TerminalPlugin, TerminalPlugins
from .state import TurnSegment

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterable, Mapping, Sequence
    from importlib.metadata import EntryPoint

    from zettcode.app.agent.conversation.presenters import Presenter
    from zettcode.app.commands import Command
    from zettcode.app.pets import PetSource
    from zettcode.config import ZettCodeConfig
    from zettcode.engine.plugins.container import PluginContainer
    from zettcode.engine.plugins.plugin import Plugin
    from zettcode.tui import ThemeSource


def load_terminal_plugins(
    config: ZettCodeConfig,
    *,
    entry_points: Iterable[EntryPoint] | None = None,
    builtins: Sequence[Plugin[Any]] = (*BUILTIN_PLUGINS, *AGENT_PLUGINS),
    shared: Mapping[str, object] | None = None,
) -> TerminalPlugins:
    """Load the builtin plugins and every enabled distribution into one bundle, for the terminal.

    The arguments are those of :func:`zettcode.engine.plugins.loader.load_plugins`; the builtins default to the
    terminal's own followed by the agent's.
    """
    bundle = run(
        TerminalLoader(config, shared),
        config,
        builtins=builtins,
        entry_points=entry_points,
        surfaces=TERMINAL_SURFACES,
    )
    assert isinstance(bundle, TerminalPlugins)
    return bundle


def terminal_plugins(config: ZettCodeConfig, shared: Mapping[str, object]) -> TerminalPlugins:
    """Load the plugins the terminal's way, in the shape :meth:`ZettCodeEngine.preview` takes as its loader."""
    return load_terminal_plugins(config, shared=shared)


def _terminal(container: PluginContainer) -> TerminalContainer:
    """Return ``container`` as the terminal's, which is the only kind this loader creates."""
    if not isinstance(container, TerminalContainer):
        raise TypeError(f"{type(container).__name__} is not a TerminalContainer")
    return container


class TerminalLoader(Loader):
    """The engine's loader with the terminal's registries."""

    def __init__(self, config: ZettCodeConfig, shared: Mapping[str, object] | None = None) -> None:
        super().__init__(config, shared, surfaces=TERMINAL_SURFACES)
        self.services.setdefault(HOST_LINK, HostLink())
        self.slots = UiSlots()
        self.turn_segments: dict[str, TurnSegment] = {}
        self.commands: list[Command] = []
        #: How many of ``commands`` the built-in plugins registered; they are loaded first.
        self.builtin_command_count = 0
        self.themes: list[ThemeSource] = []
        self.pets: list[PetSource] = []
        self.presenters: list[Presenter[Any]] = []
        self._claimed: set[str] = set()
        self._theme_names: set[str] = set(RESERVED_THEMES)
        self._pet_names: set[str] = set()

    def new_container(self) -> TerminalContainer:
        # Seed the registry with what is already loaded, so a segment that
        # reuses a name — or asks to override a side — acts on the real rows
        # instead of on an empty copy. A failure leaves it untouched.
        container = TerminalContainer(self.config, self.services)
        container.slots.take_from(self.slots)
        for segment in self.turn_segments.values():
            container.register_turn_segment(segment.name, segment.summary, segment.builder)
        return container

    def activated(self, plugin: Plugin[Any], container: PluginContainer) -> None:
        if isinstance(plugin, TerminalPlugin):
            terminal = _terminal(container)
            for region, side, slot_name, builder in plugin.ui_slots():
                terminal.slots.add(region, side, slot_name, builder)

    def clash(self, container: PluginContainer) -> str | None:
        terminal = _terminal(container)
        # Command lookup takes the first match, so a second plugin claiming the
        # same name would be silently unreachable. Reject the plugin instead.
        command_clash = next((command.name for command in terminal.commands if command.name in self._claimed), None)
        if command_clash is not None:
            return f"command {command_clash} is already registered by another plugin"
        found = super().clash(container)
        if found is not None:
            return found
        # `/theme <name>` has to mean one palette, so a name an earlier plugin (the built-in one first) or the
        # program itself already has is not shared out a second time.
        theme_clash = next((source.name for source in terminal.themes if source.name in self._theme_names), None)
        if theme_clash is not None:
            return f"theme {theme_clash} is already registered"
        # `/pet <name>` has to mean one pet, so a name an earlier plugin (the built-in one first) already has is not
        # shared out a second time.
        pet_clash = next((source.name for source in terminal.pets if source.name in self._pet_names), None)
        if pet_clash is not None:
            return f"pet {pet_clash} is already registered"
        return None

    def merge(self, container: PluginContainer) -> None:
        terminal = _terminal(container)
        super().merge(container)
        self._theme_names.update(source.name for source in terminal.themes)
        self.themes.extend(terminal.themes)
        self._pet_names.update(source.name for source in terminal.pets)
        self.pets.extend(terminal.pets)
        self.presenters.extend(terminal.presenters)
        self._claimed.update(command.name for command in terminal.commands)
        self.commands.extend(terminal.commands)
        self.slots = terminal.slots
        self.turn_segments = {segment.name: segment for segment in terminal.turn_segments}

    def builtins_loaded(self) -> None:
        self.builtin_command_count = len(self.commands)

    def bundle(self) -> TerminalPlugins:
        plain = super().bundle()
        return TerminalPlugins(
            host=plain.host,
            mentions=plain.mentions,
            providers=plain.providers,
            contributed=plain.contributed,
            services=plain.services,
            failures=plain.failures,
            skipped=plain.skipped,
            commands=tuple(self.commands),
            builtin_commands=tuple(self.commands[: self.builtin_command_count]),
            themes=tuple(self.themes),
            pets=tuple(self.pets),
            presenters=tuple(self.presenters),
            rows=self.slots.rows(),
            turn_segments=tuple(self.turn_segments.values()),
        )
