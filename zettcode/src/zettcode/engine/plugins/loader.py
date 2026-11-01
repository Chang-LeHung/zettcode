"""Discover installed plugins through Python entry points and prepare them.

A distribution advertises a plugin by publishing a class (or a zero-argument
factory returning one) under the ``zettcode.plugins`` group::

    [project.entry-points."zettcode.plugins"]
    my-plugin = "my_package:MyPlugin"

A single ``.py`` file in :attr:`ZettCodeConfig.plugins_dir` (``~/.zettcode/plugins`` by default) is the other way in:
every class the file defines that derives from :class:`Plugin` (``TuiPlugin`` included) is loaded, under the file's
stem as its origin. Nothing else registers a plugin: installing the distribution or dropping the file in is the
opt-in, and ``[plugins] disable`` in the config is the way back out. A plugin that cannot be
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

import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from zettcode.config import read_disabled_plugins
from zettcode.providers import BUILTIN_PROVIDERS

from .builtin_agent import AGENT_PLUGINS
from .context import PluginContext
from .extension import HOST_NAME, PluginExtension
from .plugin import Plugin, Plugins, PluginSetting
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


def installed_files(directory: Path) -> tuple[Path, ...]:
    """Return the single-file plugins in ``directory``, sorted by name; a folder that is not there has none."""
    try:
        found = sorted(directory.glob("*.py"))
    except OSError:
        return ()
    return tuple(path for path in found if path.is_file() and not path.name.startswith(("_", ".")))


def _file_plugins(path: Path) -> tuple[list[Plugin[Any]], list[tuple[str, BaseException]]]:
    """Import a single-file plugin and instantiate every Plugin subclass it defines itself.

    The module name carries a digest of the resolved path, so two folders that hold the same stem in one process are
    two modules rather than one stale entry. A constructor that raises fails only its own class; the file's other
    classes still load.

    Returns:
        The plugins, and the ``(origin:class, error)`` of every class that could not be constructed.

    Raises:
        BaseException: The import itself failed; the caller reports it as the file's failure.
    """
    digest = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:8]
    name = f"_zettcode_plugin_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - a .py file always has a loader
        raise ImportError(f"{path.name} cannot be loaded as a module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    found = [
        value
        for value in vars(module).values()
        if isinstance(value, type)
        and value is not Plugin
        and issubclass(value, Plugin)
        and value.__module__ == module.__name__
    ]
    if not found:
        raise ValueError(f"{path.name} defines no class deriving from Plugin or TuiPlugin")
    plugins: list[Plugin[Any]] = []
    failures: list[tuple[str, BaseException]] = []
    for value in sorted(found, key=lambda cls: cls.__name__):
        try:
            plugins.append(value())
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            failures.append((value.__name__, error))
    return plugins, failures


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
    """Feed the builtins, the enabled distributions and the single-file plugins to ``loader``, and return what it bundled.

    The builtins go first, so a plugin that registers under one of their names replaces it in place.
    Builtins always load, while ``[plugins] enabled`` only gates the distributions and the files.
    """
    for plugin in builtins:
        loader.accept(plugin, origin=plugin.name or type(plugin).__name__, builtin=True)
    loader.builtins_loaded()
    if config.plugins_enabled:
        points = tuple(entry_points) if entry_points is not None else installed_entry_points()
        # The configuration file's own list and the switch file's, merged for the one caller that loads. The switch
        # module cannot be imported here (it imports this one), so the union is written out; `off_names` is the same
        # rule for the front ends.
        disabled = set(config.disabled_plugins) | set(read_disabled_plugins(config.plugins_file))
        for point in points:
            if point.name in disabled:
                continue
            try:
                plugin = _instantiate(point)
            except KeyboardInterrupt:
                raise
            except BaseException as error:
                loader.fail(point.name, error)
                continue
            loader.accept(plugin, origin=point.name)
        for path in installed_files(config.plugins_dir):
            origin = path.stem
            if origin in disabled:
                continue
            try:
                plugins, failures = _file_plugins(path)
            except KeyboardInterrupt:
                raise
            except BaseException as error:
                loader.fail(origin, error)
                continue
            for class_name, failure in failures:
                loader.fail(origin, failure, label=class_name)
            for plugin in plugins:
                loader.accept(plugin, origin=origin, label=type(plugin).__name__)
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
        #: One ``(origin, why)`` per plugin that could not be loaded; the messages a front end shows are built from
        #: these, so a list can put a header on its own row.
        self.failed: list[tuple[str, str]] = []
        #: The origins of the compiled-in plugins, in load order, so a bundle can say which rows are the program's.
        self.builtins: list[str] = []
        self._identities: set[str] = set()
        self._extension_names: set[str] = {HOST_NAME}
        self._mention_kinds: set[str] = set()
        self._provider_names: set[str] = {provider.name for provider in BUILTIN_PROVIDERS}

    # -- what a subclass changes --

    def new_context(self, name: str = "") -> PluginContext:
        """Return the context one plugin is activated with, named so its ``[plugins.<name>]`` settings are read."""
        return PluginContext(self.config, self.services, name=name)

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
            failed=tuple(self.failed),
            builtins=tuple(self.builtins),
        )

    # -- the same for every front end --

    def fail(self, origin: str, error: BaseException | str, *, label: str | None = None) -> None:
        """Record one plugin that could not be prepared, naming the class when there is one."""
        reason = _reason(error)
        self.failed.append((origin, f"{label}: {reason}" if label else reason))

    def accept(self, plugin: Plugin[Any], *, origin: str, builtin: bool = False, label: str | None = None) -> None:
        """Activate one plugin and merge what it registered, or report why not.

        Args:
            plugin: The plugin to activate.
            origin: The name of the distribution (or of the compiled-in plugin) it came from.
            builtin: Whether it is compiled into the program, which is what makes it impossible to switch off.
            label: The class name, when this plugin came from a file that can hold several; a failure says which.
        """
        name = plugin.name or origin or type(plugin).__name__
        if builtin and origin not in self.builtins:
            # Recorded before it is activated: a compiled-in plugin is the program's own whether or not it loaded,
            # and the list of them is what a switch is refused against.
            self.builtins.append(origin)
        if plugin.setting is not None and not _is_bool_setting(self.config, plugin.setting):
            # A switch that names a setting the configuration does not have, or one that is not a boolean, would be a
            # row nobody could move or a truthy default in a panel. It is a plugin bug, and the load says so.
            self.fail(
                origin,
                f"setting {plugin.setting.path} names no boolean setting of the configuration",
                label=label,
            )
            return
        if name in self._identities:
            self.fail(origin, f"duplicate plugin name {name!r}", label=label)
            return
        if not plugin.name:
            plugin.name = name
        if not plugin.origin:
            plugin.origin = origin or name
        container = self.new_context(name)
        try:
            plugin.activate(container)
            self.activated(plugin, container)
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            self.fail(origin, error, label=label)
            return
        clash = self.clash(container)
        if clash is not None:
            self.fail(origin, clash, label=label)
            return
        self._identities.add(name)
        self.merge(container)
        self.plugins.append(plugin)


def _is_bool_setting(config: ZettCodeConfig, setting: PluginSetting) -> bool:
    """Return whether the configuration has the field a plugin's setting names, and holds a boolean there."""
    return isinstance(getattr(config, setting.field, None), bool)


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


def _reason(error: BaseException | str) -> str:
    """Return the text a load failure should show, never an empty message."""
    text = str(error).strip()
    return text or (type(error).__name__ if isinstance(error, BaseException) else "failed")
