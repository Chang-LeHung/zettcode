"""Load the plugins for the terminal: the engine's loader, plus the commands, palettes, pets, presenters and rows.

Everything the engine's :class:`~zettcode.engine.plugins.loader.Loader` checks and merges, this one does too, and in
addition it keeps command names, theme names and pet names unique and merges the header and status rows, so a plugin
that collides on any of them is reported.
"""

from __future__ import annotations

import inspect
from collections import Counter
from typing import TYPE_CHECKING, Any

from zettcode.app.commands import Command, CommandResult
from zettcode.engine.plugins.builtin_agent import AGENT_PLUGINS
from zettcode.engine.plugins.commands import PlainCommandContext, TextCommandResult, TurnCommandResult
from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.loader import Loader, run
from zettcode.tui import RESERVED_THEMES

from .builtins import BUILTIN_PLUGINS
from .groups import TuiGroups, UiSlots
from .host import HOST_LINK, HostLink
from .plugin import TuiPlugin, TuiPlugins
from .state import TurnSegment

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterable, Mapping, Sequence
    from importlib.metadata import EntryPoint

    from zettcode.app.agent.conversation.presenters import Presenter
    from zettcode.app.commands import Command
    from zettcode.app.pets import PetSource
    from zettcode.config import ZettCodeConfig
    from zettcode.engine.plugins.plugin import Plugin
    from zettcode.tui import ThemeSource


def load_terminal_plugins(
    config: ZettCodeConfig,
    *,
    entry_points: Iterable[EntryPoint] | None = None,
    builtins: Sequence[Plugin[Any]] = (*BUILTIN_PLUGINS, *AGENT_PLUGINS),
    shared: Mapping[str, object] | None = None,
) -> TuiPlugins:
    """Load the builtin plugins and every enabled distribution into one bundle, for the terminal.

    The arguments are those of :func:`zettcode.engine.plugins.loader.load_plugins`; the builtins default to the
    terminal's own followed by the agent's.
    """
    bundle = run(TerminalLoader(config, shared), config, builtins=builtins, entry_points=entry_points)
    assert isinstance(bundle, TuiPlugins)
    return bundle


def terminal_plugins(config: ZettCodeConfig, shared: Mapping[str, object]) -> TuiPlugins:
    """Load the plugins the terminal's way, in the shape :meth:`ZettCodeEngine.preview` takes as its loader."""
    return load_terminal_plugins(config, shared=shared)


def _tui(context: PluginContext) -> TuiGroups:
    """Return the terminal group of ``context``, which this loader always attaches."""
    if context.tui is None or not isinstance(context.tui, TuiGroups):
        raise TypeError(f"{type(context).__name__} has no terminal group")
    return context.tui


def terminal_context(config: ZettCodeConfig, services: Mapping[str, object] | None = None) -> PluginContext:
    """Build one context with the terminal group attached, the way this loader does for a plugin."""
    context = PluginContext(config, services)
    context.attach_tui(TuiGroups(context))
    return context


def plain_commands(context: PluginContext) -> list[Command]:
    """Turn the plugin's plain commands into the shell's, keeping the handler's contract.

    The handler returns a :class:`~zettcode.engine.plugins.commands.TextCommandResult` or a
    :class:`~zettcode.engine.plugins.commands.TurnCommandResult` — words, or a request to start — so there is nothing a
    shell could show that a process without one could not; the adapter maps each onto what the shell does with it.
    """
    adapted: list[Command] = []
    for plain in context.commands.commands:
        adapted.append(
            Command(
                name=plain.name,
                description=plain.summary,
                type="plugin",
                handler=_plain_handler(plain.handler),
                when_busy=plain.when_busy,  # type: ignore[arg-type]  # the shell validates the word
                subcommands=plain.subcommands,  # type: ignore[arg-type]
            )
        )
    return adapted


def _plain_handler(handler):
    """Wrap one plain handler as the shell's, one result type at a time."""

    async def run(context):
        host = context.host
        level = host.client.permission if host is not None else "ask"
        result = handler(PlainCommandContext(argument=context.argument, level=level))
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, TurnCommandResult):
            # A preset for a turn: the shell starts it, and the conversation keeps the short form the command was
            # typed as.
            await context.require_host().prompt(result.prompt, shown=result.shown or None)
            return CommandResult(notification=result.notification)
        if isinstance(result, TextCommandResult):
            return CommandResult(message=result.message, notification=result.notification)
        raise TypeError(
            f"a plain command returns a TextCommandResult or a TurnCommandResult, not {type(result).__name__}"
        )

    return run


class TerminalLoader(Loader):
    """The engine's loader with the terminal's registries."""

    def __init__(self, config: ZettCodeConfig, shared: Mapping[str, object] | None = None) -> None:
        super().__init__(config, shared)
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

    def new_context(self) -> PluginContext:
        # Seed the registry with what is already loaded, so a segment that
        # reuses a name — or asks to override a side — acts on the real rows
        # instead of on an empty copy. A failure leaves it untouched.
        context = terminal_context(self.config, self.services)
        tui = _tui(context)
        tui.slots.take_from(self.slots)
        for segment in self.turn_segments.values():
            tui.register_turn_segment(segment.name, segment.summary, segment.builder)
        return context

    def activated(self, plugin: Plugin[Any], context: PluginContext) -> None:
        if isinstance(plugin, TuiPlugin):
            terminal = _tui(context)
            for region, side, slot_name, builder in plugin.ui_slots():
                terminal.slots.add(region, side, slot_name, builder)

    def clash(self, context: PluginContext) -> str | None:
        terminal = _tui(context)
        # Command lookup takes the first match, so a second plugin claiming the
        # same name would be silently unreachable. Reject the plugin instead.
        claimed = [command.name for command in terminal.registered_commands]
        claimed += [plain.name for plain in context.commands.commands]
        # Both registries of this plugin, and everything loaded before it, are one namespace: the shell keeps the
        # first match, so a second spelling of a name would be unreachable rather than refused.
        command_clash = next(
            (name for name, count in Counter(claimed).items() if count > 1 or name in self._claimed), None
        )
        if command_clash is not None:
            return f"command {command_clash} is already registered by another plugin"
        found = super().clash(context)
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

    def merge(self, context: PluginContext) -> None:
        terminal = _tui(context)
        super().merge(context)
        # A plain command is one the shell can run too: text and a toast need no page, so the plugin's
        # ``ctx.commands`` become ordinary commands here, beside the ones registered on ``ctx.tui``.
        plain = plain_commands(context)
        self._claimed.update(command.name for command in plain)
        self.commands.extend(plain)
        self._theme_names.update(source.name for source in terminal.themes)
        self.themes.extend(terminal.themes)
        self._pet_names.update(source.name for source in terminal.pets)
        self.pets.extend(terminal.pets)
        self.presenters.extend(terminal.presenters)
        self._claimed.update(command.name for command in terminal.registered_commands)
        self.commands.extend(terminal.registered_commands)
        self.slots = terminal.slots
        self.turn_segments = {segment.name: segment for segment in terminal.turn_segments}

    def builtins_loaded(self) -> None:
        self.builtin_command_count = len(self.commands)

    def bundle(self) -> TuiPlugins:
        plain = super().bundle()
        return TuiPlugins(
            host=plain.host,
            mentions=plain.mentions,
            providers=plain.providers,
            contributed=plain.contributed,
            services=plain.services,
            plain_commands=plain.plain_commands,
            failures=plain.failures,
            commands=tuple(self.commands),
            builtin_commands=tuple(self.commands[: self.builtin_command_count]),
            themes=tuple(self.themes),
            pets=tuple(self.pets),
            presenters=tuple(self.presenters),
            rows=self.slots.rows(),
            turn_segments=tuple(self.turn_segments.values()),
        )
