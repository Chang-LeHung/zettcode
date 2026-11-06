"""Shared test isolation for the suite."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

import pytest

# The suite runs in a home directory of its own, set before anything from zettcode is imported.
# Every default the program has — the config file, the session store, the release check's state,
# the tokenizer's cache, the log, the theme — is `Path.home() / ".zettcode" / ...` evaluated when
# its module is imported, so this has to come first: patching a variable afterwards does not move
# a default that was already computed, and a test that builds a config without naming a store
# (`resolve_config(["-w", tmp_path])` does exactly that) would write into the developer's real
# `~/.zettcode`. That is what happened: every run left two workspace folders behind, and
# thousands piled up in a real store, each with a metadata file listing one throwaway session.
_HOME = tempfile.mkdtemp(prefix="zettcode-test-home-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME  # what `Path.home()` reads on Windows
atexit.register(shutil.rmtree, _HOME, ignore_errors=True)

#: The plugins the program is made of, as their distributions publish them under `zettcode.terminal`, sorted by name
#: the way the loader sorts them. Each distribution's `pyproject.toml` says the same; `test_structure.py` compares.
PROGRAM_PARTS = (
    ("commands", "zettcode.commands.plugin:CommandsPlugin"),
    ("pets", "zettcode.pets.plugin:PetsPlugin"),
    ("presenters", "zettcode.presenters.plugin:PresentersPlugin"),
    ("themes", "zettcode.app.plugins.builtins:BuiltinThemes"),
)

#: The plugins that compose the agent, as the SDK publishes them under `zettcode.agent`, sorted by name. The loader
#: activates them by the rank `zettcode.sdk.builtins` gives them; `test_structure.py` compares this with the
#: distribution's `pyproject.toml`.
AGENT_PARTS = tuple(
    sorted(
        (name, f"zettcode.sdk.builtins:{cls}")
        for name, cls in (
            ("coding", "CodingTools"),
            ("capabilities", "Capabilities"),
            ("subagents", "Subagents"),
            ("shell-permission", "ShellPermission"),
            ("session-log", "SessionLog"),
            ("usage-tracking", "UsageTracking"),
            ("context-tracking", "ContextTracking"),
            ("side-questions", "SideQuestionBoundary"),
            ("self-compaction", "SelfCompaction"),
            ("compaction", "Compaction"),
        )
    )
)


#: The parts of the agent that live in distributions of their own (`zettcode-skills`, `zettcode-mcp`, ...), published
#: under the same `zettcode.agent` group, sorted by name. `test_structure.py` compares this with their `pyproject.toml`
#: files.
EXTERNAL_AGENT_PARTS = (
    ("ask-user", "zettcode.ask_user.plugin:AskUser"),
    ("files", "zettcode.files.plugin:FileResources"),
    ("harness", "zettcode.jit_harness.plugin:Harness"),
    ("long-output", "zettcode.truncation.plugin:LongOutput"),
    ("mcp", "zettcode.mcp.plugin:McpTools"),
    ("messaging", "zettcode.messaging.plugin:Messaging"),
    ("project-instructions", "zettcode.instructions.plugin:ProjectInstructions"),
    ("skill-tool", "zettcode.skills.plugin:SkillTool"),
    ("skills", "zettcode.skills.plugin:SkillResources"),
    ("todos", "zettcode.todos.plugin:TodoPlan"),
    ("tool-guidelines", "zettcode.guidance.plugin:ToolGuidance"),
    ("tool-output", "zettcode.tool_output.plugin:ToolOutput"),
)


@pytest.fixture(autouse=True)
def _no_broker_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a test run from starting the background session broker.

    A shell that starts connects to the broker and starts one when none answers, and a broker is a
    process that outlives whoever started it. No test of the shell wants one: the tests of the broker
    itself start theirs explicitly, on a directory of their own, and the tests of the shell hand it a
    fake.
    """
    from zettcode.broker import finder

    monkeypatch.setattr(finder, "spawn_broker", lambda directory: None)


@pytest.fixture(autouse=True)
def _no_installed_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic: an installed plugin must not join a test run.

    ``ZettCodeEngine.preview`` loads every ``zettcode.plugins`` entry point the
    environment advertises, which would make tests depend on whatever the
    developer happens to have installed. The plugin tests inject their own entry
    points, so discovery is only stubbed here, never removed. The plugins the program itself is made of
    (``PROGRAM_PARTS``) are still found, as a literal list and not as whatever this environment advertises: without
    them there is nothing to draw with, and which of them are installed must not change what a test sees.
    """
    from zettcode.engine.plugins import loader

    points = tuple(_point(name, value, dist) for name, value, dist in _part_points())
    monkeypatch.setattr(loader, "installed_entry_points", lambda: points)


class _Point:
    """An entry point as the loader reads one: a name, the target it loads, and the distribution it came from.

    The distribution is what says which role a plugin has (``loader.program_distributions``), so a stand-in that
    names one is the part it claims to be.
    """

    group = "zettcode.plugin"

    class dist:  # noqa: N801 - the slice of importlib.metadata.Distribution the loader reads
        name = ""

    def __init__(self, name: str, value: str, distribution: str) -> None:
        self.name = name
        self.value = value

        self.dist = type("Dist", (), {"name": distribution})()

    def load(self) -> object:
        module, _, attribute = self.value.partition(":")
        from importlib import import_module

        return getattr(import_module(module), attribute)


def _point(name: str, value: str, distribution: str) -> _Point:
    """Return the stand-in an entry point of ``distribution`` is, in a test."""
    return _Point(name, value, distribution)


def _part_points() -> list[tuple[str, str, str]]:
    """Every part the program publishes, as (entry-point name, target, distribution), in load order."""
    agent = [(name, value, _OWNER[name]) for name, value in sorted((*AGENT_PARTS, *EXTERNAL_AGENT_PARTS))]
    terminal = [(name, value, _OWNER[name]) for name, value in sorted(PROGRAM_PARTS)]
    return [*agent, *terminal]


#: The distribution that publishes each part, as the suite's literals name them (`test_structure.py` checks this
#: against the `pyproject.toml` files).
_OWNER = {
    "coding": "zettcode-sdk",
    "capabilities": "zettcode-sdk",
    "subagents": "zettcode-sdk",
    "shell-permission": "zettcode-sdk",
    "session-log": "zettcode-sdk",
    "usage-tracking": "zettcode-sdk",
    "context-tracking": "zettcode-sdk",
    "side-questions": "zettcode-sdk",
    "self-compaction": "zettcode-sdk",
    "compaction": "zettcode-sdk",
    "skills": "zettcode-skills",
    "skill-tool": "zettcode-skills",
    "ask-user": "zettcode-ask-user",
    "files": "zettcode-files",
    "harness": "zettcode-jit-harness",
    "long-output": "zettcode-truncation",
    "mcp": "zettcode-mcp",
    "messaging": "zettcode-messaging",
    "project-instructions": "zettcode-instructions",
    "todos": "zettcode-todos",
    "tool-guidelines": "zettcode-guidance",
    "tool-output": "zettcode-tool-output",
    "commands": "zettcode-commands",
    "pets": "zettcode-pets",
    "presenters": "zettcode-presenters",
    "themes": "zettcode-app",
}


@pytest.fixture(autouse=True)
def _a_local_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test as if on the reader's own machine, outside tmux.

    Where a copy goes — and what the shell says about it — depends on whether the process was
    started over ``ssh``, and an escape sequence is wrapped when it is inside tmux. A developer
    who runs the suite over ssh, or in a tmux window, would otherwise see the wording and the
    route change under their feet. The tests that are *about* those say so with their own
    ``setenv``.
    """
    from zettcode.tui.clipboard import CLIPBOARD_ENV, SSH_VARIABLES

    for name in (*SSH_VARIABLES, "TMUX", CLIPBOARD_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_sdk_client_outlives_its_test():
    """Fail a test that leaves an SDK client open, and put the process back where it was.

    A client changes the process's working directory and registers its workspace, so one that is not closed would
    make every later test that makes a client fail for a reason that has nothing to do with it.
    """
    import os
    import sys

    before = os.getcwd()
    yield
    module = sys.modules.get("zettcode.sdk.client")
    if module is None:
        return
    leaked = [client for client in list(module._OPEN) if not client._closed]
    for client in leaked:
        client._dispose()
    os.chdir(before)
    assert not leaked, f"a test left {len(leaked)} SDK client(s) open: {leaked}"


@pytest.fixture(autouse=True)
def _offline_tokenizers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every tokenizer in the suite off the network.

    Starting a runtime starts two background loads — the ``/context`` report's encoding and the one
    compaction counts with — and a vocabulary that is not in the cache is a download. A test that
    wants an encoder passes its own ``loader``; one that does not gets an answer as if the machine
    were offline, which both counters take as "estimate", exactly as a first run with no network
    would.
    """
    from zettcode.engine.extensions import context

    def offline(encoding: str):
        raise OSError(f"the {encoding} vocabulary is not fetched in tests")

    monkeypatch.setattr(context, "_tiktoken_encoder", offline)


@pytest.fixture(autouse=True)
def _keep_the_collector_as_it_was() -> None:
    """Give back the collector as it was: its thresholds, whether it is on, and what is frozen.

    ``cli.main`` raises the young-generation threshold; a test that calls it must not leave that
    behind for every test after it.
    """
    import gc

    before = gc.get_threshold()
    was_on = gc.isenabled()
    yield
    gc.set_threshold(*before)
    # The shell switches the collector with its busy state and freezes the heap once it has warmed; a
    # test that ran a shell must not leave the next one with the collector off or the heap frozen.
    (gc.enable if was_on else gc.disable)()
    gc.unfreeze()
