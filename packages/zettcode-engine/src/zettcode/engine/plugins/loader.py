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
from typing import TYPE_CHECKING, Any

from zettcode.config import read_disabled_plugins
from zettcode.providers import BUILTIN_PROVIDERS

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

#: The one entry-point group: a plugin class per line, whichever part of the program it is (see
#: :data:`PROGRAM_DISTRIBUTIONS` for the ones the program itself publishes).
PLUGIN_ENTRY_POINT_GROUP = "zettcode.plugin"

#: The group this used to be, still read so a plugin published before the rename keeps loading. One release.
LEGACY_ENTRY_POINT_GROUP = "zettcode.plugins"

#: The roles a distribution of the program may publish its plugins in. Being unswitchable, ahead of everything, or
#: loaded only by a screen is a privilege of the program, not of whoever declares an entry point: the role is decided by
#: the **distribution** a point came from, which `importlib.metadata` knows before the plugin's module is imported (so a
#: process with no screen never imports the terminal's parts). A point that says nothing of its distribution (a test's
#: stand-in) is an ordinary plugin unless the table names it.
AGENT_ROLE = "agent"
TERMINAL_ROLE = "terminal"

#: The roles, by the distributions that publish them: the agent's parts (the tools, the session log, the permission, the
#: compaction, ...) are loaded by every front end and cannot be switched off — a configuration key such as
#: ``[skills] enabled`` is what turns a feature off; the terminal's (presenters, pets, palettes, commands) only a screen
#: loads, because they would import the whole terminal into the SDK and the server to offer them nothing.
PROGRAM_DISTRIBUTIONS: dict[str, frozenset[str]] = {
    AGENT_ROLE: frozenset(
        {
            "zettcode-sdk",
            "zettcode-skills",
            "zettcode-mcp",
            "zettcode-messaging",
            "zettcode-files",
            "zettcode-jit-harness",
            "zettcode-ask-user",
            "zettcode-instructions",
            "zettcode-todos",
            "zettcode-tool-output",
            "zettcode-truncation",
            "zettcode-guidance",
        }
    ),
    TERMINAL_ROLE: frozenset({"zettcode-app", "zettcode-commands", "zettcode-pets", "zettcode-presenters"}),
}

#: What the two old group names were called, for code that asks for a role by name.
AGENT_PART_GROUP = AGENT_ROLE
TERMINAL_PART_GROUP = TERMINAL_ROLE


def part_group(point: EntryPoint) -> str | None:
    """Return the role ``point`` is a part of, or ``None`` when it is an ordinary plugin of a reader's.

    The distribution says it, which is what a point published before the groups were merged cannot be trusted to: an
    old wheel still declares ``zettcode.agent`` or ``zettcode.terminal``, and the role is the same. A stand-in that
    names no distribution (a test's) is read from those old group names, which is all it has to say what it is.
    """
    dist = _distribution(point)
    if dist is not None:
        for role, allowed in PROGRAM_DISTRIBUTIONS.items():
            if dist in allowed:
                return role
        return None
    return _legacy_role(getattr(point, "group", "") or "")


def _legacy_role(group: str) -> str | None:
    """Return the role an old group name stands for, or ``None``."""
    return {"zettcode.agent": AGENT_ROLE, "zettcode.terminal": TERMINAL_ROLE}.get(group)


def installed_entry_points() -> tuple[EntryPoint, ...]:
    """Return every plugin entry point installed in this environment, the program's parts first.

    The import is deferred to the call so the plugin package itself stays cheap to import, and results are sorted by
    entry-point name so the load order is the same on every run. The group this used to be called is read beside the
    current one, so a plugin published before the rename keeps loading.
    """
    from importlib.metadata import entry_points

    current = entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
    # What the group was called before, the two the parts used, and the plugin line: a wheel published then is still
    # read, so nothing on PyPI stops loading when the program that reads it is upgraded.
    older = [
        *entry_points(group=LEGACY_ENTRY_POINT_GROUP),
        *entry_points(group="zettcode.agent"),
        *entry_points(group="zettcode.terminal"),
    ]
    # The program's parts first: a reader's plugin that took one of their names would lose it to the part, so the part
    # must be the one offered first (see `run`'s clash check).
    return tuple(sorted((*current, *older), key=lambda point: (part_group(point) is None, point.name)))


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
    builtins: Sequence[Plugin[Any]],
    shared: Mapping[str, object] | None = None,
    required: Sequence[str] = (),
    agent: bool = True,
) -> Plugins:
    """Load the builtin plugins and every enabled distribution into one bundle.

    Args:
        config: Settings the plugins are activated with, and the source of the
            ``[plugins]`` enable/disable switches.
        entry_points: Entry points to load; ``None`` reads the installed ones.
            Tests pass their own, so discovery can be exercised without
            installing a distribution.
        builtins: Plugins compiled into the repository, which the engine does not ship; ``()`` for none. The program's
            agent is not passed here: it is found through the ``zettcode.plugin`` group with the agent role, unless ``agent`` is
            false. A caller that cannot discover (a test) may pass :data:`zettcode.sdk.builtins.AGENT_PLUGINS`.
        shared: Objects the runtime hands over by name before any plugin activates (see
            :mod:`zettcode.engine.plugins.services`); a plugin reads them with ``container.service``, and they
            stay findable on the returned bundle. A plugin cannot provide a name that is taken here.

    Returns:
        The host extension, services, and load failures the plugins produced.
    """
    return run(Loader(config, shared), config, builtins=builtins, entry_points=entry_points, required=required)


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
    builtin: bool = False
    label: str | None = None
    error: BaseException | None = None
    #: Whether it came from the program's own entry-point group, which is ahead of every installed plugin.
    part: bool = False
    #: Whether it is one of the plugins that compose the agent (the ``agent`` role): a part that is also built in.
    agent: bool = False

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
    builtins: Sequence[Plugin[Any]],
    entry_points: Iterable[EntryPoint] | None,
    required: Sequence[str] = (),
    terminal: bool = False,
    agent: bool = True,
) -> Plugins:
    """Feed the builtins, the enabled distributions and the single-file plugins to ``loader``, and return what it bundled.

    The candidates are offered builtins first, then distributions, then files, and are activated in dependency order
    (:mod:`~zettcode.engine.plugins.graph`): stable, so without ``deps`` that is the order they were offered in.
    Builtins always load, while ``[plugins] enabled`` only gates the distributions and the files.

    Args:
        required: Names of plugins the program cannot run without. A ``disable`` line that names one — or one of the
            plugins it needs — is ignored and logged, and one that still did not load makes the call raise. A name is
            matched against the entry-point name (the origin) as well as ``Plugin.name``, so a required plugin keeps
            the two equal; one whose ``name`` differs cannot be pulled back in once disabled.
        terminal: Whether the loader has a screen, which is what the parts with the ``terminal`` role wait for.

    Raises:
        RequiredPluginError: A plugin in ``required`` is not loaded.
    """
    candidates: list[_Candidate] = []
    for plugin in builtins:
        candidates.append(_Candidate(plugin, plugin.name or type(plugin).__name__, builtin=True))
        if candidates[-1].origin not in loader.builtins:
            loader.builtins.append(candidates[-1].origin)
    # Offered by origin, so the ones a ``disable`` line holds back can still be pulled in when the program needs them.
    sources: dict[str, Callable[[], list[_Candidate]]] = {}
    # With `[plugins] enabled = false` nothing is loaded but the parts of the program (the `terminal` role,
    # which that switch is not about) and the plugins the program requires.
    points = tuple(entry_points) if entry_points is not None else installed_entry_points()
    # The parts of the program that need a screen are for a loader that has one.
    points = tuple(point for point in points if terminal or part_group(point) != TERMINAL_PART_GROUP)
    points = tuple(point for point in points if agent or part_group(point) != AGENT_PART_GROUP)
    parts = {point.name for point in points if part_group(point) is not None}
    agent_names = {point.name for point in points if part_group(point) == AGENT_PART_GROUP}
    # The configuration file's own list and the switch file's, merged for the one caller that loads. The switch
    # module cannot be imported here (it imports this one), so the union is written out; `off_names` is the same
    # rule for the front ends.
    disabled = set(config.disabled_plugins) | set(read_disabled_plugins(config.plugins_file))
    #: Who has each name, and who asked for a name that was taken, so the second can be told why it did not load.
    owners: dict[str, str] = {}
    owners_dist: dict[str, str | None] = {}
    taken: dict[str, list[str]] = {}
    for point in points:
        who = _described(point)
        if point.name in sources:
            # The program's parts come first, so a later plugin under the same name is the one that loses; it must
            # not take the place of a part, a required one least of all. The same distribution listed twice (a stale
            # `dist-info` beside an editable copy) is an environment quirk, not a clash.
            if _distribution(point) is None or _distribution(point) != owners_dist.get(point.name):
                taken.setdefault(point.name, []).append(who)
            continue
        owners[point.name] = who
        owners_dist[point.name] = _distribution(point)
        sources[point.name] = partial(_from_point, loader, point)
    if config.plugins_enabled:
        for path in installed_files(config.plugins_dir):
            if path.stem in sources:
                taken.setdefault(path.stem, []).append(f"the file {path.name}")
                continue
            owners[path.stem] = f"the file {path.name}"
            sources[path.stem] = partial(_from_file, loader, path)
    held = {origin for origin in sources if origin in disabled or (not config.plugins_enabled and origin not in parts)}
    for origin in sources:
        # A name the caller already passed as a built-in is that plugin; the discovered twin of it is the same part
        # offered twice, not a second plugin to refuse as a duplicate.
        if origin not in held and origin not in loader.builtins:
            candidates.extend(sources[origin]())
    # A name on that list can only reach a distribution or a file, unless the program needs it: the plugins it lists
    # as builtin loaded above, and the required ones, with what they need, are pulled in below. A line that names one
    # does nothing, and a reader who wrote it is told so instead of left to think the part is off.
    for origin in sorted(disabled & set(loader.builtins)):
        logger.warning(
            "plugins.required",
            extra={"plugin": origin, "reason": "part of the program; [plugins] disable does not reach it"},
        )
    # The plugins that compose the agent are protected like the required ones, but a failure of one is recorded and
    # does not stop the call: that is what they were as compiled-in plugins.
    protected = set(required) | agent_names
    while True:
        by_name = {candidate.name: candidate for candidate in candidates}
        wanted: set[str] = set()
        queue = [name for name in protected]
        while queue:
            name = queue.pop()
            if name in wanted:
                continue
            wanted.add(name)
            if name in by_name:
                queue.extend(by_name[name].deps)
        pulled = sorted(
            origin for origin in held if origin in wanted and not (origin in parts and origin in loader.builtins)
        )
        if not pulled:
            break
        for origin in pulled:
            held.discard(origin)
            if origin in disabled:
                logger.warning(
                    "plugins.required",
                    extra={
                        "plugin": origin,
                        "reason": "the program cannot run without it; [plugins] disable does not reach it",
                    },
                )
            candidates.extend(sources[origin]())
    # A name that was taken is reported only when the one that has it was actually offered: a part the reader switched
    # off refused nothing, and its row on the plugins page says "off", not "failed".
    for name, losers in taken.items():
        if name in held:
            continue
        for who in losers:
            # Not a failure of the plugin that has the name: it loaded, and its row says so. The loser has no row of
            # its own (it shares the name, or is a file with nothing but the name), so it is written to the log.
            logger.warning(
                "plugins.name_taken",
                extra={"plugin": name, "who": who, "reason": f"{owners[name]} already has the name {name!r}"},
            )
    # A plugin of the program is the program's own whether or not it loads, and whether or not it is ever activated: one
    # refused for a need that failed still goes on the list a switch is refused against.
    loader.builtins.extend(c.origin for c in candidates if c.builtin and c.origin not in loader.builtins)
    # Within the program's own groups the stated rank decides, then the name; the stable sort keeps everything else.
    at = [i for i, c in enumerate(candidates) if c.agent]
    for slot, candidate in zip(at, sorted((candidates[i] for i in at), key=_rank), strict=True):
        candidates[slot] = candidate
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
        elif loader.accept(
            candidate.plugin,
            origin=candidate.origin,
            builtin=candidate.builtin,
            part=candidate.part,
            label=candidate.label,
        ):
            loaded.add(index)
            names_loaded.add(candidate.name)
    # A required plugin is the program's own as much as a compiled-in one: no switch reaches it, and a list says so.
    loader.builtins.extend(name for name in required if name not in loader.builtins)
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


def _rank(candidate: _Candidate) -> tuple[int, str]:
    """Sort key of a part inside its group: its declared rank, then its name; a failure sorts first, by origin."""
    return (candidate.plugin.rank if candidate.plugin is not None else -1, candidate.origin)


def _from_point(loader: Loader, point: EntryPoint) -> list[_Candidate]:
    """Resolve one entry point into a candidate; a failure is a candidate that carries it."""
    group = part_group(point)
    part = group is not None
    agent = group == AGENT_PART_GROUP
    try:
        return [_Candidate(_instantiate(point), point.name, builtin=agent, part=part, agent=agent)]
    except KeyboardInterrupt:
        raise
    except BaseException as error:
        return [_Candidate(None, point.name, builtin=agent, error=error, part=part, agent=agent)]


def _from_file(loader: Loader, path: Path) -> list[_Candidate]:
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
        self.plain_commands: list[object] = []
        self.triggers: list[TriggerRegistration] = []
        #: One ``(origin, why)`` per plugin that could not be loaded; the messages a front end shows are built from
        #: these, so a list can put a header on its own row.
        self.failed: list[tuple[str, str]] = []
        #: The origins of the compiled-in plugins, in load order, so a bundle can say which rows are the program's.
        self.builtins: list[str] = []
        #: Whether the plugin being accepted is the program's own (built in, or one of its parts); read by ``merge``.
        self.program = False
        self._identities: set[str] = set()
        self._extension_names: set[str] = {HOST_NAME}
        self._mention_kinds: set[str] = set()
        self._trigger_names: set[str] = set()
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
        self.providers.extend(context.providers)
        self._mention_kinds.update(provider.kind for provider in context.mentions)
        self.mentions.extend(context.mentions)
        self.plain_commands.extend(context.commands.commands)
        self._trigger_names.update(reg.name for reg in context.triggers)
        self.triggers.extend(context.triggers)

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
            triggers=tuple(self.triggers),
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
        builtin: bool = False,
        part: bool = False,
        label: str | None = None,
    ) -> bool:
        """Activate one plugin and merge what it registered, or report why not.

        Returns:
            Whether the plugin was activated and merged.

        Args:
            plugin: The plugin to activate.
            origin: The name of the distribution (or of the compiled-in plugin) it came from.
            builtin: Whether it is compiled into the program, which is what makes it impossible to switch off.
            part: Whether it is one of the program's own parts (a role in ``PROGRAM_DISTRIBUTIONS``). Unlike a builtin it
                can be switched off, unless the loader's caller requires it; what it registers is the program's own,
                which is what :attr:`program` tells :meth:`merge` while it runs.
            label: The class name, when this plugin came from a file that can hold several; a failure says which.
        """
        self.program = builtin or part
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
