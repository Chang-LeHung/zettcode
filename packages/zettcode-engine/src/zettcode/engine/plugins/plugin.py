"""The plugin base class and the bundle of what the loaded plugins produced.

:class:`Plugin` is what an author subclasses: identity, one activation hook, and
the composed hook groups from :mod:`zettcode.engine.plugins.mixins`.
:class:`Plugins` is the other direction — the host extension, services, and
providers the loader hands the application, plus whatever failed to load.

A plugin is activated with one :class:`PluginContext`: the engine's own plugins take a
:class:`~zettcode.engine.plugins.container.PluginContext`, and the terminal's take its subclass, which also
registers commands, palettes, pets, presenters and rows.
"""

from __future__ import annotations

import logging
from abc import ABC
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from .context import PluginContext
from .mixins import PluginAgentMixin
from .services import lookup, require
from .state import AgentBuild, Contribution

logger = logging.getLogger("zettcode.plugins")

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from collections.abc import Mapping

    from zett_agent.extensions.base import AgentExtension

    from zettcode.mention import MentionProvider
    from zettcode.providers import Provider

    from .extension import PluginExtension
    from .triggers import TriggerRegistration

_C = TypeVar("_C", bound=PluginContext)
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class PluginSetting:
    """The configuration key that decides whether a compiled-in plugin does its work.

    A plugin installed as a distribution is switched by `[plugins] disable` in the configuration. One compiled into the program has no
    file of its own: what turns its work off is a setting the reader already has, such as ``[skills] enabled``. A
    plugin that declares one is listed by a panel with a switch, and the switch writes that key; a plugin that does
    not is not listed, because there is nothing a reader could do about it.

    Attributes:
        field: The attribute of :class:`~zettcode.config.ZettCodeConfig` that holds it now, for the state a list
            shows and for a running process to keep up with.
        table: The configuration table it is written to.
        key: The key inside that table.
    """

    field: str
    table: str
    key: str = "enabled"

    @property
    def path(self) -> str:
        """Return it the way the configuration file spells it, ``skills.enabled``."""
        return f"{self.table}.{self.key}"


class Plugin(PluginAgentMixin, Generic[_C], ABC):
    """Base class for one ZettCode plugin.

    It is generic over the container its hooks are handed — ``Plugin[PluginContext]`` for a plugin the runtime activates,
    which is every one this repository ships — so a subclass that names it gets its ``activate`` checked and an override
    that changes the signature is an error.

    The hooks are grouped into mixins, and :class:`Plugin` composes the agent flow group
    (:class:`PluginAgentMixin`). A subclass overrides only the stages it takes part in, and each default does
    nothing; the finer agent groups (setup, run, turn, model, tool, maintenance, events, middleware) mirror
    ``zett-agent``'s extension mixins one for one, so an author who knows the extension docs already knows where a
    hook belongs.

    Attributes:
        name: Unique registration identity. Defaults to the class name; set it
            when the entry-point name is not the label you want in
            diagnostics. When it is empty the entry-point name is used, and a
            plugin that declares neither falls back to the class name.
        description: One-line summary of what the plugin adds, for diagnostics.
        priority: Hook order against every other extension: lower runs first,
            and equal priorities keep registration order.
        setting: The configuration key that turns its work off, for a plugin compiled into the program; ``None`` when
            the plugin is installed as a distribution, which `[plugins] disable` reaches instead.
    """

    #: Identity the loader may resolve and record; a plain attribute, so a
    #: nameless class can be given its entry-point name at load time.
    name: str = ""
    #: How the distribution that carries it is called — the entry-point name for an installed plugin, its own
    #: name for a builtin. `/plugins` shows it when it differs from :attr:`name`, because `[plugins] disable` and the
    #: switch file are matched against it.
    origin: str = ""
    description: ClassVar[str] = ""
    #: The names of the plugins this one needs. The loader activates a plugin after every plugin it lists, and
    #: leaves it out, reported, when one of them is absent, turned off, failed, or the lists go round in a circle.
    deps: ClassVar[tuple[str, ...]] = ()
    #: Where a plugin stands among the others of its entry-point group when the loader has no ``deps`` to go by: parts
    #: are activated by ``(rank, name)`` within their group, so a group whose extensions share a priority (and so
    #: keep their registration order) is activated in a stated order and not in the order entry points happen to sort.
    #: The program's to set: ``zettcode.sdk.builtins`` writes it for its own plugins, and a plugin of anyone else has
    #: no use for it, since it is only read for the parts of the program.
    rank: ClassVar[int] = 0
    priority: ClassVar[int] = 100
    #: The configuration key that decides whether a compiled-in plugin does its work, or ``None`` when there is none:
    #: a plugin the reader cannot turn off is left out of the list rather than shown without a switch.
    setting: ClassVar[PluginSetting | None] = None

    def activate(self, container: _C) -> None:
        """Run once at startup, before any agent client is built.

        This is the place to register what the plugin contributes, and to read the
        configuration. It is synchronous on purpose: the shell must know the
        full command list before it paints, and a plugin that needs asynchronous
        setup can do it in the lifecycle hooks, which all run on the agent loop.

        Args:
            container: The resolved settings and the registration surface.
        """

    async def aclose(self) -> None:
        """Release what the plugin holds beyond one turn, when the runtime closes.

        Called once per plugin, in reverse load order, after the runtime has stopped the plugins' triggers and before
        it releases the store. The default does nothing; a plugin that opened a connection, started a watcher or
        keeps a long-lived client overrides it. What it raises is logged and does not stop the other plugins closing.
        """


@dataclass(frozen=True, slots=True)
class Plugins:
    """Everything the installed plugins contributed to the agent, and what failed to load.

    Attributes:
        host: The single extension that drives every loaded plugin; ``None``
            when none loaded. The agent is handed one extension, not one per
            plugin, so plugin-wide behaviour has one place to live.
        mentions: ``@`` resource providers the plugins registered, in load and
            registration order; the shell merges them with the builtin skills.
        providers: Model providers the plugins described, in load and registration order; the
            shell offers them in ``/config`` after the built-in ones.
        contributed: The ``zett-agent`` extensions the plugins registered through ``register_extension`` and
            ``register_extension_factory``, in load and registration order. :meth:`agent_extensions` turns them
            into the extensions the agent is given, beside the host, so each keeps the priority it declares.
        services: Objects the runtime handed over and the plugins provided, by name; read them with
            :meth:`service` and :meth:`find`.
        plain_commands: Commands a plugin registered on ``ctx.commands``, in load and registration order, each
            typed ``"plugin"``. The terminal turns them into shell commands; another front end reads them here.
        failures: One message per plugin that could not be loaded or activated, ``origin: why``, read from
            :attr:`failed`. A plugin that cannot be loaded is reported rather than taking the whole application
            with it; the shell reports these where the user can see them.
        failed: The failures themselves, one ``(origin, why)`` pair each, for a list that groups them by the plugin
            they belong to. This is the one record; :attr:`failures` is written from it.
        builtins: The origins of the plugins compiled into the program, in load order. They always load, so a switch
            cannot leave one out, and a list can say which rows are the program's own.
        triggers: The triggers the plugins registered, in load and registration order; the runtime starts them with
            itself (see :class:`~zettcode.engine.plugins.triggers.TriggerHost`).
        taken: The plugins that lost a name to one loaded before them, each as ``(name, why)``; they are not failures
            of the plugin that kept it, and a list shows them without a switch.
    """

    host: PluginExtension | None = None
    mentions: tuple[MentionProvider, ...] = ()
    providers: tuple[Provider, ...] = ()
    contributed: tuple[Contribution, ...] = ()
    services: Mapping[str, object] = field(default_factory=dict)
    plain_commands: tuple[object, ...] = ()
    failed: tuple[tuple[str, str], ...] = ()
    builtins: tuple[str, ...] = ()
    triggers: tuple[TriggerRegistration, ...] = ()
    taken: tuple[tuple[str, str], ...] = ()

    @property
    def failures(self) -> tuple[str, ...]:
        """Return each failure as the one line a transcript shows, ``origin: why``."""
        return tuple(f"{origin}: {why}" for origin, why in self.failed)

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
    def plugins(self) -> tuple[Plugin[Any], ...]:
        """Return the loaded plugins, in the order the host will call them."""
        return self.host.plugins if self.host is not None else ()

    async def aclose(self) -> None:
        """Release what each loaded plugin holds beyond a turn, newest first.

        Newest means the reverse of the order they were activated in, not the reverse of the hook order: priorities
        decide who sees a hook first, not who borrowed from whom. One that borrows from an earlier plugin closes
        before it. A plugin that raises is logged and the others still close, which is what keeps an installation
        with one broken plugin from leaving its other connections open at exit.
        """
        order = self.host.activation if self.host is not None else ()
        for plugin in reversed(order):
            try:
                await plugin.aclose()
            except Exception as error:  # noqa: BLE001 - one plugin must not stop the others closing
                logger.warning("plugins.close_failed", extra={"plugin": plugin.name, "error": repr(error)})

    @property
    def extensions(self) -> tuple[PluginExtension, ...]:
        """Return the one extension to register, or nothing when no plugin loaded."""
        return (self.host,) if self.host is not None else ()
