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

import zettcode
from zettcode._compat import tomllib

#: The repository root, two levels above the tests (``zettcode/tests`` here).
ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The package's own project directory, where its sources, probes and ``pyproject.toml`` live.
PROJECT = ROOT / "zettcode"

#: One piece of evidence in ``docs/internal/invariants.md``: a test file and,
#: within the same row, the bare names that follow it.
CITATION = re.compile(r"`([^`]+)`")
PREFIXED = re.compile(r"(test_[a-z_]+)\.py::([A-Za-z_][A-Za-z0-9_]*)")
BARE = re.compile(r"test_[a-z_]+")


def test_every_invariant_cites_a_test_that_exists():
    """A row's evidence has to be findable, or the mark cannot be trusted.

    Every row points at the test that fails when the rule breaks, and a row
    names the file once and then the rest of that row's tests by themselves, so
    this reads a row the way a reader does: the first citation names the file,
    the ones after it belong to it, and each has to exist there. A test renamed
    without its citation, or a name written with no file in front of it, sends a
    reader looking for evidence that is not where the row says it is.
    """
    document = (ROOT / "docs/internal/invariants.md").read_text(encoding="utf-8")
    # The evidence lives in one suite now: the server's tests sit beside the agent's, under ``zettcode/tests``.
    evidence: dict[str, list[pathlib.Path]] = {}
    for path in (PROJECT / "tests").glob("test_*.py"):
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
    ("zettcode.app.commands", ("zettcode.engine",)),
    # The engine is what the terminal and the SDK both drive, so it knows neither of them.
    ("zettcode.engine", ("zettcode.app", "zettcode.tui", "zettcode.cli", "zettcode.sdk", "zettcode.server")),
    # The SDK is the public face of the engine; it reaches the terminal's code for nothing.
    ("zettcode.sdk", ("zettcode.app", "zettcode.tui", "zettcode.cli", "zettcode.server")),
    # The server is the SDK's HTTP face and holds no agent of its own: it reaches the agent through the SDK only.
    (
        "zettcode.server",
        ("zettcode.app", "zettcode.engine", "zettcode.tui", "zettcode.cli", "zettcode.broker", "zettcode.config"),
    ),
    # The broker is standard library only, and the shell imports it, never the other way round.
    ("zettcode.broker", ("zettcode.app", "zettcode.cli", "zettcode.config", "zettcode.tui")),
    # A daemon is a front end like the terminal's: a session run headless, through the SDK and the broker. It owns no
    # agent of its own, draws nothing, and serves nothing over HTTP. (It reads the session store's workspace naming
    # from `engine.storage.layout`, a path helper it shares with the store rather than a second spelling of it.)
    (
        "zettcode.daemon",
        ("zettcode.app", "zettcode.server", "zettcode.tui", "zettcode.cli", "zettcode.config"),
    ),
    ("zettcode.filelock", ("zettcode.app", "zettcode.cli", "zettcode.config", "zettcode.tui", "zettcode.broker")),
)

#: Packages that re-export their subpackages lazily through ``__getattr__``.
FACADES = (
    "zettcode",
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
    root = pathlib.Path(zettcode.__file__).parent
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
    for path in sorted((PROJECT / "src" / "zettcode").rglob("*.py")):
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


def test_the_version_is_written_once_and_the_distribution_carries_it():
    """A copy of the version in ``pyproject`` would drift from the tag check.

    The installed metadata is compared as well, because it is what
    ``importlib.metadata`` reports to plugins and what a release actually
    publishes. Bumping ``__version__`` without rebuilding the editable install
    fails here until ``uv sync --reinstall-package zettcode`` runs; CI installs
    from scratch, so there the two always agree.
    """
    project = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["dynamic"] == ["version"]
    assert project["tool"]["hatch"]["version"]["path"] == "src/zettcode/__init__.py"
    assert project["project"]["name"] == zettcode.__name__
    assert zettcode.__version__ == importlib.metadata.version("zettcode")


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
    """The core is ``ZettCodeEngine`` and nothing answers to the name it had before."""
    from zettcode.engine import ZettCodeEngine

    assert zettcode.ZettCodeEngine is ZettCodeEngine
    assert "ZettCodeEngine" in zettcode.__all__
    assert not hasattr(zettcode, "ZettCodeRuntime")


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
    source = (PROJECT / "src/zettcode/app/agent/conversation/projection.py").read_text(encoding="utf-8")

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
        path = PROJECT / "src/zettcode/sdk" / f"{module}.py"
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
        if module.startswith("zettcode.app.ui") or module == "zettcode.app.commands"
        for line, target, _relative in _imports(path, module, is_package)
        if target.startswith("zettcode.engine")
    )

    assert found == []


def test_the_shell_starts_a_run_through_the_sdk_and_never_streams_from_its_own_agent():
    """A turn, a side question and a continue are runs of the SDK: the agent's own ``stream`` is the SDK's to call.

    The shell answers an approval from a panel, later, which the SDK allows with ``defer_answers``; a shell that went
    round it would be running a turn that nothing denies when it ends, and one the SDK does not know is busy.
    """
    ui = PROJECT / "src/zettcode/app/ui"
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
    paths = [*(PROJECT / "src/zettcode/app/ui").rglob("*.py"), PROJECT / "src/zettcode/app/plugins/builtin_commands.py"]
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
    root = pathlib.Path(zettcode.__file__).parent / "broker"
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
