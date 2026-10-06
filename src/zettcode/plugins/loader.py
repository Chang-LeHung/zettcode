"""Discover installed plugins through Python entry points and prepare them.

A distribution advertises a plugin by publishing a class (or a zero-argument
factory returning one) under the ``zettcode.plugins`` group::

    [project.entry-points."zettcode.plugins"]
    my-plugin = "my_package:MyPlugin"

Nothing else registers a plugin: installing the distribution is the opt-in, and
``[plugins] disable`` in the config is the way back out. A plugin that cannot be
imported, instantiated, or activated is skipped and reported in
:attr:`~zettcode.plugins.plugin.Plugins.failures`; one broken plugin must not take
the whole application with it.

The accepted plugins are bundled into one host extension (see
:mod:`zettcode.plugins.extension`) plus their commands. Identities must be
unique — a plugin's declared ``name``, else its entry-point name — and so must
command names, because the shell runs the first match: a later plugin that
collides is skipped and reported rather than silently shadowed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .builtins import BUILTIN_PLUGINS
from .container import PluginContainer, UiSlots
from .extension import PluginExtension
from .plugin import Plugin, Plugins

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterable, Sequence
    from importlib.metadata import EntryPoint

    from ..app.agent.mentions import MentionProvider
    from ..app.commands import Command
    from ..config import ZettCodeConfig

#: Entry-point group a distribution publishes its plugin under.
PLUGIN_ENTRY_POINT_GROUP = "zettcode.plugins"


def installed_entry_points() -> tuple[EntryPoint, ...]:
    """Return every plugin entry point installed in this environment.

    The import is deferred to the call so the plugin package itself stays cheap
    to import, and results are sorted by entry-point name so the load order —
    and therefore the command order — is the same on every run.
    """
    from importlib.metadata import entry_points

    return tuple(sorted(entry_points(group=PLUGIN_ENTRY_POINT_GROUP), key=lambda point: point.name))


def load_plugins(
    config: ZettCodeConfig,
    *,
    entry_points: Iterable[EntryPoint] | None = None,
    builtins: Sequence[Plugin] = BUILTIN_PLUGINS,
) -> Plugins:
    """Load the builtin plugins and every enabled distribution into one bundle.

    The builtins go first, so a plugin that registers a segment under one of
    their names replaces it in place; anything it registers under a new name
    appends after the builtin segment for that side. Builtins always load —
    they are the shell's rows — while ``[plugins] enabled`` only gates the
    distributions.

    Args:
        config: Settings the plugins are activated with, and the source of the
            ``[plugins]`` enable/disable switches.
        entry_points: Entry points to load; ``None`` reads the installed ones.
            Tests pass their own, so discovery can be exercised without
            installing a distribution.
        builtins: Plugins compiled into the repository; tests pass ``()`` to
            exercise a load without the shell's own rows.

    Returns:
        The host extension, commands, rows, and load failures the plugins
        produced.
    """
    loader = _Loader(config)
    for plugin in builtins:
        loader.accept(plugin, origin=plugin.name or type(plugin).__name__)
    if config.plugins_enabled:
        points = tuple(entry_points) if entry_points is not None else installed_entry_points()
        disabled = set(config.disabled_plugins)
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


class _Loader:
    """Accumulate accepted plugins into the one bundle the application gets."""

    def __init__(self, config: ZettCodeConfig) -> None:
        self.config = config
        self.slots = UiSlots()
        self.plugins: list[Plugin] = []
        self.commands: list[Command] = []
        self.mentions: list[MentionProvider] = []
        self.failures: list[str] = []
        self._identities: set[str] = set()
        self._claimed: set[str] = set()
        self._mention_kinds: set[str] = set()

    def fail(self, origin: str, error: BaseException) -> None:
        """Record one plugin that could not be prepared."""
        self.failures.append(f"{origin}: {_reason(error)}")

    def accept(self, plugin: Plugin, *, origin: str) -> None:
        """Activate one plugin and merge what it registered, or report why not."""
        name = plugin.name or origin or type(plugin).__name__
        if name in self._identities:
            self.failures.append(f"{origin}: duplicate plugin name {name!r}")
            return
        if not plugin.name:
            plugin.name = name
        container = PluginContainer(self.config)
        # Seed the registry with what is already loaded, so a segment that
        # reuses a name — or asks to override a side — acts on the real rows
        # instead of on an empty copy. A failure below leaves it untouched.
        container.slots.take_from(self.slots)
        try:
            plugin.activate(container)
            for region, side, slot_name, builder in plugin.ui_slots():
                container.slots.add(region, side, slot_name, builder)
        except Exception as error:
            self.fail(origin, error)
            return
        # Command lookup takes the first match, so a second plugin claiming the
        # same name would be silently unreachable. Reject the plugin instead.
        clash = next((command.name for command in container.commands if command.name in self._claimed), None)
        if clash is not None:
            self.failures.append(f"{origin}: command {clash} is already registered by another plugin")
            return
        # A mention token has no prefix naming its provider, so two providers
        # with the same kind would make resolution ambiguous. Reject the plugin.
        mention_clash = next(
            (provider.kind for provider in container.mentions if provider.kind in self._mention_kinds),
            None,
        )
        if mention_clash is not None:
            self.failures.append(f"{origin}: mention kind {mention_clash} is already registered")
            return
        self._identities.add(name)
        self._claimed.update(command.name for command in container.commands)
        self._mention_kinds.update(provider.kind for provider in container.mentions)
        self.commands.extend(container.commands)
        self.mentions.extend(container.mentions)
        self.slots = container.slots
        self.plugins.append(plugin)

    def bundle(self) -> Plugins:
        """Return everything the accepted plugins contributed."""
        host = PluginExtension(self.plugins) if self.plugins else None
        return Plugins(
            host=host,
            commands=tuple(self.commands),
            mentions=tuple(self.mentions),
            rows=self.slots.rows(),
            failures=tuple(self.failures),
        )


def _instantiate(point: EntryPoint) -> Plugin:
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
