"""Discover installed plugins through Python entry points and prepare them.

A distribution advertises a plugin by publishing a class (or a zero-argument
factory returning one) under the ``zettcode.plugin`` group::

    [project.entry-points."zettcode.plugin"]
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
import logging
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

from zettcode.config import read_disabled_plugins

from . import graph
from .context import PluginContext
from .extension import HOST_NAME, PluginExtension
from .plugin import Plugin, Plugins, PluginSetting
from .state import Contribution

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import Iterable, Mapping, Sequence
    from importlib.metadata import EntryPoint

    from zettcode.config import ZettCodeConfig
    from zettcode.mention import MentionProvider
    from zettcode.providers import Provider

    from .triggers import TriggerRegistration

logger = logging.getLogger("zettcode.plugins")

#: What a caller may hand over whole: the plugin itself, or its class, which the loader builds.
OfferedPlugin: TypeAlias = Plugin[Any] | type[Plugin[Any]]

#: The entry-point group every process reads: a plugin class per line. There is no kind of plugin that is more
#: privileged than another; what a program cannot run without is named by the caller (``required``).
PLUGIN_ENTRY_POINT_GROUP = "zettcode.plugin"

#: The group only a process with a screen reads. A plugin that draws (the commands, the presenters, the pets, the
#: palettes) publishes here instead, so the SDK and the server never look at it, let alone import it. Nothing else is
#: different about it: it is the same class, the same switch and the same row on the plugins page.
TERMINAL_ENTRY_POINT_GROUP = "zettcode.tui"


def installed_entry_points(*, terminal: bool = False) -> tuple[EntryPoint, ...]:
    """Return the plugin entry points installed in this environment, sorted by name and then by distribution.

    The import is deferred to the call so the plugin package itself stays cheap to import. The terminal's group is
    read only for ``terminal=True``: a process that has no screen does not even list what it would never load.
    """
    from importlib.metadata import entry_points

    found = list(entry_points(group=PLUGIN_ENTRY_POINT_GROUP))
    if terminal:
        found.extend(entry_points(group=TERMINAL_ENTRY_POINT_GROUP))
    return tuple(sorted(found, key=lambda point: (point.name, _distribution(point) or "")))


def screen_entry_points() -> tuple[EntryPoint, ...]:
    """Return only the plugins published for a screen: what a picture of the shell is drawn with, and nothing else."""
    return tuple(point for point in installed_entry_points(terminal=True) if point.group == TERMINAL_ENTRY_POINT_GROUP)


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


def file_off_by_default(path: Path) -> bool | None:
    """Return whether a single-file plugin loads nothing unless ``[plugins] enable`` names it.

    The answer is on the class, so the file is imported here the way a start imports it: its module is executed and
    its plugin classes are built, but nothing is activated and no command of the plugin runs. ``None`` when the file
    cannot be read as a plugin at all — a failure the next start reports, and one a list must not turn into a
    traceback. A file that defines several classes is off by default when every one of them asks to be.
    """
    try:
        plugins, _failures = _file_plugins(path)
    except KeyboardInterrupt:
        raise
    except BaseException:  # noqa: BLE001 - an unreadable plugin file is the loader's to report, not a caller's
        return None
    return bool(plugins) and not any(plugin.default_enabled() for plugin in plugins)


def load_plugins(
    config: ZettCodeConfig,
    *,
    entry_points: Iterable[EntryPoint] | None = None,
    builtins: Sequence[OfferedPlugin] = (),
    shared: Mapping[str, object] | None = None,
    required: Sequence[str] = (),
) -> Plugins:
    """Load every enabled plugin into one bundle.

    Args:
        config: Settings the plugins are activated with, and the source of the
            ``[plugins]`` enable/disable switches.
        entry_points: Entry points to load; ``None`` reads the installed ones.
            Tests pass their own, so discovery can be exercised without
            installing a distribution.
        builtins: Plugins handed over whole (a class or an instance), loaded whatever the switches say; ``()`` for none.
        shared: Objects the runtime hands over by name before any plugin activates (see
            :mod:`zettcode.engine.plugins.services`); a plugin reads them with ``container.service``, and they
            stay findable on the returned bundle. A plugin cannot provide a name that is taken here.
        required: Names of the plugins the program cannot run without; see :func:`run`.

    Returns:
        The host extension, services, and load failures the plugins produced.
    """
    return run(Loader(config, shared), config, builtins=builtins, entry_points=entry_points, required=required)


class PluginActivationError(RuntimeError):
    """An inherited plugin could not activate; startup must not silently lose its backend."""


class RequiredPluginError(RuntimeError):
    """A plugin the program cannot run without did not load.

    Attributes:
        missing: ``{name: why}`` for each required plugin that is not among the loaded ones, in the order they were
            asked for. The message lists them, so a front end can print it as it is.
    """

    def __init__(self, missing: dict[str, str]) -> None:
        self.missing = dict(missing)
        lines = "; ".join(f"{name}: {why}" for name, why in self.missing.items())
        super().__init__(f"cannot start without the required plugins ({lines})")


@dataclass(frozen=True, slots=True)
class _Candidate:
    """One plugin on its way to ``accept``, or the failure of one that could not even be built.

    A failure travels with the others so it is reported where it was found, in discovery order, and not before or
    after the plugins around it.
    """

    plugin: Plugin[Any] | None
    origin: str
    label: str | None = None
    error: BaseException | None = None
    #: Whether the caller handed it in whole instead of leaving it to be discovered; such a plugin is not held back by
    #: a switch, since whoever passed it asked for it.
    offered: bool = False

    @property
    def name(self) -> str:
        if self.plugin is None:
            return f"\0failed:{self.origin}:{self.label}"
        return self.plugin.name or self.origin or type(self.plugin).__name__

    @property
    def deps(self) -> tuple[str, ...]:
        return tuple(self.plugin.deps) if self.plugin is not None else ()


def run(
    loader: Loader,
    config: ZettCodeConfig,
    *,
    builtins: Sequence[OfferedPlugin],
    entry_points: Iterable[EntryPoint] | None,
    required: Sequence[str] = (),
    terminal: bool = False,
) -> Plugins:
    """Feed the offered plugins, the enabled distributions and the single-file plugins to ``loader``, and bundle them.

    Every plugin is the same kind of thing. The candidates are the ones the caller offered whole (``builtins``), then
    the installed entry points, then the files; they are activated in dependency order
    (:mod:`~zettcode.engine.plugins.graph`) after a stable sort by ``rank``. ``[plugins] disable`` and
    ``[plugins] enabled`` hold back the installed ones and the files. What the caller offered whole always loads.

    Args:
        builtins: Plugins the caller hands over as they are, a class or an instance; ``()`` for none. They are not
            discovered, so a test can pass the exact set it wants.
        required: Names of plugins the program cannot run without. A ``disable`` line that names one — or one of the
            plugins it needs — is ignored and logged, and one that still did not load makes the call raise. A name is
            matched against the entry-point name (the origin) as well as ``Plugin.name``.
        terminal: Whether the loader has a screen, which is what makes it read the terminal's entry-point group
            (:data:`TERMINAL_ENTRY_POINT_GROUP`) beside the common one.

    Raises:
        RequiredPluginError: A plugin in ``required`` is not loaded.
    """
    candidates: list[_Candidate] = []
    offered_names: set[str] = set()
    for offered in builtins:
        plugin = _offered_plugin(offered)
        origin = plugin.name or type(plugin).__name__
        candidates.append(_Candidate(plugin, origin, offered=True))
        offered_names.add(origin)
    # Offered by origin, so the ones a ``disable`` line holds back can still be pulled in when the program needs them.
    sources: dict[str, Callable[[], list[_Candidate]]] = {}
    points = tuple(entry_points) if entry_points is not None else installed_entry_points(terminal=terminal)
    # The configuration file's own list and the switch file's, merged for the one caller that loads. The switch
    # module cannot be imported here (it imports this one), so the union is written out; `off_names` is the same
    # rule for the front ends.
    disabled = set(config.disabled_plugins) | set(read_disabled_plugins(config.plugins_file))
    enabled = set(config.enabled_plugins)
    #: Who has each name, and who asked for a name that was taken, so the second can be told why it did not load.
    owners: dict[str, str] = {}
    owners_dist: dict[str, str | None] = {}
    taken: dict[str, list[str]] = {}
    for point in points:
        who = _described(point)
        if point.name in sources:
            # The first one found keeps the name. The same distribution listed twice (a stale `dist-info` beside an
            # editable copy) is an environment quirk, not a clash.
            if _distribution(point) is None or _distribution(point) != owners_dist.get(point.name):
                taken.setdefault(point.name, []).append(who)
            continue
        owners[point.name] = who
        owners_dist[point.name] = _distribution(point)
        sources[point.name] = partial(_from_point, point)
    if config.plugins_enabled:
        for path in installed_files(config.plugins_dir):
            if path.stem in sources:
                taken.setdefault(path.stem, []).append(f"the file {path.name}")
                continue
            owners[path.stem] = f"the file {path.name}"
            sources[path.stem] = partial(_from_file, path)
    held = {origin for origin in sources if origin in disabled or not config.plugins_enabled}
    for origin in sorted(disabled & offered_names):
        # Offered whole, so the line cannot reach it; the pull loop below tells the reader about the discovered ones.
        logger.warning(
            "plugins.required",
            extra={"plugin": origin, "reason": "handed over by the program; [plugins] disable does not reach it"},
        )
    for origin in sources:
        # A name the caller already offered is that plugin; the discovered twin of it is the same plugin offered
        # twice, not a second one to refuse as a duplicate. It is noted at debug level, for whoever is diagnosing a
        # package that publishes a name the program handed over.
        if origin in offered_names:
            logger.debug(
                "plugins.name_offered", extra={"plugin": origin, "who": owners[origin], "reason": "handed over whole"}
            )
        if origin not in held and origin not in offered_names:
            candidates.extend(sources[origin]())
    # What the program requires is loaded whatever the switches say, with what it needs; a reader who wrote a line
    # that cannot take effect is told so instead of left to think the plugin is off.
    while True:
        by_name = {candidate.name: candidate for candidate in candidates}
        wanted: set[str] = set()
        queue = list(required)
        while queue:
            name = queue.pop()
            if name in wanted:
                continue
            wanted.add(name)
            if name in by_name:
                queue.extend(by_name[name].deps)
        pulled = sorted(origin for origin in held if origin in wanted and origin not in offered_names)
        if not pulled:
            break
        for origin in pulled:
            held.discard(origin)
            added = sources[origin]()
            if origin in disabled:
                logger.warning(
                    "plugins.required",
                    extra={
                        "plugin": origin,
                        "reason": "the program cannot run without it; [plugins] disable does not reach it",
                    },
                )
            candidates.extend(added)
    # A name that was taken is reported only when the one that has it was actually offered: one the reader switched
    # off refused nothing, and its row on the plugins page says "off", not "failed".
    for name, losers in taken.items():
        if name in held:
            continue
        for who in losers:
            # Not a failure of the plugin that has the name: it loaded, and its row says so. The loser has no row of
            # its own (it shares the name, or is a file with nothing but the name), so it is a note on the page.
            reason = f"{owners[name]} already has the name {name!r}"
            logger.warning(
                "plugins.name_taken",
                extra={"plugin": name, "who": who, "reason": reason},
            )
            loader.taken.append((name, f"{who}: {reason}"))
    # A plugin that says it is off by default is loaded only when the configuration enables it, the caller requires
    # it, or another plugin that loads needs it.
    kept = [
        candidate
        for candidate in candidates
        if candidate.plugin is None
        or candidate.offered
        or candidate.plugin.default_enabled()
        or candidate.name in loader.child_state
        or candidate.name in enabled
        or candidate.origin in enabled
        or candidate.name in required
        or candidate.origin in required
    ]
    kept_ids = {id(candidate) for candidate in kept}
    needed = {dep for candidate in kept for dep in candidate.deps}
    while True:
        extra = [
            candidate
            for candidate in candidates
            if id(candidate) not in kept_ids and (candidate.name in needed or candidate.origin in needed)
        ]
        if not extra:
            break
        kept.extend(extra)
        kept_ids.update(id(candidate) for candidate in extra)
        needed.update(dep for candidate in extra for dep in candidate.deps)
    # The plugins dropped for exactly one reason — they say they are off by default — are remembered, so a list can
    # draw the row as off and a switch knows which line of the configuration file turns one on. An origin that kept
    # another candidate is not one of them: a single file may define a class that loads and one that does not, and the
    # file it names did its work, so neither list may call the file off by default.
    kept_origins = {candidate.origin for candidate in candidates if id(candidate) in kept_ids}
    loader.off_by_default.extend(
        candidate.origin
        for candidate in candidates
        if id(candidate) not in kept_ids
        and candidate.origin not in kept_origins
        and candidate.plugin is not None
        and not candidate.plugin.default_enabled()
    )
    # Among equal ranks, what the caller named (offered whole, or required) goes first, so a plugin nobody asked for
    # cannot take a name one of those needs; `rank` stays the primary key because extensions that share a priority
    # run in the order they registered.
    named = set(required)
    candidates = sorted(
        kept,
        key=lambda c: (_rank(c), 0 if (c.offered or c.name in named or c.origin in named) else 1),
    )
    ordered, refused = graph.order([graph.Node(c.name, c.deps) for c in candidates])
    loaded: set[int] = set()
    for index in sorted(refused):
        candidate = candidates[index]
        loader.fail(candidate.origin, refused[index], label=candidate.label)
    names_loaded: set[str] = set()
    for index in ordered:
        candidate = candidates[index]
        lost = next((dep for dep in candidate.deps if dep not in names_loaded), None)
        if candidate.plugin is None:
            assert candidate.error is not None
            loader.fail(candidate.origin, candidate.error, label=candidate.label)
        elif lost is not None:
            # It was ready, but a plugin it needs failed to activate: the failure is that plugin's, and this one is
            # reported as the casualty it is rather than activated without what it asked for.
            loader.fail(candidate.origin, f"needs plugin {lost!r}, which cannot be loaded", label=candidate.label)
        elif loader.accept(candidate.plugin, origin=candidate.origin, label=candidate.label):
            loaded.add(index)
            names_loaded.add(candidate.name)
    loader.required.extend(name for name in required if name not in loader.required)
    if required:
        have = {candidates[index].name for index in loaded}
        absent: dict[str, str] = {}
        for name in required:
            if name in have:
                continue
            why = next((reason for origin, reason in loader.failed if origin == name), None)
            absent[name] = why or "not installed"
        if absent:
            raise RequiredPluginError(absent)
    return loader.bundle()


def _distribution(point: EntryPoint) -> str | None:
    """Return the name of the distribution an entry point came from, or ``None`` when it does not say."""
    dist = getattr(point, "dist", None)
    name = getattr(dist, "name", None)
    return re.sub(r"[-_.]+", "-", str(name)).lower() if name else None


def _described(point: EntryPoint) -> str:
    """Say who an entry point is, for a message that has to name what to uninstall."""
    dist = _distribution(point)
    value = getattr(point, "value", None)
    return f"{point.name!r} ({dist or 'unknown distribution'}" + (f", {value})" if value else ")")


def _rank(candidate: _Candidate) -> int:
    """Sort key: the plugin's declared rank. The call site breaks ties by what the caller named, then keeps discovery order."""
    return candidate.plugin.rank if candidate.plugin is not None else 0


def _from_point(point: EntryPoint) -> list[_Candidate]:
    """Resolve one entry point into a candidate; a failure is a candidate that carries it."""
    try:
        return [_Candidate(_instantiate(point), point.name)]
    except KeyboardInterrupt:
        raise
    except BaseException as error:
        return [_Candidate(None, point.name, error=error)]


def _from_file(path: Path) -> list[_Candidate]:
    """Import one single-file plugin into candidates; a failure is recorded and gives none."""
    origin = path.stem
    try:
        plugins, failures = _file_plugins(path)
    except KeyboardInterrupt:
        raise
    except BaseException as error:
        return [_Candidate(None, origin, error=error)]
    broken = [_Candidate(None, origin, label=class_name, error=failure) for class_name, failure in failures]
    return [*broken, *(_Candidate(plugin, origin, label=type(plugin).__name__) for plugin in plugins)]


class Loader:
    """Accumulate accepted plugins into the one bundle the application gets."""

    def __init__(self, config: ZettCodeConfig, shared: Mapping[str, object] | None = None) -> None:
        self.config = config
        self.plugins: list[Plugin[Any]] = []
        self.mentions: list[MentionProvider] = []
        self.providers: list[Provider] = []
        self.contributed: list[Contribution] = []
        self.services: dict[str, object] = dict(shared or {})
        from .children import CHILD_STATE, validate_child_state

        self.child_state = validate_child_state(self.services.get(CHILD_STATE, {}))
        # Present in every process, not only a daemon: a plugin may read it from `activate` in any front end.
        self.services[CHILD_STATE] = self.child_state
        self.plain_commands: list[object] = []
        self.triggers: list[TriggerRegistration] = []
        #: One ``(origin, why)`` per plugin that could not be loaded; the messages a front end shows are built from
        #: these, so a list can put a header on its own row.
        self.failed: list[tuple[str, str]] = []
        #: One ``(name, why)`` per plugin that lost a name to one loaded before it; the winner did nothing wrong,
        #: so these are notes rather than failures, and a list shows them without a switch.
        self.taken: list[tuple[str, str]] = []
        #: The origins of the plugins left out only because they say they are off by default, in discovery order; a
        #: list shows one as off and a switch writes it into ``[plugins] enable``.
        self.off_by_default: list[str] = []
        #: The names the program cannot run without (what the caller passed as ``required``), so a list can say which
        #: rows have no switch.
        self.required: list[str] = []
        self._identities: set[str] = set()
        self._extension_names: set[str] = {HOST_NAME}
        self._mention_kinds: set[str] = set()
        self._trigger_names: set[str] = set()
        self._provider_names: set[str] = set()
        #: The names a model is shown by, which `/model` and a session's recorded choice both depend on: the
        #: file's entries and every provided model accepted so far.
        self._model_names: set[str] = {model.shown_name for model in config.models}

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
        # A name is what a provider is registered under, so two hosts sharing one cannot both be reached; the one
        # that was there first, an earlier plugin, keeps it.
        provider_clash = next(
            (provider.name for provider in context.providers if provider.name in self._provider_names),
            None,
        )
        if provider_clash is not None:
            return f"provider {provider_clash} is already registered"
        # A model is chosen by the name a list shows, and a session records it, so two entries under one name would
        # make `/model` a guess.
        model_clash = next(
            (
                model.shown_name
                for provider in context.providers
                for model in provider.models
                if model.shown_name in self._model_names
            ),
            None,
        )
        if model_clash is not None:
            return f"a model shown as {model_clash!r} is already registered"
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
        # A trigger is one instance per process or per machine *by name*: two plugins sharing one would be one
        # watcher with two owners.
        trigger_clash = next((reg.name for reg in context.triggers if reg.name in self._trigger_names), None)
        if trigger_clash is not None:
            return f"trigger {trigger_clash} is already registered"
        return None

    def merge(self, context: PluginContext) -> None:
        """Take what an accepted plugin registered."""
        self._extension_names.update(extension.name for extension in context.extensions)
        self.contributed.extend(context.extensions)
        self.services.update(context.services)
        self._provider_names.update(provider.name for provider in context.providers)
        self._model_names.update(model.shown_name for provider in context.providers for model in provider.models)
        self.providers.extend(context.providers)
        self._mention_kinds.update(provider.kind for provider in context.mentions)
        self.mentions.extend(context.mentions)
        self.plain_commands.extend(context.commands.commands)
        self._trigger_names.update(reg.name for reg in context.triggers)
        self.triggers.extend(context.triggers)

    def bundle(self) -> Plugins:
        """Return everything the accepted plugins contributed."""
        missing = self.child_state.keys() - {plugin.name for plugin in self.plugins}
        if missing:
            raise PluginActivationError(
                "Cannot inherit child state without loaded plugins: " + ", ".join(sorted(missing))
            )
        host = PluginExtension(self.plugins) if self.plugins else None
        return Plugins(
            host=host,
            mentions=tuple(self.mentions),
            providers=tuple(self.providers),
            contributed=tuple(self.contributed),
            services=dict(self.services),
            plain_commands=tuple(self.plain_commands),
            failed=tuple(self.failed),
            required=tuple(self.required),
            triggers=tuple(self.triggers),
            taken=tuple(self.taken),
            default_off=tuple(dict.fromkeys(self.off_by_default)),
        )

    # -- the same for every front end --

    def fail(self, origin: str, error: BaseException | str, *, label: str | None = None) -> None:
        """Record one plugin that could not be prepared, naming the class when there is one."""
        reason = _reason(error)
        self.failed.append((origin, f"{label}: {reason}" if label else reason))

    def accept(
        self,
        plugin: Plugin[Any],
        *,
        origin: str,
        label: str | None = None,
    ) -> bool:
        """Activate one plugin and merge what it registered, or report why not.

        Returns:
            Whether the plugin was activated and merged.

        Args:
            plugin: The plugin to activate.
            origin: The entry-point name (or file stem) it came from.
            label: The class name, when this plugin came from a file that can hold several; a failure says which.
        """
        name = plugin.name or origin or type(plugin).__name__
        if plugin.setting is not None and not _is_bool_setting(self.config, plugin.setting):
            # A switch that names a setting the configuration does not have, or one that is not a boolean, would be a
            # row nobody could move or a truthy default in a panel. It is a plugin bug, and the load says so.
            self.fail(
                origin,
                f"setting {plugin.setting.path} names no boolean setting of the configuration",
                label=label,
            )
            return False
        if name in self._identities:
            self.fail(origin, f"duplicate plugin name {name!r}", label=label)
            return False
        if not plugin.name:
            plugin.name = name
        if not plugin.origin:
            plugin.origin = origin or name
        container = self.new_context(name)
        try:
            if name in self.child_state:
                from .children import validate_child_state

                plugin.restore_child(validate_child_state({name: self.child_state[name]})[name])
            plugin.activate(container)
            self.activated(plugin, container)
        except KeyboardInterrupt:
            raise
        except BaseException as error:
            self.fail(origin, error, label=label)
            return False
        clash = self.clash(container)
        if clash is not None:
            self.fail(origin, clash, label=label)
            return False
        self._identities.add(name)
        self.merge(container)
        self.plugins.append(plugin)
        return True


def _is_bool_setting(config: ZettCodeConfig, setting: PluginSetting) -> bool:
    """Return whether the configuration has the field a plugin's setting names, and holds a boolean there."""
    return isinstance(getattr(config, setting.field, None), bool)


def _offered_plugin(target: Plugin[Any] | type[Plugin[Any]]) -> Plugin[Any]:
    """Return an offered plugin as an instance: a caller may hand over a class or an object."""
    if isinstance(target, Plugin):
        return target
    if isinstance(target, type) and issubclass(target, Plugin):
        return target()
    raise TypeError(f"an offered plugin is a Plugin or a Plugin subclass, not {type(target).__name__}")


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
