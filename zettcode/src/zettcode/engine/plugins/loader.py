"""Discover installed plugins through Python entry points and prepare them.

A distribution advertises a plugin by publishing a class (or a zero-argument
factory returning one) under the ``zettcode.plugins`` group::

    [project.entry-points."zettcode.plugins"]
    my-plugin = "my_package:MyPlugin"

Nothing else registers a plugin: installing the distribution is the opt-in, and
``[plugins] disable`` in the config is the way back out. A plugin that cannot be
imported, instantiated, or activated is reported in
:attr:`~zettcode.engine.plugins.plugin.Plugins.failures`; one broken plugin must not take
the whole application with it.

The accepted plugins are bundled into one host extension (see
:mod:`zettcode.engine.plugins.extension`). Identities must be unique — a plugin's declared ``name``, else its
entry-point name — and so must the names of what they register, because a later plugin that collides is skipped
and reported rather than silently shadowed.

:class:`Loader` is the engine's: it merges what the agent uses. The terminal's loader subclasses it to merge what
only a terminal has (see :class:`zettcode.app.plugins.loader.TerminalLoader`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from zettcode.config import read_disabled_plugins
from zettcode.providers import BUILTIN_PROVIDERS

from .builtin_agent import AGENT_PLUGINS
from .context import PluginContext
from .extension import HOST_NAME, PluginExtension
from .plugin import Plugin, Plugins
from .state import Contribution

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterable, Mapping, Sequence
    from importlib.metadata import EntryPoint

    from zettcode.config import ZettCodeConfig
    from zettcode.mentions import MentionProvider
    from zettcode.providers import Provider

#: Entry-point group a distribution publishes its plugin under.
PLUGIN_ENTRY_POINT_GROUP = "zettcode.plugins"


def installed_entry_points() -> tuple[EntryPoint, ...]:
    """Return every plugin entry point installed in this environment.

    The import is deferred to the call so the plugin package itself stays cheap
    to import, and results are sorted by entry-point name so the load order is the same on every run.
    """
    from importlib.metadata import entry_points

    return tuple(sorted(entry_points(group=PLUGIN_ENTRY_POINT_GROUP), key=lambda point: point.name))


def load_plugins(
    config: ZettCodeConfig,
    *,
    entry_points: Iterable[EntryPoint] | None = None,
    builtins: Sequence[Plugin[Any]] = AGENT_PLUGINS,
    shared: Mapping[str, object] | None = None,
) -> Plugins:
    """Load the builtin plugins and every enabled distribution into one bundle.

    Args:
        config: Settings the plugins are activated with, and the source of the
            ``[plugins]`` enable/disable switches.
        entry_points: Entry points to load; ``None`` reads the installed ones.
            Tests pass their own, so discovery can be exercised without
            installing a distribution.
        builtins: Plugins compiled into the repository; tests pass ``()`` to
            exercise a load without them.
        shared: Objects the runtime hands over by name before any plugin activates (see
            :mod:`zettcode.engine.plugins.services`); a plugin reads them with ``container.service``, and they
            stay findable on the returned bundle. A plugin cannot provide a name that is taken here.

    Returns:
        The host extension, services, and load failures the plugins produced.
    """
    return run(Loader(config, shared), config, builtins=builtins, entry_points=entry_points)


def run(
    loader: Loader,
    config: ZettCodeConfig,
    *,
    builtins: Sequence[Plugin[Any]],
    entry_points: Iterable[EntryPoint] | None,
) -> Plugins:
    """Feed the builtins and then the enabled distributions to ``loader``, and return what it bundled.

    The builtins go first, so a plugin that registers under one of their names replaces it in place.
    Builtins always load, while ``[plugins] enabled`` only gates the distributions.
    """
    for plugin in builtins:
        loader.accept(plugin, origin=plugin.name or type(plugin).__name__)
    loader.builtins_loaded()
    if config.plugins_enabled:
        points = tuple(entry_points) if entry_points is not None else installed_entry_points()
        disabled = set(config.disabled_plugins) | set(read_disabled_plugins(config.plugins_file))
        for point in points:
            if point.name in disabled:
                continue
            try:
                plugin = _instantiate(point)
            except Exception as error:
                loader.fail(point.name, error)
                continue
            loader.accept(plugin, origin=point.name)
    return loader.bundle()


class Loader:
    """Accumulate accepted plugins into the one bundle the application gets."""

    def __init__(self, config: ZettCodeConfig, shared: Mapping[str, object] | None = None) -> None:
        self.config = config
        self.plugins: list[Plugin[Any]] = []
        self.mentions: list[MentionProvider] = []
        self.providers: list[Provider] = []
        self.contributed: list[Contribution] = []
        self.services: dict[str, object] = dict(shared or {})
        self.plain_commands: list[object] = []
        self.failures: list[str] = []
        self._identities: set[str] = set()
        self._extension_names: set[str] = {HOST_NAME}
        self._mention_kinds: set[str] = set()
        self._provider_names: set[str] = {provider.name for provider in BUILTIN_PROVIDERS}

    # -- what a subclass changes --

    def new_context(self) -> PluginContext:
        """Return the context one plugin is activated with."""
        return PluginContext(self.config, self.services)

    def activated(self, plugin: Plugin[Any], context: PluginContext) -> None:
        """Run after a plugin's ``activate`` succeeded and before its contribution is checked; may raise."""

    def clash(self, context: PluginContext) -> str | None:
        """Return why this plugin's contribution cannot be merged, or ``None`` when it can."""
        # A mention token has no prefix naming its provider, so two providers
        # with the same kind would make resolution ambiguous. Reject the plugin.
        mention_clash = next(
            (provider.kind for provider in context.mentions if provider.kind in self._mention_kinds),
            None,
        )
        if mention_clash is not None:
            return f"mention kind {mention_clash} is already registered"
        # A name is what `/config add` is typed with, so two hosts sharing one cannot both be
        # reached; the one that was there first, a built-in or an earlier plugin, keeps it.
        provider_clash = next(
            (provider.name for provider in context.providers if provider.name in self._provider_names),
            None,
        )
        if provider_clash is not None:
            return f"provider {provider_clash} is already registered"
        # The agent refuses two extensions with one name, and that would fail the first turn rather than
        # the load, so the clash is caught here; the name of the host itself counts.
        extension_clash = next(
            (extension.name for extension in context.extensions if extension.name in self._extension_names),
            None,
        )
        if extension_clash is not None:
            return f"extension {extension_clash} is already registered"
        # A service is looked up by its name, so a second provider would be unreachable behind the first.
        service_clash = next((name for name in context.services if name in self.services), None)
        if service_clash is not None:
            return f"service {service_clash} is already provided"
        return None

    def merge(self, context: PluginContext) -> None:
        """Take what an accepted plugin registered."""
        self._extension_names.update(extension.name for extension in context.extensions)
        self.contributed.extend(context.extensions)
        self.services.update(context.services)
        self._provider_names.update(provider.name for provider in context.providers)
        self.providers.extend(context.providers)
        self._mention_kinds.update(provider.kind for provider in context.mentions)
        self.mentions.extend(context.mentions)
        self.plain_commands.extend(context.commands.commands)

    def builtins_loaded(self) -> None:
        """Called once the builtin plugins have all been offered, before any distribution."""

    def bundle(self) -> Plugins:
        """Return everything the accepted plugins contributed."""
        host = PluginExtension(self.plugins) if self.plugins else None
        return Plugins(
            host=host,
            mentions=tuple(self.mentions),
            providers=tuple(self.providers),
            contributed=tuple(self.contributed),
            services=dict(self.services),
            plain_commands=tuple(self.plain_commands),
            failures=tuple(self.failures),
        )

    # -- the same for every front end --

    def fail(self, origin: str, error: BaseException) -> None:
        """Record one plugin that could not be prepared."""
        self.failures.append(f"{origin}: {_reason(error)}")

    def accept(self, plugin: Plugin[Any], *, origin: str) -> None:
        """Activate one plugin and merge what it registered, or report why not."""
        name = plugin.name or origin or type(plugin).__name__
        if name in self._identities:
            self.failures.append(f"{origin}: duplicate plugin name {name!r}")
            return
        if not plugin.name:
            plugin.name = name
        if not plugin.origin:
            plugin.origin = origin or name
        container = self.new_context()
        try:
            plugin.activate(container)
            self.activated(plugin, container)
        except Exception as error:
            self.fail(origin, error)
            return
        clash = self.clash(container)
        if clash is not None:
            self.failures.append(f"{origin}: {clash}")
            return
        self._identities.add(name)
        self.merge(container)
        self.plugins.append(plugin)


def _instantiate(point: EntryPoint) -> Plugin[Any]:
    """Resolve one entry point to a plugin: a class, a factory, or an instance."""
    target = point.load()
    if isinstance(target, Plugin):
        return target
    if isinstance(target, type) and issubclass(target, Plugin):
        return target()
    if callable(target):
        produced = target()
        if isinstance(produced, Plugin):
            return produced
        raise TypeError(f"factory returned {type(produced).__name__}, not a Plugin")
    raise TypeError(f"{type(target).__name__} is not a Plugin, a Plugin subclass, or a factory")


def _reason(error: BaseException) -> str:
    """Return the text a load failure should show, never an empty message."""
    text = str(error).strip()
    return text or type(error).__name__
