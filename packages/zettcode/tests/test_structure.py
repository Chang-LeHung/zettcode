"""Static checks on the source tree: resolvable imports, and layers that hold.

Both checks read the source instead of importing it, so they also cover imports
that live inside functions — the ones a test run never executes.
"""

from __future__ import annotations

import ast
import importlib
import importlib.metadata
import importlib.util
import pathlib
import re
import subprocess
import sys
from typing import NamedTuple

import pytest
from packaging.requirements import Requirement

from zettcode._compat import tomllib

#: The repository root, two levels above the tests (``tests`` here).
ROOT = pathlib.Path(__file__).resolve().parents[3]

#: The program's project directory, where its command line, probes and ``pyproject.toml`` live.
PROJECT = ROOT / "packages" / "zettcode"

#: Where each distribution's source tree is.
APP = ROOT / "packages" / "zettcode-app" / "src" / "zettcode" / "app"
SDK = ROOT / "packages" / "zettcode-sdk" / "src" / "zettcode" / "sdk"
BROKER = ROOT / "packages" / "zettcode-broker" / "src" / "zettcode" / "broker"
ENGINE = ROOT / "packages" / "zettcode-engine" / "src" / "zettcode"

#: One piece of evidence in ``docs/internal/invariants.md``: a test file and,
#: within the same row, the bare names that follow it.
CITATION = re.compile(r"`([^`]+)`")
PREFIXED = re.compile(r"(test_[a-z_]+)\.py::([A-Za-z_][A-Za-z0-9_]*)")
BARE = re.compile(r"test_[a-z_]+")


def test_every_invariant_has_one_id_of_its_own():
    """Two rows numbered alike inside one section make a citation ambiguous, and nothing else would notice.

    Numbering starts again in each section (`L1` is a layout rule in one and an import rule in another), so what
    has to be unique is the pair of the section and the id.
    """
    import collections

    text = (ROOT / "docs" / "internal" / "invariants.md").read_text(encoding="utf-8")
    repeated: list[str] = []
    for section in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        title, _, body = section.partition("\n")
        ids = re.findall(r"^\| ([A-Z]+\d+) \|", body, re.MULTILINE)
        repeated += [f"{title.strip()}: {name}" for name, count in collections.Counter(ids).items() if count > 1]

    assert repeated == []


def test_every_invariant_cites_a_test_that_exists():
    """A row's evidence has to be findable, or the mark cannot be trusted.

    Every row points at the test that fails when the rule breaks, and a row
    names the file once and then the rest of that row's tests by themselves, so
    this reads a row the way a reader does: the first citation names the file,
    the ones after it belong to it, and each has to exist there. A test renamed
    without its citation, or a name written with no file in front of it, sends a
    reader looking for evidence that is not where the row says it is.

    It sees cited evidence only. A test nothing cites that goes missing is indistinguishable from one that was never
    written, and requiring every test to be cited would be false for nearly all of them; what catches that is reading
    the diff of an edit that touches the neighbouring tests, not this.
    """
    document = (ROOT / "docs/internal/invariants.md").read_text(encoding="utf-8")
    # The evidence lives beside the code it pins: each distribution's tests are in its own `tests/`.
    evidence: dict[str, list[pathlib.Path]] = {}
    for path in sorted((ROOT / "packages").glob("*/tests/test_*.py")):
        evidence.setdefault(path.name, []).append(path)
    missing: list[str] = []
    unqualified: list[str] = []
    checked = 0
    for line in document.splitlines():
        current: str | None = None
        for piece in CITATION.findall(line):
            prefixed = PREFIXED.fullmatch(piece)
            if prefixed:
                current, name = prefixed.group(1), prefixed.group(2)
            elif BARE.fullmatch(piece):
                if current is None:
                    unqualified.append(piece)
                    continue
                name = piece
            else:
                continue
            checked += 1
            found = any(
                re.search(rf"^\s*(?:async )?def {re.escape(name)}\(", path.read_text(encoding="utf-8"), re.MULTILINE)
                for path in evidence.get(f"{current}.py", [])
            )
            if not found:
                missing.append(f"{current}::{name}")

    assert checked > 150, f"the citations stopped parsing: {checked} read"
    assert unqualified == [], f"cite the file once in the row first: {unqualified}"
    assert missing == []


# A module under one of these prefixes may not import anything under the others:
# the framework stays standalone, and the agent side never reaches into the ui.
LAYERS = (
    ("zettcode.tui", ("zettcode.app", "zettcode.cli", "zettcode.config")),
    ("zettcode.app.agent", ("zettcode.app.ui",)),
    # The shell and its views hold an SDK client and the terminal's agent; the engine is not theirs to import.
    ("zettcode.app.ui", ("zettcode.engine",)),
    ("zettcode.plugin_api.commands", ("zettcode.engine",)),
    # The engine is what the terminal and the SDK both drive, so it knows neither of them — and it does not reach
    # the broker, which is why the line to the other sessions is built by the SDK and only carried here.
    (
        "zettcode.engine",
        (
            "zettcode.app",
            "zettcode.tui",
            "zettcode.cli",
            "zettcode.sdk",
            "zettcode.server",
            "zettcode.gateway",
            "zettcode.broker",
            "zettcode.daemon",
        ),
    ),
    # The SDK is the public face of the engine; it reaches the terminal's code for nothing.
    ("zettcode.sdk", ("zettcode.app", "zettcode.tui", "zettcode.cli", "zettcode.server", "zettcode.gateway")),
    # The server is the SDK's HTTP face and holds no agent of its own: it reaches the agent through the SDK only.
    (
        "zettcode.server",
        ("zettcode.app", "zettcode.engine", "zettcode.tui", "zettcode.cli", "zettcode.broker", "zettcode.config"),
    ),
    # The broker is standard library only, and the shell imports it, never the other way round.
    ("zettcode.broker", ("zettcode.app", "zettcode.cli", "zettcode.config", "zettcode.tui")),
    # Three leaves every layer may use, so none may grow an import upward: the names a message's mode can have, the
    # command-line reader a package uses before it ends a process of its own, and the plain-text layout a command
    # prints with.
    (
        "zettcode.modes",
        (
            "zettcode.app",
            "zettcode.tui",
            "zettcode.cli",
            "zettcode.config",
            "zettcode.sdk",
            "zettcode.server",
            "zettcode.gateway",
            "zettcode.engine",
            "zettcode.broker",
            "zettcode.daemon",
        ),
    ),
    (
        "zettcode.processes",
        (
            "zettcode.app",
            "zettcode.tui",
            "zettcode.cli",
            "zettcode.config",
            "zettcode.sdk",
            "zettcode.server",
            "zettcode.gateway",
            "zettcode.engine",
            "zettcode.broker",
            "zettcode.daemon",
        ),
    ),
    (
        "zettcode.table",
        (
            "zettcode.app",
            "zettcode.tui",
            "zettcode.cli",
            "zettcode.config",
            "zettcode.sdk",
            "zettcode.server",
            "zettcode.gateway",
            "zettcode.engine",
            "zettcode.broker",
            "zettcode.daemon",
        ),
    ),
    # The plugin command is a shell helper for the environment: it reads installed metadata and drives pip, and it
    # belongs to no front end. It reaches the loader only for the entry-point group's name.
    (
        "zettcode.plugin_cli",
        (
            "zettcode.app",
            "zettcode.tui",
            "zettcode.cli",
            "zettcode.server",
            "zettcode.gateway",
            "zettcode.broker",
            "zettcode.daemon",
        ),
    ),
    # A daemon is a front end like the terminal's: a session run headless, through the SDK and the broker. It owns no
    # agent of its own, draws nothing, and serves nothing over HTTP. (It reads the session store's workspace naming
    # from `engine.storage.layout`, a path helper it shares with the store rather than a second spelling of it.)
    (
        "zettcode.daemon",
        ("zettcode.app", "zettcode.server", "zettcode.tui", "zettcode.cli", "zettcode.config"),
    ),
    # The gateway is the SDK's other front end besides the server: a web page over the agent and the daemons. It owns no
    # agent, reads nothing of the terminal, and reaches the broker, the engine and the daemons' records through the
    # SDK only.
    (
        "zettcode.gateway",
        (
            "zettcode.app",
            "zettcode.cli",
            "zettcode.config",
            "zettcode.tui",
            "zettcode.engine",
            "zettcode.broker",
            "zettcode.daemon",
            "zettcode.server",
        ),
    ),
    ("zettcode.filelock", ("zettcode.app", "zettcode.cli", "zettcode.config", "zettcode.tui", "zettcode.broker")),
)

#: Packages that re-export their subpackages lazily through ``__getattr__``.
FACADES = (
    "zettcode.app",
    "zettcode.app.agent",
    "zettcode.app.ui",
    "zettcode.app.ui.widgets",
    "zettcode.engine",
    "zettcode.tui",
    "zettcode.tui.widgets",
)


def _sources() -> list[tuple[pathlib.Path, str, bool]]:
    """Return every module as ``(path, dotted name, is package)``."""
    # `…/src/zettcode`, so the dotted name carries `app` as its first part.
    root = APP.parent
    modules: list[tuple[pathlib.Path, str, bool]] = []
    for path in sorted(root.rglob("*.py")):
        parts = list(path.relative_to(root).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        modules.append((path, ".".join(["zettcode", *parts]), is_package))
    return modules


def _resolved(module: str, is_package: bool, level: int, imported: str | None) -> str:
    """Return the dotted name a relative import points at."""
    package = module if is_package else module.rpartition(".")[0]
    for _ in range(level - 1):
        package = package.rpartition(".")[0]
    return f"{package}.{imported}" if imported else package


def _imports(path: pathlib.Path, module: str, is_package: bool) -> list[tuple[int, str, bool]]:
    """Return ``(line, dotted target, is relative)`` for every import in a file."""
    found: list[tuple[int, str, bool]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name, False) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append((node.lineno, _resolved(module, is_package, node.level, node.module), True))
            elif node.module:
                found.append((node.lineno, node.module, False))
    return found


def test_every_relative_import_resolves_to_a_real_module():
    """Moving a module is a chance to miscount the dots; check them all."""
    unresolved: list[str] = []
    for path, module, is_package in _sources():
        for line, target, relative in _imports(path, module, is_package):
            if not relative:
                continue
            try:
                exists = importlib.util.find_spec(target) is not None
            except ModuleNotFoundError:
                exists = False
            if not exists:
                unresolved.append(f"{module}:{line} resolves to {target}")

    assert unresolved == []


def test_no_import_climbs_more_than_two_packages_by_dots():
    """`from ...x` and deeper are written `from zettcode.x`; `.` and `..` stay relative."""
    deep: list[str] = []
    for path in sorted((ROOT / "packages").glob("*/src/zettcode/**/*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level > 2:
                deep.append(f"{path.relative_to(ROOT)}:{node.lineno} {'.' * node.level}{node.module or ''}")

    assert deep == []


def test_layers_only_import_downwards():
    """`ui` reads `agent`, `agent` builds on `tui`, and `tui` stands alone."""
    violations: list[str] = []
    for path, module, is_package in _sources():
        for line, target, _ in _imports(path, module, is_package):
            for owner, forbidden in LAYERS:
                if module.startswith(owner) and target.startswith(forbidden):
                    violations.append(f"{module}:{line} imports {target}")

    assert violations == []


#: What each part of ``zettcode.app.agent`` may import from its siblings, and nothing more.
#: The order runs one way: ``errors`` and ``tools`` stand alone (the tools are written here and know
#: nothing of the rest, only ``permission`` knows what a tool asks of it), ``dialogue`` takes the two search tools a
#: side question is given, ``storage`` builds on
#: the dialogue's side questions, ``extensions`` and ``conversation`` on those, ``runtime``
#: composes the extensions, and ``agent`` composes everything. A part that needed to import
#: *up* this table would be a cycle waiting for the first function-level import to hide it —
#: ``describe_error`` was exactly that, between the runtime and an extension, until it
#: moved to ``errors``.
AGENT_PARTS: dict[str, frozenset[str]] = {
    "errors": frozenset(),
    "dialogue": frozenset({"tools"}),
    "tools": frozenset(),
    "permission": frozenset({"tools"}),
    "storage": frozenset({"dialogue"}),
    "extensions": frozenset({"dialogue", "errors", "storage", "tools"}),
    "conversation": frozenset({"dialogue", "extensions", "storage"}),
    "export": frozenset({"dialogue", "extensions", "storage"}),
    "runtime": frozenset({"dialogue", "extensions", "permission", "storage"}),
    "agent": frozenset({"conversation", "dialogue", "export", "extensions", "permission", "runtime", "storage"}),
}


def _agent_part(module: str) -> str | None:
    """Return which part of ``zettcode.app.agent`` a module belongs to, if it is in one."""
    prefix = "zettcode.app.agent."
    if not module.startswith(prefix):
        return None
    head = module[len(prefix) :].split(".")[0]
    return head if head in AGENT_PARTS else None


def test_the_parts_of_the_agent_package_import_in_one_direction():
    """The grouping is only worth having if it keeps holding: each part imports what it is
    allowed to and nothing else, and every module sits in a part or is the facade itself."""
    seen: dict[str, set[str]] = {part: set() for part in AGENT_PARTS}
    unplaced: list[str] = []
    for path, module, is_package in _sources():
        if not module.startswith("zettcode.app.agent.") or module == "zettcode.app.agent":
            continue
        part = _agent_part(module)
        if part is None:
            unplaced.append(module)
            continue
        for _, target, _ in _imports(path, module, is_package):
            other = _agent_part(target)
            if other is not None and other != part:
                seen[part].add(other)

    assert unplaced == [], f"a module outside every part of the agent package: {unplaced}"
    exceeded = {part: sorted(found - AGENT_PARTS[part]) for part, found in seen.items() if found - AGENT_PARTS[part]}
    assert exceeded == {}, f"imports the table does not allow: {exceeded}"


def test_every_facade_publishes_what_it_promises():
    """A lazy re-export is easy to get wrong, so every name has to resolve."""
    missing: list[str] = []
    for name in FACADES:
        module = importlib.import_module(name)
        for attribute in module.__all__:
            try:
                getattr(module, attribute)
            except AttributeError as error:
                missing.append(f"{name}.{attribute}: {error}")

    assert missing == []


def test_importing_the_package_does_not_build_the_application():
    """Names are imported on use: ``import zettcode`` must not load the runtime."""
    script = "import zettcode, sys; print('zett_agent' in sys.modules, 'zettcode.app.ui' in sys.modules)"

    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"


def _release_order_module():
    """Return the generator a release publishes in the order of, loaded by path.

    `packages/order.txt` is a dump of this for a reader (`make order`) and is not in git, so the tests hold the script
    rather than a snapshot of what it printed once.
    """
    spec = importlib.util.spec_from_file_location("release_order", ROOT / ".github" / "scripts" / "release_order.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_order() -> list[str]:
    """Return the order a release publishes in, from the generator that computes it."""
    return _release_order_module().ordered()


def test_the_version_is_written_once_and_every_distribution_carries_it():
    """A copy of the version in a ``pyproject`` would drift from the tag check.

    One file holds it, `zettcode/version.py` in the engine's tree, and every distribution's `[tool.hatch.version]`
    reads that file. The installed metadata is compared as well, because it is what ``importlib.metadata`` reports to
    plugins and what a release publishes: bumping the file without rebuilding the editable install fails here until
    ``uv sync`` runs, and CI installs from scratch, so there the two always agree.
    """
    from zettcode.version import __version__

    for name in [*_release_order(), "zettcode"]:
        assert importlib.metadata.version(name) == __version__, name

    engine = tomllib.loads((ENGINE.parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert engine["project"]["dynamic"] == ["version"]
    assert engine["tool"]["hatch"]["version"]["path"] == "src/zettcode/version.py"
    assert engine["project"]["name"] == "zettcode-engine"


def test_each_extra_names_a_plugin_this_workspace_builds_in_a_range_that_admits_it():
    """`pip install "zettcode[monitor]"` is a range a reader resolves against a published plugin.

    uv resolves a workspace member for a dependency without checking the range that asks for it and records no
    specifier in the lock, so bumping a plugin past its extra — or leaving an extra behind at an older plugin's
    version — locks, tests and ships green, and fails only in a reader's environment. `make smoke` cannot see it
    either: it resolves the extra from PyPI, where a version that is not published yet does not exist.

    The inventory is the program's own extras, and each of them has to name a distribution this repository builds:
    the directories under `packages/` are the truth about what can be installed from here.
    """
    project = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]
    assert set(extras) == {"all", "monitor", "recap"}, "one extra per plugin this repository publishes"

    built = {path.name for path in (ROOT / "packages").iterdir() if (path / "pyproject.toml").is_file()}
    plugins = {"monitor": "zettcode-monitor", "recap": "zettcode-recap"}
    for extra, distribution in plugins.items():
        assert distribution in built, f"packages/{distribution} is what the {extra!r} extra names"
    carried = {Requirement(line) for extra in plugins for line in extras[extra]}
    assert {Requirement(line) for line in extras["all"]} == carried, "the `all` extra names every plugin extra"

    for extra, lines in extras.items():
        for line in lines:
            requirement = Requirement(line)
            built = importlib.metadata.version(requirement.name)
            assert requirement.specifier.contains(built, prereleases=True), (
                f"the {extra!r} extra requires {requirement}, which excludes {requirement.name} {built}, "
                "the version this workspace builds"
            )


def test_a_facade_maps_every_name_to_the_module_it_statically_imports():
    """The runtime map and the static imports a checker reads must agree.

    A lazy ``__getattr__`` is invisible to a type checker, so each facade also
    imports its names under ``TYPE_CHECKING``. Nothing at runtime notices when
    the two drift apart — a reader's editor does — so they are compared here.
    """
    drifted: list[str] = []
    for name in FACADES:
        module = importlib.import_module(name)
        tree = ast.parse(pathlib.Path(module.__file__).read_text(encoding="utf-8"))
        mapping = next(
            ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_EXPORTS"
        )
        static: dict[str, str] = {}
        for node in tree.body:
            if not (isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING"):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom):
                    target = "." * child.level + (child.module or "")
                    for alias in child.names:
                        static[alias.asname or alias.name] = target
        if static != mapping:
            drifted.append(f"{name}: static {sorted(static)} vs map {sorted(mapping)}")

    assert drifted == []


def test_the_engine_is_published_under_one_name():
    """The core is ``ZettCodeEngine``, in the engine package, and nothing answers to the name it had before."""
    import zettcode.engine
    from zettcode.engine import ZettCodeEngine

    assert zettcode.engine.ZettCodeEngine is ZettCodeEngine
    assert "ZettCodeEngine" in zettcode.engine.__all__
    assert not hasattr(zettcode.engine, "ZettCodeRuntime")


def test_importing_the_engine_loads_nothing_of_the_application():
    """The engine is the SDK's floor, so what it imports, directly or through a plugin, must not be the terminal's.

    The layer table above reads import statements; this reads what a fresh interpreter actually loads, which is how
    a dependency that goes round through the plugins shows up.
    """
    code = (
        "import sys, zettcode.engine.core, zettcode.engine.agent, zettcode.engine.plugins\n"
        "print(sorted(m for m in sys.modules if m == 'zettcode.app' or m.startswith('zettcode.app.')))"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert done.stdout.strip() == "[]"


def test_the_terminal_reads_the_agents_events_through_the_sdks_translation_and_not_a_second_one():
    """One translation of the agent's events, the SDK's, so what the terminal shows and what the SDK reports agree."""
    source = (APP / "agent/conversation/projection.py").read_text(encoding="utf-8")

    assert "zettcode.sdk.translation import" in source and "translate(" in source
    assert "AgentEventType" not in source, "a second reading of the agent's event types is a second translation"


def test_nothing_the_sdk_returns_or_accepts_is_a_type_of_the_broker_or_the_engine():
    """A public method whose signature names an internal type makes that type public by accident.

    Annotations are strings at run time (``from __future__ import annotations``) and the internal imports sit under
    ``TYPE_CHECKING``, so this reads the source: it collects the names a module imports from the broker or the
    engine, and looks for them in the annotations of every public function and method.
    """
    internal = ("zettcode.broker", "zettcode.engine")
    leaks: list[str] = []
    for module in ("client", "session", "handlers", "events", "types"):
        path = SDK / f"{module}.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                target = (
                    _resolved(f"zettcode.sdk.{module}", False, node.level, node.module) if node.level else node.module
                )
                if target and target.startswith(internal):
                    names.update({(alias.asname or alias.name): target for alias in node.names})
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
                continue
            annotations = [a.annotation for a in (*node.args.args, *node.args.kwonlyargs) if a.annotation]
            if node.returns:
                annotations.append(node.returns)
            for annotation in annotations:
                used = {n.id for n in ast.walk(annotation) if isinstance(n, ast.Name)}
                used |= {
                    n.value for n in ast.walk(annotation) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                }
                leaks.extend(f"{module}.{node.name}: {name} from {names[name]}" for name in sorted(used & names.keys()))
    assert leaks == []


def test_the_views_of_the_terminal_import_nothing_of_the_engine():
    """``app/ui`` and ``app/commands.py`` are the shell and its views: they hold an SDK client and the terminal's agent.

    The layer table says it with the engine's prefix; this is the same rule read the other way, so that a view cannot
    get round it by importing the engine from inside a function, which is how most of them used to.
    ``app/agent`` and ``app/plugins`` are where the terminal is put together from the engine's parts, and may import it,
    and it is there that the views are given the names of the engine objects they hold.
    """
    found = sorted(
        f"{module}:{line} imports {target}"
        for path, module, is_package in _sources()
        if module.startswith("zettcode.app.ui") or module == "zettcode.plugin_api.commands"
        for line, target, _relative in _imports(path, module, is_package)
        if target.startswith("zettcode.engine")
    )

    assert found == []


def test_the_shell_starts_a_run_through_the_sdk_and_never_streams_from_its_own_agent():
    """A turn, a side question and a continue are runs of the SDK: the agent's own ``stream`` is the SDK's to call.

    The shell answers an approval from a panel, later, which the SDK allows with ``defer_answers``; a shell that went
    round it would be running a turn that nothing denies when it ends, and one the SDK does not know is busy.
    """
    ui = APP / "ui"
    offenders = [
        f"{path.name}:{number}"
        for path in sorted(ui.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\bagent\.(stream|stream_resume)\(", line)
    ]

    assert offenders == []


def test_the_shell_does_not_reach_round_the_sdk_for_what_the_sdk_offers():
    """The models, the session, the settings, the plan and a steering message are the SDK client's to give and take.

    Each name here was once called on the terminal's agent and has an SDK counterpart now; this keeps it that way.
    What is left on the agent is the terminal's own (pets, themes, the status line, plugins) and the start of the
    engine, listed in ``docs/internal/engine.md``.
    """
    moved = (
        "active_model|models|find_model|use_model|file_models|config_file|add_configured_model|"
        "update_configured_model|remove_configured_model|change_compact_percent|tasks|steer|turn|"
        "session_id|session_locked|session_title|retake_session|rename_session|fork_session|title_session|"
        "load_session|install_session|use_effort|use_permission|use_harness|use_self_compaction|"
        "self_compaction_default|remember_self_compaction|effort|efforts|permission|permissions|harness"
    )
    pattern = re.compile(rf"\bagent\.({moved})\b")
    paths = [*(APP / "ui").rglob("*.py"), APP / "plugins/builtin_commands.py"]
    offenders = [
        f"{path.name}:{number}: {line.strip()}"
        for path in sorted(paths)
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]

    assert offenders == []


def test_the_hub_and_the_roster_know_nothing_of_the_web():
    """What the broker decides is separate from how it is served: the hub and the roster import none of the web
    libraries (nor the web layer), so they can be driven, and read, without a socket."""
    root = BROKER
    forbidden = ("starlette", "uvicorn", "websockets", "httpx", "zettcode.broker.web", "zettcode.broker.server")
    found: list[str] = []
    for name in ("hub.py", "roster.py", "protocol.py", "text.py"):
        tree = ast.parse((root / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [("." * node.level) + (node.module or "")]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for module in modules:
                if module.startswith(forbidden) or module in (".web", ".server", ".runner"):
                    found.append(f"{name}: {module}")

    assert found == []


#: What the engine's distribution ships besides its own tree: the leaves the runtime is written on. They are the
#: engine's because it may not import anything of ours, which is what lets a plugin depend on the engine alone.
ENGINE_LEAVES = frozenset(
    {
        "_compat",
        "budget",
        "config",
        "config_edit",
        "error_text",
        "filelock",
        "logging_setup",
        "mention",
        "modes",
        "paths",
        "plugin_tui",
        "processes",
        "prompt",
        "providers",
        "registry",
        "relay",
        "statusline_parts",
        "wire",
        "wording",
    }
)


def test_the_engine_imports_only_what_its_package_ships():
    """The engine is the root of the split: the only things it imports of ours are the leaves it ships.

    An import of anything above it — the SDK, the terminal, the broker, the server — is a dependency a plugin would
    have to carry to use the engine, and one the namespace split cannot express without a cycle. `docs/internal/
    namespace-split.md` is the plan this list comes from.
    """
    source = ENGINE
    offenders: list[str] = []
    # The whole tree the wheel carries, the leaves included: a leaf that reached above the engine would be the same
    # defect in a different file.
    for path in sorted(source.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                targets = [node.module]
            elif isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            for target in targets:
                parts = target.split(".")
                if len(parts) < 2 or parts[0] != "zettcode" or parts[1] == "engine":
                    continue
                if parts[1] not in ENGINE_LEAVES:
                    offenders.append(f"{path.relative_to(source)}: {target}")

    assert sorted(offenders) == []
    missing = sorted(name for name in ENGINE_LEAVES if not (source / f"{name}.py").is_file())
    assert missing == [], f"the engine's leaves are all present; missing {missing}"


def test_a_plugin_depends_on_one_package_of_ours_and_imports_from_it():
    """The split exists so a plugin installs one package: `zettcode-plugin-api`, and nothing else of ours.

    A plugin that names `zettcode-app` or `zettcode-engine` in its dependencies, or imports one of them directly,
    works here and breaks for a reader the moment one of them moves: the API package is the seam, and this holds the
    two plugins to it.
    """
    checked = 0
    for project in sorted((ROOT / "packages").glob("*/pyproject.toml")):
        settings = tomllib.loads(project.read_text(encoding="utf-8"))
        if not settings.get("project", {}).get("entry-points", {}).get("zettcode.plugins"):
            continue
        checked += 1
        name = settings["project"]["name"]
        ours = [
            requirement
            for requirement in map(Requirement, settings["project"]["dependencies"])
            if requirement.name.startswith("zettcode")
        ]
        assert [requirement.name for requirement in ours] == ["zettcode-plugin-api"], name

        # The plugin's own module is inside the namespace too, so a subpackage two levels down has to be able to
        # import it absolutely: the climb rule forbids `from ...x`, and `from zettcode.monitor.x` is the spelling it
        # prescribes. Everything else of ours has to come through the API package.
        own = {value.split(":", 1)[0] for value in settings["project"]["entry-points"]["zettcode.plugins"].values()}
        imports = sorted(
            target
            for path in (project.parent / "src").rglob("*.py")
            for target in _imported_modules(path)
            if target.startswith("zettcode.")
            and target != "zettcode.plugin_api"
            and not target.startswith("zettcode.plugin_api.")
            and not any(target == module or target.startswith(f"{module}.") for module in own)
        )
        assert imports == [], f"{name} imports outside the API: {imports}"

    assert checked >= 2, "the plugins this repository ships are the ones this checks"


def _imported_modules(path: pathlib.Path) -> list[str]:
    """Return every `zettcode.*` module a file imports, by its absolute name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # A plugin ships a top-level module of its own, so only its absolute imports of the namespace are the rule's.
    return [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module.startswith("zettcode")
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.startswith("zettcode")
    ]


def test_the_release_order_lists_every_distribution_once_with_its_dependencies_first():
    """The generated order is what `release.yml` publishes in, and a distribution must not go before what it needs:
    PyPI has no transaction, so a wrong order publishes something whose dependency is still missing.

    The plugins are released on their own lines and are not in the list; every other distribution under `packages/`
    is, exactly once.
    """
    package = ROOT / "packages"
    order = _release_order()
    distributions: dict[str, pathlib.Path] = {}
    plugins: set[str] = set()
    for project in sorted(package.glob("*/pyproject.toml")):
        settings = tomllib.loads(project.read_text(encoding="utf-8"))
        name = settings["project"]["name"]
        if settings["project"].get("entry-points", {}).get("zettcode.plugins"):
            plugins.add(name)
        else:
            distributions[name] = project

    assert set(order) == set(distributions), "every distribution of the program, once each"
    assert len(order) == len(set(order))
    for index, name in enumerate(order):
        settings = tomllib.loads(distributions[name].read_text(encoding="utf-8"))
        for requirement in map(Requirement, settings["project"]["dependencies"]):
            if requirement.name in distributions:
                assert order.index(requirement.name) < index, f"{name} needs {requirement.name} published first"


class Distribution(NamedTuple):
    """One distribution, as the import rules need to see it."""

    directory: pathlib.Path
    #: The distributions of ours it declares.
    declared: set[str]
    #: Distributions of ours named in an extra: importable for types, never at run time.
    optional: set[str]
    #: The top-level names it puts in the `zettcode` namespace.
    shipped: set[str]
    #: The top-level names it ships outside the namespace (a plugin ships one module).
    own: set[str]
    #: The third-party names it declares, extras included, and the ones a dependency provides.
    external: set[str]


#: Imported directly, but provided by another dependency rather than declared by name.
PROVIDED_BY = {"pydantic_core": "pydantic"}

#: Standard library from 3.11 on, so a 3.10 interpreter's table lacks them while the shims name them anyway (and
#: declare `tomli`, the backport). Counting the running interpreter's table alone fails this guard on the floor.
LATER_STDLIB = frozenset({"tomllib"})


def _type_only_imports(path: pathlib.Path) -> set[str]:
    """Return the `zettcode.*` modules a file imports under `if TYPE_CHECKING:` and nowhere else.

    Such an import costs nothing at run time and cannot fail there, so a distribution may take its types from one it only
    offers through an extra (the plugin contract types `host.client` against the SDK without depending on it).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def guarded(node: ast.AST) -> bool:
        test = getattr(node, "test", None)
        return isinstance(node, ast.If) and (
            (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING")
            or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
        )

    inside: set[str] = set()
    outside: set[str] = set()

    def visit(node: ast.AST, in_block: bool) -> None:
        # Only the body of `if TYPE_CHECKING:` is type-only. Its `else:` (and an `elif`, which is an `If` in the
        # `else:`) runs exactly when the checker does not, so it inherits whatever the enclosing code is.
        if guarded(node):
            assert isinstance(node, ast.If)
            visit(node.test, in_block)
            for statement in node.body:
                visit(statement, True)
            for statement in node.orelse:
                visit(statement, in_block)
            return
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            (inside if in_block else outside).add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                (inside if in_block else outside).add(alias.name)
        for child in ast.iter_child_nodes(node):
            visit(child, in_block)

    visit(tree, False)
    return {module for module in inside - outside if module.startswith("zettcode")}


def _shipped_distributions() -> dict[str, Distribution]:
    """Return every distribution under `packages/`, with what it ships and what it declares."""
    found: dict[str, Distribution] = {}
    for project in sorted((ROOT / "packages").glob("*/pyproject.toml")):
        settings = tomllib.loads(project.read_text(encoding="utf-8"))
        name = settings["project"]["name"]
        requirements = [Requirement(line) for line in settings["project"]["dependencies"]]
        extras = [
            Requirement(line)
            for lines in settings["project"].get("optional-dependencies", {}).values()
            for line in lines
        ]
        tree = project.parent / "src" / "zettcode"
        shipped = {
            entry.stem if entry.is_file() else entry.name
            for entry in (tree.iterdir() if tree.is_dir() else ())
            if entry.name not in ("__pycache__", "py.typed")
        }
        own = {
            entry.stem if entry.is_file() else entry.name
            for entry in (project.parent / "src").iterdir()
            if entry.name not in ("__pycache__", "zettcode")
        }
        found[name] = Distribution(
            directory=project.parent,
            declared={requirement.name for requirement in requirements if requirement.name.startswith("zettcode")},
            optional={requirement.name for requirement in extras if requirement.name.startswith("zettcode")},
            shipped=shipped,
            own=own,
            external={requirement.name.replace("-", "_") for requirement in (*requirements, *extras)},
        )
    return found


def _module_level_imports(path: pathlib.Path) -> list[str]:
    """Return the modules a file imports outside any function or class.

    An import inside a function is the module's own business — a fallback, an optional feature — and costs a reader
    nothing at install time. An import at the top level, including one inside a version branch, is what a wheel has to
    carry to be importable at all.
    """
    found: list[str] = []

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.Import):
                found.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.append(node.module)
            for field in ("body", "orelse", "finalbody"):
                visit(list(getattr(node, field, []) or []))
            for handler in getattr(node, "handlers", []) or []:
                visit(handler.body)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def _namespace_imports(path: pathlib.Path) -> list[str]:
    """Return every `zettcode.*` module a source file imports, by its absolute dotted name.

    Relative imports are resolved to the absolute name they stand for, so an import that climbs out of a distribution
    is checked like any other.
    """
    source_root = path.parent
    while source_root.name != "src":
        source_root = source_root.parent
    parts = list(path.relative_to(source_root).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    module = ".".join(parts)

    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [
                alias.name for alias in node.names if alias.name == "zettcode" or alias.name.startswith("zettcode.")
            ]
        elif isinstance(node, ast.ImportFrom):
            base = node.module if node.level == 0 else _resolved(module, is_package, node.level, node.module)
            if base is None:
                continue
            if base == "zettcode":
                found += [f"zettcode.{alias.name}" for alias in node.names]
            elif base.startswith("zettcode."):
                found.append(base)
    return found


def test_every_distribution_imports_only_what_it_declares():
    """A namespace hides a dependency: `zettcode.x` resolves whoever shipped `x`, so an import of another
    distribution's module works in the checkout and fails in a venv holding one wheel.

    Both halves are checked against what the distribution declares: every absolute `zettcode.<name>` import has to
    name a module it ships or one whose distribution it declares, and every top-level third-party import has to be a
    dependency (or an extra) of its own — the module-level ones only, since a lazy import has a fallback. This is the
    rule the split lives or dies by, and the one that breaks first as modules move.
    """
    distributions = _shipped_distributions()
    owner: dict[str, str] = {}
    for name, distribution in distributions.items():
        for module in distribution.shipped:
            assert module not in owner, f"{module} is shipped by {owner.get(module)} and {name}"
            owner[module] = name

    offenders: list[str] = []
    for name, distribution in distributions.items():
        for path in sorted((distribution.directory / "src").rglob("*.py")):
            where = f"{name}: {path.relative_to(distribution.directory)}"

            type_only = _type_only_imports(path)
            for target in _namespace_imports(path):
                parts = target.split(".")
                if len(parts) < 2:
                    continue  # `import zettcode` is the namespace itself
                shipped_by = owner.get(parts[1])
                if shipped_by is None:
                    offenders.append(f"{where} imports {target}, which no distribution ships")
                elif shipped_by == name or shipped_by in distribution.declared:
                    continue
                elif shipped_by in distribution.optional and target in type_only:
                    continue  # offered through an extra, and only the type checker reads the import
                elif shipped_by in distribution.optional:
                    offenders.append(
                        f"{where} imports {target} from {shipped_by} at run time, which {name} offers only as an extra"
                    )
                else:
                    offenders.append(f"{where} imports {target} from {shipped_by}, which {name} does not declare")

            for target in _module_level_imports(path):
                top = target.split(".")[0]
                if (
                    top in sys.stdlib_module_names
                    or top in LATER_STDLIB
                    or top == "zettcode"
                    or top in distribution.own
                ):
                    continue
                provided = PROVIDED_BY.get(top)
                if provided is not None and provided in distribution.external:
                    continue
                if top not in distribution.external:
                    offenders.append(f"{where} imports {top} at module level, which {name} does not declare")

    assert offenders == []


def test_every_test_path_the_documents_name_exists():
    """A document that points at a test is evidence a reader follows, and a test that moved leaves a path nobody can.

    `docs/internal/invariants.md` is checked by file and name; the other documents name tests by path, and this
    repository just moved them by the hundred, so every `packages/<distribution>/tests/<file>.py` a document spells
    has to be there.
    """
    pattern = re.compile(r"packages/[A-Za-z0-9_.-]+/tests/[A-Za-z0-9_.-]+\.py")
    documents = [
        ROOT / "AGENTS.md",
        ROOT / "RELEASING.md",
        ROOT / "pyproject.toml",
        *sorted((ROOT / "docs").rglob("*.md")),
    ]
    missing = [
        f"{path.relative_to(ROOT)}: {named}"
        for path in documents
        if ".vitepress" not in path.parts
        for named in pattern.findall(path.read_text(encoding="utf-8"))
        if not (ROOT / named).is_file()
    ]

    assert missing == []


def test_every_distribution_ships_under_the_zettcode_namespace():
    """One namespace, and no distribution with a top-level module of its own.

    A PEP 420 namespace is the union of what is installed: it works because no distribution ships
    `zettcode/__init__.py`, and because every one of them puts its modules under `zettcode/` and builds its wheel from
    that tree. A distribution that grows a top-level directory is a second import root a reader has to know about —
    the plugins had `zettcode_monitor` and `zettcode_recap` before they joined it.
    """
    offenders: list[str] = []
    for project in sorted((ROOT / "packages").glob("*/pyproject.toml")):
        name = project.parent.name
        src = project.parent / "src"
        shipped = sorted(entry.name for entry in src.iterdir() if entry.name != "__pycache__")
        if shipped != ["zettcode"]:
            offenders.append(f"{name}: ships {shipped}")
        if (src / "zettcode" / "__init__.py").exists():
            offenders.append(f"{name}: ships zettcode/__init__.py, which makes the namespace a package")
        if 'packages = ["src/zettcode"]' not in project.read_text(encoding="utf-8"):
            offenders.append(f"{name}: its wheel is not built from src/zettcode")

    assert offenders == []


def test_the_release_order_refuses_a_cycle_and_a_dependency_nobody_ships(tmp_path, monkeypatch):
    """What the generator promises is an error, not a short list: an edge it cannot order would otherwise disappear.

    A cycle is the obvious case. The quiet one is a name no distribution in the graph has — a typo, or a program
    distribution that started depending on a plugin, which is published on its own line — because the readiness check
    only looks at what is left and would simply drop it.
    """
    generator = _release_order_module()
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    packages = tmp_path / "packages"

    def write(name: str, needs: tuple[str, ...]) -> None:
        directory = packages / name
        directory.mkdir(parents=True, exist_ok=True)
        dependencies = "".join(f'  "{need}",\n' for need in needs)
        (directory / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "1.0"\ndependencies = [\n{dependencies}]\n',
            encoding="utf-8",
        )

    write("zettcode-a", ("zettcode-b>=1",))
    write("zettcode-b", ("zettcode-a>=1",))
    with pytest.raises(generator.Cycle, match="need each other"):
        generator.ordered()

    write("zettcode-b", ("zettcode-missing>=1",))
    with pytest.raises(generator.Cycle, match="zettcode-missing"):
        generator.ordered()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "if TYPE_CHECKING:\n    from zettcode.sdk.types import Usage\n", {"zettcode.sdk.types"}, id="body"
        ),
        pytest.param(
            "if TYPE_CHECKING:\n    from zettcode.sdk.types import Usage\nelse:\n    from zettcode.sdk.types import M\n",
            set(),
            id="the else branch runs when the checker does not",
        ),
        pytest.param(
            "if TYPE_CHECKING:\n    from zettcode.sdk.a import A\nelif sys.platform:\n    from zettcode.sdk.a import B\n",
            set(),
            id="an elif is an else",
        ),
        pytest.param(
            "if TYPE_CHECKING:\n    from zettcode.sdk.a import A\nelse:\n    from zettcode.sdk.b import B\n",
            {"zettcode.sdk.a"},
            id="a different module in the else branch leaves the guarded one type-only",
        ),
        pytest.param(
            "if not TYPE_CHECKING:\n    from zettcode.sdk.a import A\n", set(), id="negated is a run-time import"
        ),
        pytest.param(
            "import typing\nif typing.TYPE_CHECKING:\n    import zettcode.sdk.a\n",
            {"zettcode.sdk.a"},
            id="the attribute spelling",
        ),
        pytest.param(
            "from zettcode.sdk.a import A\nif TYPE_CHECKING:\n    from zettcode.sdk.a import B\n",
            set(),
            id="also imported at run time",
        ),
        pytest.param(
            "def f():\n    if TYPE_CHECKING:\n        from zettcode.sdk.a import A\n",
            {"zettcode.sdk.a"},
            id="in a function",
        ),
    ],
)
def test_only_the_body_of_a_type_checking_block_is_type_only(tmp_path, source: str, expected: set[str]):
    """The extras rule trusts this helper: an import it calls type-only is one a distribution may take from an extra."""
    module = tmp_path / "probe.py"
    module.write_text(source, encoding="utf-8")

    assert _type_only_imports(module) == expected


#: The calls that evaluate an annotation, which resolves every name in it -- the ones that exist only for the type checker
#: included. This is the set of tools this repository uses; a library that introspects annotations in its own way
#: (`attrs.resolve_types`, `typeguard`, `beartype`, `pydantic.validate_call`) is a new name, to be added here with the
#: first use rather than discovered in a bug report.
ANNOTATION_EVALUATORS = {"get_type_hints", "get_annotations", "TypeAdapter", "validate_call", "resolve_types"}

#: What may be evaluated today, by the TYPE it is evaluated on and not by the file that does it, because the premise is
#: about the type: every one is defined in the engine without a name that exists only under `TYPE_CHECKING`. The value is
#: the module that DEFINES it -- a bare name is not an identity (`Line` is also an unrelated alias in the terminal's usage
#: charts), and a contract class that happened to share one must not pass for it. `Line` and `MetadataRecord` are the
#: session store's own discriminated unions of models.
EVALUATED_TYPES = {
    "ZettCodeConfig": "zettcode.config",
    "Line": "zettcode.engine.storage.records",
    "MetadataRecord": "zettcode.engine.storage.metadata",
}


def _module_of(source: pathlib.Path) -> str:
    """Return the dotted module a file under `packages/<name>/src/` is."""
    parts = source.relative_to(ROOT / "packages").parts[2:]  # drop `<name>/src`
    return ".".join(parts).removesuffix(".py").removesuffix(".__init__")


def _origin(tree: ast.Module, module: str, name: str) -> str | None:
    """Return the module a name used in a file comes from: an absolute import of it, else this file if it defines it."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if any((alias.asname or alias.name) == name for alias in node.names):
                return node.module
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return module
        targets = (
            node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        )
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            return module
    return None


def _evaluated_name(target: ast.expr) -> str | None:
    """Return the name of the type an evaluator is called on, or ``None`` when the source does not name one.

    `cast(Any, Line)` is `Line`, `module.Line` is `Line`; a call, a subscript or an attribute of a value
    (`self.config.__class__`) is a type chosen at run time, which a syntactic scan cannot name.
    """
    if isinstance(target, ast.Call) and getattr(target.func, "id", "") == "cast" and len(target.args) == 2:
        return _evaluated_name(target.args[1])
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
        return target.attr
    return None


def test_no_annotation_of_the_plugin_contract_is_evaluated_anywhere():
    """The `types` extra is safe because nothing resolves the annotations of the contract, here or in a consumer.

    `zettcode-plugin-api` imports the SDK's `Client`, `ModelInfo` and `Usage` for the type checker only, so a plugin that
    does not install the extra still imports every name. That holds while the annotations stay strings. The plausible
    accident is not in the contract but in whoever consumes it: the HTTP API serialising a shell snapshot with a
    `TypeAdapter`, or a page resolving hints on `DisplayState`. Neither is visible from the contract's own files, so this
    scans every module of every distribution for a call that evaluates annotations and requires the type it is evaluated
    on to be one of the engine's (`EVALUATED_TYPES`). Before adding a contract class to a pydantic model, or a new
    evaluator, look at the ones listed there.

    What it cannot see, and what covers it. A FastAPI route that annotates its body or return with a contract class
    registers without complaint and fails only when the schema is built, so it is not this scan's to find: the server
    does not depend on the contract (`test_only_the_terminal_its_rows_and_the_plugins_know_the_plugin_contract`), and
    `packages/zettcode-server/tests/test_server_api.py::test_the_openapi_schema_lists_the_endpoints` builds the real
    schema. A spelling no scan can name (`getattr(typing, "get_type_hints")`) or a type chosen at run time is the honest
    limit of a syntactic guard; a new evaluator is a new name in `ANNOTATION_EVALUATORS`.
    """
    offenders: list[str] = []
    found = 0
    for source in sorted((ROOT / "packages").glob("*/src/**/*.py")):
        if "__pycache__" in source.parts:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"))
        # `from pydantic import TypeAdapter as adapter` is the same call under another name, and the aliased spelling is
        # exactly how an accident would arrive: so a name is resolved to what it was imported as before it is judged.
        imported_as = {
            alias.asname: alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
            if alias.asname
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if isinstance(function, ast.Subscript):  # `TypeAdapter[X](...)`
                function = function.value
            name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
            name = imported_as.get(name, name)
            if name not in ANNOTATION_EVALUATORS:
                continue
            found += 1
            where = f"{source.relative_to(ROOT)}:{node.lineno}"
            if not node.args:
                offenders.append(
                    f"{where} {name}() evaluates an expression this scan cannot name -- it has no argument"
                )
                continue
            evaluated = _evaluated_name(node.args[0])
            if evaluated is None:
                offenders.append(
                    f"{where} {name}() evaluates an expression this scan cannot name -- call it on a plain name, "
                    "or teach the scan the spelling"
                )
            elif evaluated not in EVALUATED_TYPES:
                offenders.append(f"{where} {name}() evaluates {evaluated}, which is not in EVALUATED_TYPES")
            elif (origin := _origin(tree, _module_of(source), evaluated)) != EVALUATED_TYPES[evaluated]:
                offenders.append(
                    f"{where} {name}() evaluates {evaluated} from {origin}, but EVALUATED_TYPES allows the one "
                    f"{EVALUATED_TYPES[evaluated]} defines"
                )

    assert found >= 3, "the scan must still see the evaluators this repository has"
    assert offenders == []


def test_every_type_the_evaluators_may_resolve_is_defined_without_a_checker_only_name():
    """The allowlist is a promise about identity, not spelling: the allowed module defines each type, once, and the
    plugin contract defines none of the names.

    Otherwise a class called `Line` in `zettcode-plugin-api` would be indistinguishable from the session store's, and the
    scan above would wave an evaluation of it through. Each allowed type also names nothing that exists only under
    `TYPE_CHECKING` -- listing one that does would make the scan pass for a type whose evaluation fails at run time.
    """
    contract = ROOT / "packages" / "zettcode-plugin-api"
    for source in sorted(contract.glob("src/**/*.py")):
        for node in ast.parse(source.read_text(encoding="utf-8")).body:
            defined = (
                [node.name]
                if isinstance(node, ast.ClassDef)
                else [
                    t.id
                    for t in (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else [node.target]
                        if isinstance(node, ast.AnnAssign)
                        else []
                    )
                    if isinstance(t, ast.Name)
                ]
            )
            assert not set(defined) & set(EVALUATED_TYPES), (source.name, sorted(set(defined) & set(EVALUATED_TYPES)))

    by_module = {
        _module_of(source): source
        for source in (ROOT / "packages").glob("*/src/**/*.py")
        if "__pycache__" not in source.parts
    }
    for name, module in EVALUATED_TYPES.items():
        source = by_module[module]
        tree = ast.parse(source.read_text(encoding="utf-8"))
        found = [
            node
            for node in tree.body
            if (isinstance(node, ast.ClassDef) and node.name == name)
            or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets))
            or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name)
        ]
        assert len(found) == 1, f"{module} defines {name} {len(found)} times"
        guarded = {
            alias.asname or alias.name.split(".")[0]
            for statement in ast.walk(tree)
            if isinstance(statement, ast.If)
            and getattr(statement.test, "id", getattr(statement.test, "attr", "")) == "TYPE_CHECKING"
            for child in statement.body
            if isinstance(child, (ast.Import, ast.ImportFrom))
            for alias in child.names
        }
        used = {n.id for n in ast.walk(found[0]) if isinstance(n, ast.Name)}
        assert not (used & guarded), (name, source.name, sorted(used & guarded))


#: The distributions that know the plugin contract: the two that are written against it (the terminal and its built-in
#: rows), the plugins that implement it, the program that installs it, and the contract itself. Everything else -- the
#: server, the gateway, the SDK, the broker, the widget framework and the engine -- is not.
KNOWS_THE_CONTRACT = {
    "zettcode",
    "zettcode-app",
    "zettcode-monitor",
    "zettcode-plugin-api",
    "zettcode-presenters",
    "zettcode-recap",
}


def test_only_the_terminal_its_rows_and_the_plugins_know_the_plugin_contract():
    """The faces of the SDK (HTTP, the web gateway) never hold a contract class, so nothing there can serialise one.

    A contract class is not a model: its annotations name the SDK's types for the checker alone, and a framework that
    builds a response from a return annotation would resolve them. The server and the gateway are where that framework
    is, so they do not depend on the contract, and `test_every_distribution_imports_only_what_it_declares` turns an
    import of it there into a failure. A route that annotates one registers without complaint and fails only when the
    schema is built, which `packages/zettcode-server/tests/test_server_api.py::test_the_openapi_schema_lists_the_endpoints`
    does for the real app. This test makes adding the dependency itself a decision: it cannot be added without changing
    the list above, which says why the list is short.
    """
    others = KNOWS_THE_CONTRACT - {"zettcode-plugin-api"}
    knows = {
        name
        for name, distribution in _shipped_distributions().items()
        if "zettcode-plugin-api" in distribution.declared
    }

    assert knows == others, knows ^ others


def _declared(distribution: str) -> set[str]:
    """Return the distributions of ours that one declares as dependencies."""
    settings = tomllib.loads((ROOT / "packages" / distribution / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        requirement.name
        for requirement in map(Requirement, settings["project"]["dependencies"])
        if requirement.name.startswith("zettcode")
    }


def test_the_plugin_contract_sits_below_what_implements_it_and_below_the_application():
    """`plugin-api` defines the contract; `presenters` and `app` are written against it, in that order.

    The direction is the point of splitting them. A contract that depended on the application could not be installed
    without it, and one that depended on an implementation of itself would hand the plugin a second package to depend
    on. So the contract needs the runtime and the widget framework, and nothing above them; the built-in rows
    need the contract; the application needs both; and a release publishes them in that order.
    """
    api, rows, app = (_declared(name) for name in ("zettcode-plugin-api", "zettcode-presenters", "zettcode-app"))

    # No SDK among them: it is only needed to type-check a plugin, so it is the `types` extra and not a dependency.
    assert api == {"zettcode-engine", "zettcode-tui"}
    assert "zettcode-plugin-api" in rows and rows.isdisjoint({"zettcode-app", "zettcode-gateway", "zettcode-server"})
    assert {"zettcode-plugin-api", "zettcode-presenters"} <= app

    order = _release_order()
    assert order.index("zettcode-plugin-api") < order.index("zettcode-presenters") < order.index("zettcode-app")


def test_a_part_the_program_is_made_of_is_never_discoverable_as_a_plugin():
    """What `[plugins] disable` can reach is what an entry point makes discoverable, so a part must not have one.

    `zettcode-presenters` is the first built-in part to be a distribution of its own. If it declared a
    `zettcode.plugins` entry point it would load as an installed plugin, and a line in the configuration could switch
    the transcript's rows off; listing it in the program's built-ins is what makes that impossible.
    """
    parts = [name for name in _release_order() if name != "zettcode-plugin-api"]
    assert "zettcode-presenters" in parts
    for name in parts:
        settings = tomllib.loads((ROOT / "packages" / name / "pyproject.toml").read_text(encoding="utf-8"))
        assert not settings["project"].get("entry-points", {}).get("zettcode.plugins"), name
