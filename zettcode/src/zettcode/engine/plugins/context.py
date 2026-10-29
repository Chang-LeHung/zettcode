"""What a plugin receives when it activates: ``ctx``, and the groups it registers into.

The context is the plugin's only channel to the application. It exposes the resolved configuration, and three groups:
``ctx.agent`` for what every front end has (extensions, providers, ``@`` providers, services), ``ctx.commands`` for
plain commands that say nothing about a UI, and ``ctx.tui`` for what only the terminal can hold — ``None`` everywhere
else. The context itself keeps the accumulated registrations; the groups are the stable names a plugin writes
against, so what is added later lands in a group rather than in another method on the context.

The terminal's own group is :class:`zettcode.app.plugins.groups.TuiGroups`; the engine cannot name it, since the
terminal is a layer above this one, which is why the attribute is untyped here and documented instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from zettcode.plugin_tui import TuiGroup
from zettcode.providers import Provider

from .commands import CommandGroups
from .groups import AgentGroups
from .services import lookup, require
from .state import Contribution, ExtensionFactory

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from collections.abc import Mapping

    from zett_agent.extensions.base import AgentExtension

    from zettcode.config import ZettCodeConfig
    from zettcode.mentions import MentionProvider

_T = TypeVar("_T")


class PluginContext:
    """What a plugin is handed when it activates, and the groups it registers into.

    The container is the plugin's only channel to the application: it exposes the resolved configuration, and
    collects what the plugin registers. They are accumulated here rather than returned, so a plugin can decide what
    to register from the configuration it is given.
    """

    def __init__(self, config: ZettCodeConfig, services: Mapping[str, object] | None = None) -> None:
        """Keep the resolved settings and open empty registries.

        Args:
            config: The resolved settings.
            services: What is already findable by name: the objects the runtime hands over, and what the
                plugins loaded before this one provided. Read with :meth:`service` and :meth:`find`.
        """
        self.config = config
        self.workspace = config.workspace
        #: What every front end has: extensions, providers, ``@`` providers and services.
        self.agent = AgentGroups(self)
        #: Plain commands: text and a toast, no widget and no shell.
        self.commands = CommandGroups()
        self._tui: TuiGroup | None = None
        self._available: Mapping[str, object] = services if services is not None else {}
        self._mentions: list[MentionProvider] = []
        self._providers: list[Provider] = []
        self._extensions: list[Contribution] = []
        self._services: dict[str, object] = {}

    @property
    def tui(self) -> TuiGroup | None:
        """Return the terminal's group, or ``None`` in a process without a screen.

        The loader attaches it once, before the plugin activates; a plugin reads it and never replaces it.
        :class:`zettcode.app.plugins.groups.TuiGroups` is the implementation.
        """
        return self._tui

    def attach_tui(self, group: TuiGroup) -> None:
        """Give this context its terminal group; the terminal's loader is the caller."""
        self._tui = group

    @property
    def extensions(self) -> tuple[Contribution, ...]:
        """Return the agent extensions registered so far, in registration order."""
        return tuple(self._extensions)

    @property
    def services(self) -> dict[str, object]:
        """Return a copy of the services provided so far, by name."""
        return dict(self._services)

    @property
    def mentions(self) -> tuple[MentionProvider, ...]:
        """Return the ``@`` resource providers registered so far."""
        return tuple(self._mentions)

    @property
    def providers(self) -> tuple[Provider, ...]:
        """Return the model providers registered so far, in registration order."""
        return tuple(self._providers)

    def register_provider(self, provider: Provider) -> Provider:
        """Describe a host models can be reached at, so ``/config`` offers it.

        A provider is an address and a protocol; the reader brings the token and the model id. It
        appears in the ``/config`` picker beside the built-in ones and ``/config add <name>``
        takes it. Nothing is called or connected to: this only describes a host.

        Args:
            provider: The host. Its ``name`` must be unique across the application, because it is
                what ``/config add`` is typed with.

        Returns:
            The registered provider, in case the plugin wants to keep it.

        Raises:
            ValueError: When the name is already registered by this plugin, or is one of the
                built-in providers'.
        """
        if not isinstance(provider, Provider):
            raise ValueError("A provider must be a zettcode.providers.Provider")
        if provider.name in {existing.name for existing in self._providers}:
            raise ValueError(f"Provider already registered: {provider.name}")
        self._providers.append(provider)
        return provider

    def register_extension(self, extension: AgentExtension) -> AgentExtension:
        """Hand the agent one ``zett-agent`` extension of the plugin's own.

        Use this when the plugin is, or wraps, a whole extension rather than a set of hooks: the
        agent receives it as a separate extension, ordered by the priority it declares and, among
        equals, by registration order, exactly as if the application had listed it itself. The hook
        methods on :class:`~zettcode.engine.plugins.Plugin` are the other route, for a plugin that only
        needs to watch a stage; they run inside the one host extension.

        Args:
            extension: The extension to add. Its ``name`` must be unique among the agent's
                extensions; a clash fails the plugin when it loads.

        Returns:
            The extension, in case the plugin wants to keep it.

        Raises:
            ValueError: When the name is blank or this plugin already registered it.
        """
        name = getattr(extension, "name", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("An extension must have a non-empty name")
        self._claim_extension(name)
        self._extensions.append(Contribution(name, extension=extension))
        return extension

    def register_extension_factory(self, name: str, factory: ExtensionFactory) -> None:
        """Hand the agent an extension that is built when the agent is, not when the plugin activates.

        Use it for an extension that needs something only a running agent has (the provider it starts
        on), or that is costly to import: a plugin activates while the shell is still being drawn, so
        importing a large module there delays the first frame. The factory is called with an
        :class:`~zettcode.engine.plugins.AgentBuild` after the imports the runtime warms up have finished,
        and may return ``None`` for a run that has nothing to add. Where the extension lands in the
        order is where it was registered, as for :meth:`register_extension`.

        Args:
            name: The name of the extension the factory builds, given up front so that a clash is
                caught when the plugin loads. A factory that builds it under another name fails the build.
            factory: Called once per agent build.

        Raises:
            ValueError: When the name is blank or this plugin already registered it.
        """
        if not name.strip():
            raise ValueError("An extension must have a non-empty name")
        self._claim_extension(name)
        self._extensions.append(Contribution(name, factory=factory))

    def _claim_extension(self, name: str) -> None:
        """Refuse an extension name this plugin has already registered."""
        if any(existing.name == name for existing in self._extensions):
            raise ValueError(f"Extension already registered: {name}")

    def service(self, name: str, kind: type[_T]) -> _T:
        """Return an object another part of the application or an earlier plugin made available.

        This is how a plugin gets hold of the state it builds on: the session's permission policy, the
        session store, or a service a plugin loaded before it provided. Order matters, because only
        what is already there can be found.

        Raises:
            LookupError: When nothing is available under the name.
            TypeError: When what is there is not a ``kind``.
        """
        return require({**self._available, **self._services}, name, kind)

    def find(self, name: str, kind: type[_T]) -> _T | None:
        """Return the object available under ``name``, or ``None`` when there is none (see :meth:`service`)."""
        return lookup({**self._available, **self._services}, name, kind)

    def provide(self, name: str, service: object) -> object:
        """Register an object under a name, so other parts of the application can look it up.

        Use it when the plugin creates something that the shell or the runtime also needs to reach,
        for example the todo extension, whose plan the shell draws. The application looks it up with
        ``Plugins.service(name, kind)`` or ``Plugins.find(name, kind)``, so it needs no field of its
        own for it. This is separate from :meth:`register_extension`: that one gives the agent an
        extension to run, this one only makes an object findable. A plugin can provide an object
        it does not register with the agent, such as the todo extension while the tool is switched off.

        Args:
            name: Identity of the service; unique across the loaded plugins.
            service: The object itself.

        Returns:
            The service, in case the plugin wants to keep it.

        Raises:
            ValueError: When the name is blank or this plugin already provided it.
        """
        name = name.strip()
        if not name:
            raise ValueError("Service name cannot be empty")
        if name in self._services:
            raise ValueError(f"Service already provided: {name}")
        self._services[name] = service
        return service

    def register_mention(self, provider: MentionProvider) -> MentionProvider:
        """Register one kind of ``@`` resource the composer can offer.

        A provider lists candidates for the completion menu and expands a
        token into the text the model sees; the builtin provider offers skills,
        and a plugin adds its own kind the same way.

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
