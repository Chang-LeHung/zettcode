"""The terminal's plugin base class and the bundle of what the loaded plugins produced for the terminal.

:class:`TerminalPlugin` is the engine's :class:`~zettcode.engine.plugins.plugin.Plugin` with the shell's row hooks, and
it is activated with a :class:`~zettcode.app.plugins.container.TerminalContainer`. :class:`TerminalPlugins` is the
engine's bundle plus what only a terminal reads: commands, palettes, pets, presenters and rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from zettcode.engine.plugins.plugin import Plugin, Plugins
from zettcode.engine.plugins.surfaces import Surface

from .container import TerminalContainer
from .mixins import PluginUiMixin
from .state import TurnSegment, UiRow

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from zettcode.app.agent.conversation.presenters import Presenter
    from zettcode.app.commands import Command
    from zettcode.app.pets import PetSource
    from zettcode.tui import ThemeSource


class TerminalPlugin(Plugin[TerminalContainer], PluginUiMixin):
    """Base class for a plugin that contributes to the terminal as well as, or instead of, the agent.

    Its :attr:`~zettcode.engine.plugins.plugin.Plugin.surfaces` default to ``{TUI}``: what a terminal plugin registers
    — a command, a palette, a pet, a presenter, a row — is the shell's, and a server running the same distribution
    skips it instead of activating a contribution it cannot hold. A plugin that also contributes an agent extension,
    a provider or an ``@`` resource says ``{AGENT, TUI}`` and is loaded by both.
    """

    surfaces: ClassVar[frozenset[Surface]] = frozenset({Surface.TUI})


@dataclass(frozen=True, slots=True)
class TerminalPlugins(Plugins):
    """Everything the installed plugins contributed, for the terminal: the agent's side and the shell's.

    Attributes:
        commands: Commands the plugins registered, in load and registration
            order, each typed ``"plugin"``.
        builtin_commands: The first of ``commands`` that came from the plugins compiled into the program, in the same
            order. The shell lists them ahead of its own and puts the rest after everything built in, so an installed
            plugin can add a command but never shadow one of the program's.
        themes: Palettes the plugins offered by name, in load and registration order; the built-in plugin's come
            first. ``/theme`` lists, previews and switches to them, after ``dark`` and ``light``.
        presenters: How plugins asked for entries to be drawn, in load and registration order; the built-in
            presenters come first, at the lowest priority, so a plugin's claim on the same rows wins.
        pets: Pets the plugins offered by name, in load and registration order; the built-in plugin's come first.
            ``/pet`` lists, previews and switches to them.
        rows: The header and status rows the plugins fill, each with its left
            and right segments in paint order. The builtin rows are merged in
            first, so an overridden segment keeps its place.
        turn_segments: The items of the line a request ends on, in the order they stand; the built-in plugin's come
            first, so a name a plugin reuses replaces that item in place.
    """

    commands: tuple[Command, ...] = ()
    builtin_commands: tuple[Command, ...] = ()
    themes: tuple[ThemeSource, ...] = ()
    pets: tuple[PetSource, ...] = ()
    presenters: tuple[Presenter, ...] = ()
    rows: tuple[UiRow, ...] = ()
    turn_segments: tuple[TurnSegment, ...] = ()

    @property
    def installed_commands(self) -> tuple[Command, ...]:
        """Return the commands of the installed plugins: ``commands`` without the built-in ones."""
        return self.commands[len(self.builtin_commands) :]
