"""The plugin base class and the bundle of what the loaded plugins produced.

:class:`Plugin` is what an author subclasses: identity, one activation hook, and
the composed hook groups from :mod:`zettcode.plugins.mixins`.
:class:`Plugins` is the other direction — the host extension, commands, and
segments the loader hands the application, plus whatever failed to load.
"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar, TypeVar

from .mixins import PluginAgentMixin, PluginUiMixin
from .services import lookup, require
from .state import AgentBuild, Contribution, UiRow

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from collections.abc import Mapping

    from zett_agent.extensions.base import AgentExtension

    from ..app.agent.conversation.presenters import Presenter
    from ..app.commands import Command
    from ..app.pets import PetSource
    from ..engine.dialogue.mentions import MentionProvider
    from ..providers import Provider
    from ..tui import ThemeSource
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


_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class Plugins:
    """Everything the installed plugins contributed, and what failed to load.

    Attributes:
        host: The single extension that drives every loaded plugin; ``None``
            when none loaded. The agent is handed one extension, not one per
            plugin, so plugin-wide behaviour has one place to live.
        commands: Commands the plugins registered, in load and registration
            order, each typed ``"plugin"``.
        builtin_commands: The first of ``commands`` that came from the plugins compiled into the program, in the same
            order. The shell lists them ahead of its own and puts the rest after everything built in, so an installed
            plugin can add a command but never shadow one of the program's.
        mentions: ``@`` resource providers the plugins registered, in load and
            registration order; the shell merges them with the builtin skills.
        providers: Model providers the plugins described, in load and registration order; the
            shell offers them in ``/config`` after the built-in ones.
        themes: Palettes the plugins offered by name, in load and registration order; the built-in plugin's come
            first. ``/theme`` lists, previews and switches to them, after ``dark`` and ``light``.
        presenters: How plugins asked for entries to be drawn, in load and registration order; the built-in
            presenters come first, at the lowest priority, so a plugin's claim on the same rows wins.
        contributed: The ``zett-agent`` extensions the plugins registered through ``register_extension`` and
            ``register_extension_factory``, in load and registration order. :meth:`agent_extensions` turns them
            into the extensions the agent is given, beside the host, so each keeps the priority it declares.
        services: Objects the runtime handed over and the plugins provided, by name; read them with
            :meth:`service` and :meth:`find`.
        pets: Pets the plugins offered by name, in load and registration order; the built-in plugin's come first.
            ``/pet`` lists, previews and switches to them.
        rows: The header and status rows the plugins fill, each with its left
            and right segments in paint order. The builtin rows are merged in
            first, so an overridden segment keeps its place.
        failures: One message per plugin that could not be loaded or activated.
            A broken plugin is skipped rather than taking the whole application
            with it; the shell reports these where the user can see them.
    """

    host: PluginExtension | None = None
    commands: tuple[Command, ...] = ()
    builtin_commands: tuple[Command, ...] = ()
    mentions: tuple[MentionProvider, ...] = ()
    providers: tuple[Provider, ...] = ()
    themes: tuple[ThemeSource, ...] = ()
    pets: tuple[PetSource, ...] = ()
    presenters: tuple[Presenter, ...] = ()
    contributed: tuple[Contribution, ...] = ()
    services: Mapping[str, object] = field(default_factory=dict)
    rows: tuple[UiRow, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def installed_commands(self) -> tuple[Command, ...]:
        """Return the commands of the installed plugins: ``commands`` without the built-in ones."""
        return self.commands[len(self.builtin_commands) :]

    def find(self, name: str, kind: type[_T]) -> _T | None:
        """Return the service under ``name``, or ``None`` when no loaded plugin provides it.

        For what the application can do without: the plan panel has nothing to show when nobody keeps a
        plan. A service that exists but is the wrong type is still an error, because that is a plugin
        bug and not an absence.
        """
        return lookup(self.services, name, kind)

    def service(self, name: str, kind: type[_T]) -> _T:
        """Return the service under ``name``, checked to be a ``kind``.

        Raises:
            LookupError: When nothing provides it; a plugin that failed to load provides nothing, and
                the message says which service is missing.
            TypeError: When the name is taken by an object of another type.
        """
        return require(self.services, name, kind)

    def agent_extensions(self, build: AgentBuild | None = None) -> tuple[AgentExtension, ...]:
        """Return the extensions the plugins hand the agent, in registration order.

        Args:
            build: What exists while the agent is being built. Factories are called with it; without it
                (outside a build) only the extensions registered whole are returned.
        """
        built = (contribution.build(build) for contribution in self.contributed)
        return tuple(extension for extension in built if extension is not None)

    @property
    def plugins(self) -> tuple[Plugin, ...]:
        """Return the loaded plugins, in the order the host will call them."""
        return self.host.plugins if self.host is not None else ()

    @property
    def extensions(self) -> tuple[PluginExtension, ...]:
        """Return the one extension to register, or nothing when no plugin loaded."""
        return (self.host,) if self.host is not None else ()
