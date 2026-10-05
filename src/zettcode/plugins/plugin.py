"""The plugin base class and the bundle of what the loaded plugins produced.

:class:`Plugin` is what an author subclasses: identity, one activation hook, and
the composed hook groups from :mod:`zettcode.plugins.mixins`.
:class:`Plugins` is the other direction — the host extension, commands, and
segments the loader hands the application, plus whatever failed to load.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from .mixins import PluginAgentMixin, PluginUiMixin
from .state import UiRow

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from ..app.commands import Command
    from .container import PluginContainer
    from .extension import PluginExtension


class Plugin(PluginAgentMixin, PluginUiMixin, ABC):
    """Base class for one ZettCode plugin.

    The hooks are grouped into mixins, and :class:`Plugin` composes the two
    top-level groups: :class:`PluginAgentMixin` for the agent flow and
    :class:`PluginUiMixin` for the shell's header and status rows. A subclass
    overrides only the stages it takes part in, and each default does nothing;
    the finer agent groups (setup, run, turn, model, tool, maintenance, events,
    middleware) mirror ``zett-agent``'s extension mixins one for one, so an
    author who knows the extension docs already knows where a hook belongs.

    Attributes:
        name: Unique registration identity. Defaults to the class name; set it
            when the entry-point name is not the label you want in
            diagnostics. When it is empty the entry-point name is used, and a
            plugin that declares neither falls back to the class name.
        description: One-line summary of what the plugin adds, for diagnostics.
        priority: Hook order against every other extension: lower runs first,
            and equal priorities keep registration order.
    """

    #: Identity the loader may resolve and record; a plain attribute, so a
    #: nameless class can be given its entry-point name at load time.
    name: str = ""
    description: ClassVar[str] = ""
    priority: ClassVar[int] = 100

    def activate(self, container: PluginContainer) -> None:
        """Run once at startup, before any agent client is built.

        This is the place to register commands and segments, and to read the
        configuration. It is synchronous on purpose: the shell must know the
        full command list before it paints, and a plugin that needs asynchronous
        setup can do it in the lifecycle hooks, which all run on the agent loop.

        Args:
            container: The resolved settings and the registration surface.
        """


@dataclass(frozen=True, slots=True)
class Plugins:
    """Everything the installed plugins contributed, and what failed to load.

    Attributes:
        host: The single extension that drives every loaded plugin; ``None``
            when none loaded. The agent is handed one extension, not one per
            plugin, so plugin-wide behaviour has one place to live.
        commands: Commands the plugins registered, in load and registration
            order, each typed ``"plugin"``.
        rows: The header and status rows the plugins fill, each with its left
            and right segments in paint order. The builtin rows are merged in
            first, so an overridden segment keeps its place.
        failures: One message per plugin that could not be loaded or activated.
            A broken plugin is skipped rather than taking the whole application
            with it; the shell reports these where the user can see them.
    """

    host: PluginExtension | None = None
    commands: tuple[Command, ...] = ()
    rows: tuple[UiRow, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def plugins(self) -> tuple[Plugin, ...]:
        """Return the loaded plugins, in the order the host will call them."""
        return self.host.plugins if self.host is not None else ()

    @property
    def extensions(self) -> tuple[PluginExtension, ...]:
        """Return the one extension to register, or nothing when no plugin loaded."""
        return (self.host,) if self.host is not None else ()
