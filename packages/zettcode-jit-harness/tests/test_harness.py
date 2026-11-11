"""The just-in-time harness: off unless asked for, switched between requests, and never half-on."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.events import AgentEventType
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import AssistantMessage, SystemMessage
from zett_agent.model import ModelEvent, ModelResponse, RetryOptions

from plugin_helpers import agent_extensions
from zettcode.config import ModelConfig, ZettCodeConfig, load_config
from zettcode.engine.extensions.harness_switch import HarnessSwitch
from zettcode.jit_harness.extension import SwitchedHarness
from zettcode.plugin_api.commands import CommandResult
from zettcode.sdk.builtins import load_agent_plugins

#: The tools the framework's harness adds to a request.
HARNESS_TOOLS = {"repo_create", "repo_load", "repo_unload", "profile_tools"}


class _Model:
    """A model that answers once and remembers what each request offered it."""

    retry = RetryOptions(max_retries=0)

    def __init__(self) -> None:
        self.requests: list[object] = []

    async def stream(self, request):
        self.requests.append(request)
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content="ok")))


class _Probe(AgentExtension):
    """Records the tools a request has once every other extension has registered its own."""

    priority = 2_000_000

    def __init__(self) -> None:
        self.offered: list[set[str]] = []

    async def on_tool(self, context) -> None:
        self.offered.append(set(context.tools))


async def _turn(agent: Agent, session: str = "s") -> None:
    events = [event async for event in agent.stream("hi", config=AgentRunConfig(session_id=session))]
    assert events[-1].type is AgentEventType.RUN_COMPLETED


async def _agent(tmp_path: Path, switch: HarnessSwitch, model: _Model, probe: _Probe) -> Agent:
    return await Agent.create(
        model,
        config=AgentRunConfig(session_id="s"),
        extensions=[SwitchedHarness(tmp_path / "harness", switch), probe],
    )


def test_a_run_starts_with_the_harness_off_and_the_config_can_start_it_on(tmp_path: Path):
    path = tmp_path / "config.toml"
    body = '[[models]]\nmodel = "a"\ntoken = "t"\n'

    path.write_text(body, encoding="utf-8")
    assert load_config(tmp_path, path=path).jit_harness is False

    path.write_text(body + "\n[harness]\njit = true\n", encoding="utf-8")
    assert load_config(tmp_path, path=path).jit_harness is True

    path.write_text(body + "\n[harness]\njit = 1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="jit"):
        load_config(tmp_path, path=path)


def test_the_switch_costs_nothing_to_hold():
    """It is imported by the runtime on every launch, so it must not pull the framework's harness in with it."""
    import subprocess
    import sys

    code = (
        "import sys; import zettcode.engine.extensions.harness_switch as m; "
        "print('zett_agent.jit_harness' in sys.modules)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)

    assert done.stdout.strip() == "False"


async def test_with_the_switch_off_a_request_has_none_of_the_harness(tmp_path: Path):
    model, probe, switch = _Model(), _Probe(), HarnessSwitch()
    agent = await _agent(tmp_path, switch, model, probe)

    await _turn(agent)

    assert probe.offered[0] & HARNESS_TOOLS == set()
    assert not any(
        isinstance(message, SystemMessage) and "repo_create" in message.content
        for message in model.requests[0].messages
    ), "no guidance about a tool that is not offered"
    assert not (tmp_path / "harness").exists(), "nothing is created on disk for a harness nobody asked for"


async def test_with_the_switch_on_a_request_has_the_four_tools_and_their_guidance(tmp_path: Path):
    model, probe, switch = _Model(), _Probe(), HarnessSwitch(on=True)
    agent = await _agent(tmp_path, switch, model, probe)

    await _turn(agent)

    assert HARNESS_TOOLS <= probe.offered[0]
    offered = {tool.name for tool in model.requests[0].tools}
    assert HARNESS_TOOLS <= offered
    assert any(
        isinstance(message, SystemMessage) and "repo_create" in message.content
        for message in model.requests[0].messages
    )


async def test_the_switch_applies_to_the_next_request_of_a_client_that_was_already_built(tmp_path: Path):
    """The harness switch does not rebuild anything: the same agent offers the tools from its next request."""
    model, probe, switch = _Model(), _Probe(), HarnessSwitch()
    agent = await _agent(tmp_path, switch, model, probe)

    await _turn(agent)
    switch.on = True
    await _turn(agent)
    switch.on = False
    await _turn(agent)

    offered = [bool(seen & HARNESS_TOOLS) for seen in probe.offered]
    assert offered == [False, True, False]


async def test_a_request_that_began_with_the_harness_keeps_it_to_its_end_whatever_the_switch_says(tmp_path: Path):
    """The switch is read once, when the request mounts its tools: no request sees the harness change halfway."""
    harness = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True))

    class Context:
        session_id = "s"

    context = Context()
    harness._engaged.add("s")
    harness._switch.on = False

    assert harness.engaged(context) is True  # type: ignore[arg-type]
    harness._release(context)  # type: ignore[arg-type]
    assert harness.engaged(context) is False  # type: ignore[arg-type]


async def test_the_harness_of_one_session_is_not_engaged_for_another(tmp_path: Path):
    harness = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True))

    class Context:
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id

    harness._engaged.add("a")

    assert harness.engaged(Context("a")) is True  # type: ignore[arg-type]
    assert harness.engaged(Context("b")) is False  # type: ignore[arg-type]


def test_each_session_keeps_its_tools_in_its_own_folder_beside_the_sessions_not_inside_them(tmp_path: Path):
    from zettcode.paths import DEFAULT_HARNESS_DIR

    assert DEFAULT_HARNESS_DIR.name == "harness" and DEFAULT_HARNESS_DIR.parent.name == ".zettcode"
    assert DEFAULT_HARNESS_DIR.parent == DEFAULT_HARNESS_DIR.parent.parent / ".zettcode"

    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        harness_dir=tmp_path / "harness",
        mcp_enabled=False,
    )
    from zettcode.engine.harness_paths import harness_root

    (harness,) = [e for e in agent_extensions(config) if isinstance(e, SwitchedHarness)]

    assert harness.session_directory("abc").parent == harness_root(config)
    assert not harness.session_directory("abc").is_relative_to(tmp_path / "sessions")


def test_a_session_directory_from_before_the_workspace_level_is_moved_under_it(tmp_path: Path):
    from zett_agent.jit_harness.repo import session_directory_name

    from zettcode.engine.harness_paths import harness_root, session_directory

    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        harness_dir=tmp_path / "harness",
        mcp_enabled=False,
    )
    legacy = config.harness_dir / session_directory_name("abc")
    (legacy / "kit").mkdir(parents=True)

    moved = session_directory(config, "abc")

    assert moved.parent == harness_root(config) and (moved / "kit").is_dir()
    assert not legacy.exists()


def test_the_harness_runs_model_code_in_a_child_and_only_sandboxes_it_below_full(tmp_path):
    """A crash in code the model wrote stays out of the window; the sandbox is for the levels that still bound things."""
    from zett_agent.jit_harness import SubprocessToolHost

    from zettcode.engine.permission import Permission, ShellPolicy

    policy = ShellPolicy(Permission.SAFE, workspace=tmp_path)

    policy.level = Permission.ASK
    assert policy.jit_sandbox() is policy.sandbox.boundary, "every level below full hands over the same boundary"
    policy.level = Permission.FULL
    assert policy.jit_sandbox() is None, "at full the reader has given the model their own access"
    assert not policy.sandbox_missing(), "full promises no boundary, so a missing one says nothing"

    # The host itself, through the factory the plugin builds: a child either way, and the boundary the policy names.
    policy.level = Permission.SAFE
    host = _harness_host(tmp_path, policy)
    assert isinstance(host, SubprocessToolHost), "a crash or a hang must not take this process with it"
    if policy.sandbox.available:
        assert host.sandbox is policy.sandbox.boundary, "the child runs in the boundary the shell's safe level uses"
    else:
        assert host.sandbox is None


def test_a_session_whose_boundary_changed_is_really_forgotten(tmp_path):
    """The SDK is the thing that has to let go of the old child, and a request in flight holds it.

    Driving the real ``forget_session`` is the point: a stand-in that cannot raise is what hid the two bugs this
    test was written for — a key the framework had already dropped, and a forget attempted before the release
    (which the framework refuses, leaving the old child running for the rest of the session).
    """
    from zettcode.engine.extensions.harness_switch import HarnessSwitch

    boundaries = ["sandboxed"]
    harness = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True), boundary=lambda: boundaries[0])

    harness._follow_boundary("s1")
    assert harness._built["s1"] == "sandboxed"

    boundaries[0] = "none"
    harness._follow_boundary("s1")
    assert harness._built["s1"] == "none", "the record follows the boundary once the old child is gone"
    with pytest.raises(KeyError):
        harness.forget_session("s1")  # it was never loaded, and the framework no longer holds it


def test_a_boundary_change_waiting_for_the_release_is_retried(tmp_path, monkeypatch):
    """A child cannot be forgotten while the request holds it: the boundary stays unrecorded, so it is tried again."""
    from zettcode.engine.extensions.harness_switch import HarnessSwitch

    boundaries = ["sandboxed"]
    harness = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True), boundary=lambda: boundaries[0])
    harness._follow_boundary("s1")

    attempts: list[str] = []

    def busy(session_id: str) -> None:
        attempts.append(session_id)
        raise RuntimeError("Cannot forget a harness with an active request")

    monkeypatch.setattr(harness, "forget_session", busy)
    boundaries[0] = "none"
    harness._follow_boundary("s1")

    assert harness._built["s1"] == "sandboxed", "not recorded, so the next request tries again"
    assert "s1" in harness._pending


def test_the_release_detaches_before_it_forgets(tmp_path, monkeypatch):
    """The framework detaches in the release: a forget before it always fails, and the fail-open child survives."""
    from zett_agent.jit_harness import JITHarnessExtension

    from zettcode.engine.extensions.harness_switch import HarnessSwitch

    harness = SwitchedHarness(tmp_path / "harness", HarnessSwitch(on=True), boundary=lambda: "none")
    order: list[str] = []

    def release(self, context) -> None:
        order.append("detach")

    monkeypatch.setattr(JITHarnessExtension, "_release", release)
    monkeypatch.setattr(harness, "forget_session", lambda session_id: order.append("forget"))

    class _Context:
        session_id = "s1"

    harness._pending.add("s1")
    harness._release(_Context())

    assert order == ["detach", "forget"], order


def test_a_machine_without_a_sandbox_says_so_once_per_session(tmp_path, monkeypatch):
    """The model's own tools are not a shell command, so the shell's fallbacks do not bound them: say it, once."""
    from zett_agent.events import AgentEventType

    from zettcode.engine.extensions.harness_switch import HarnessSwitch
    from zettcode.engine.extensions.mcp_notice import HARNESS_NOTICE_EVENT_NAME, notice_from, notice_level_from

    emitted: list[object] = []

    class _Context:
        session_id = "s1"

        async def emit(self, event):
            emitted.append(event)

    harness = SwitchedHarness(
        tmp_path / "harness", HarnessSwitch(on=True), boundary=lambda: "none", unbounded=lambda: True
    )

    asyncio.run(harness._say_unbounded(_Context()))
    asyncio.run(harness._say_unbounded(_Context()))

    assert len(emitted) == 1, "once per session, not once per request"
    event = emitted[0]
    assert event.type is AgentEventType.CUSTOM and event.name == HARNESS_NOTICE_EVENT_NAME
    assert notice_level_from(event) == "warn"
    assert "/plugins" in notice_from(event)


def _harness_host(tmp_path, policy):
    """Return the host the plugin's factory builds for one session."""
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        harness_dir=tmp_path / "harness",
        mcp_enabled=False,
    )
    (harness,) = [
        extension for extension in agent_extensions(config, policy=policy) if isinstance(extension, SwitchedHarness)
    ]
    return harness._host_factory()  # type: ignore[misc]


def test_the_default_harness_folder_is_not_inside_the_default_session_store():
    from zettcode.config import ZettCodeConfig as Config
    from zettcode.paths import DEFAULT_HARNESS_DIR, DEFAULT_STORE

    assert DEFAULT_HARNESS_DIR == DEFAULT_STORE.parent / "harness"
    assert not DEFAULT_HARNESS_DIR.is_relative_to(DEFAULT_STORE)
    assert Config.__dataclass_fields__["harness_dir"].default == DEFAULT_HARNESS_DIR


def test_the_plugin_registers_the_harness_even_when_off_so_the_command_can_turn_it_on(tmp_path: Path):
    config = ZettCodeConfig(
        workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "sessions", mcp_enabled=False
    )

    found = [e for e in agent_extensions(config) if isinstance(e, SwitchedHarness)]

    assert len(found) == 1
    assert found[0]._switch.on is False


async def test_the_runtime_turns_the_harness_on_and_off_and_starts_from_the_config(tmp_path: Path, monkeypatch):
    from zettcode.engine import core as runtime_module

    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)

    def runtime(**changes):
        config = ZettCodeConfig(
            workspace=tmp_path,
            models=(ModelConfig(model="m", token="t"),),
            store=tmp_path / "sessions",
            mcp_enabled=False,
            **changes,
        )
        return runtime_module.ZettCodeEngine.preview(config, load_agent_plugins)

    off, on = runtime(), runtime(jit_harness=True)
    assert off.harness.on is False and on.harness.on is True

    assert off.use_harness(True) is True and off.harness.on is True
    assert off.use_harness(False) is False and off.harness.on is False


def test_a_legacy_session_directory_is_merged_when_both_exist(tmp_path: Path):
    from zettcode.engine.harness_paths import move_session

    legacy = tmp_path / "harness"
    root = legacy / "workspace"
    (legacy / "sid" / "kit").mkdir(parents=True)
    (root / "sid" / "new").mkdir(parents=True)

    moved = move_session(legacy, root, "sid")

    assert (moved / "kit").is_dir() and (moved / "new").is_dir()
    assert not (legacy / "sid").exists()


def test_two_workspaces_with_one_name_get_different_folders(tmp_path: Path):
    from zettcode.engine.harness_paths import workspace_directory_name

    first = tmp_path / "a" / "app"
    second = tmp_path / "b" / "app"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    assert workspace_directory_name(first) != workspace_directory_name(second)


def test_a_repository_present_on_both_sides_stays_in_the_legacy_folder(tmp_path: Path):
    from zettcode.engine.harness_paths import move_session

    legacy = tmp_path / "harness"
    root = legacy / "workspace"
    (legacy / "sid" / "kit").mkdir(parents=True)
    (root / "sid" / "kit").mkdir(parents=True)
    (root / "sid" / "kit" / "new.py").write_text("", encoding="utf-8")

    move_session(legacy, root, "sid")

    assert (root / "sid" / "kit" / "new.py").is_file(), "the new copy wins"
    assert (legacy / "sid" / "kit").is_dir(), "the old copy is not thrown away"


# -- /harness and its two words ------------------------------------------------------------------------------------


class _Switch:
    """The bit of the SDK client ``/harness`` reads: the config, the session, the switch and one turn's worth of SDK."""

    def __init__(
        self, config: ZettCodeConfig, *, harness: bool = False, started: bool = True, locked: bool = False
    ) -> None:
        self.config = config
        self.session = type("Session", (), {"id": "mine", "locked": locked})()
        self.sessions = type(
            "Sessions",
            (),
            {
                "list": lambda _self, *, limit=1000: _stored(),
            },
        )()
        self.harness = harness
        self.started = started
        #: What happened, in the order the command made it happen: the switch, the notice it wrote, or the turn.
        self.events: list[str] = []
        self.switched: list[bool] = []

    def use_harness(self, on: bool) -> bool:
        self.switched.append(on)
        self.events.append(f"switch:{bool(on)}")
        self.harness = bool(on)
        return self.harness


async def _stored():
    """The session store the picker reads: the current session and one other with a harness."""
    return [
        type("Info", (), {"id": "mine", "title": "Mine"})(),
        type("Info", (), {"id": "other", "title": "Other"})(),
    ]


class _Shell:
    """The shell a command runs against: the client, the turn it may start, and the page it may close."""

    def __init__(self, client: _Switch) -> None:
        self.client = client
        self.ui = _Ui(client.events)
        self.transcript = self.ui
        self.prompts: list[tuple[str, str | None]] = []
        self.closed = 0
        self.selected: list[str] = []

    async def prompt(self, text: str, *, shown: str | None = None, cache: str | None = None) -> bool:
        self.client.events.append("prompt")
        self.prompts.append((text, shown))
        return self.client.started

    def close_page(self) -> None:
        self.closed += 1

    def select_session(self, session_id: str) -> None:
        self.selected.append(session_id)


class _Ui:
    """The surfaces a command may write to, recording what reached them — and when, next to the turns."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.notices: list[str] = []
        self.messages: list[str] = []
        #: Shared with the fake client, so a notice and a turn are ordered against each other.
        self.events = events if events is not None else []

    def markdown(self, text: str) -> None:
        self.messages.append(text)

    def notice(self, text: str) -> None:
        self.notices.append(text)
        self.events.append("notice")

    def error(self, text: str) -> None: ...

    def notify(self, text: str, *, level: str = "info") -> None: ...


def _configured(tmp_path: Path) -> ZettCodeConfig:
    """Return a config whose harness folder and session store are both under the test's directory."""
    (tmp_path / "work").mkdir(exist_ok=True)
    return ZettCodeConfig(
        workspace=tmp_path / "work",
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        harness_dir=tmp_path / "harness",
        mcp_enabled=False,
    )


def _page(result: CommandResult):
    """Return the page from either a full-screen result or an overlay-wrapped one."""
    widget = result.widget
    return widget.slots[0].widget if hasattr(widget, "slots") else widget


async def _run(argument: str, client: _Switch, choices: object | None = None) -> tuple[CommandResult, _Shell]:
    """Run ``/harness`` with ``argument`` and return what it answered, beside the shell it answered through.

    What the command wrote to the reader's surfaces is on ``shell.ui``, so a test can read a notice as well as a result.
    """
    from zettcode.jit_harness.command import HarnessCommand
    from zettcode.plugin_api.commands import CommandContext

    shell = _Shell(client)
    context = CommandContext(argument=argument, ui=shell.ui, host=shell)  # type: ignore[arg-type]
    command = HarnessCommand()
    command.choices = choices  # type: ignore[assignment]
    return await command.harness(context), shell


async def test_the_command_is_offered_with_the_two_words_it_takes():
    """The menu offers ``gen`` and ``reset`` behind an extra Enter, and the policy for a running request is ``refuse``."""
    from types import SimpleNamespace

    from zettcode.jit_harness.command import HarnessCommand

    class Tui:
        def __init__(self) -> None:
            self.registered: list[SimpleNamespace] = []

        def register_command(self, name, description, handler, *, when_busy="refuse", subcommands=()):
            self.registered.append(
                SimpleNamespace(name=name, handler=handler, when_busy=when_busy, subcommands=tuple(subcommands))
            )

    class Context:
        def __init__(self) -> None:
            self.tui = Tui()

        def find(self, _name, _kind):
            return None

    context = Context()
    HarnessCommand().activate(context)  # type: ignore[arg-type]

    (command,) = context.tui.registered
    assert command.name == "harness"
    assert command.when_busy == "refuse", "gen asks for a turn of its own, so the whole command takes the slot"
    assert [word.name for word in command.subcommands] == ["gen", "reset"]
    assert all(word.needs_more for word in command.subcommands), (
        "a menu Enter on the word must not spend a turn or flip the switch by itself"
    )


async def test_every_word_the_menu_offers_is_one_the_command_runs(tmp_path: Path):
    """A word added to the menu but not to the dispatch would be offered and then answered with the usage."""
    from zettcode.jit_harness.command import SUBCOMMANDS

    for word in SUBCOMMANDS:
        result, _ = await _run(word.name, _Switch(_configured(tmp_path)))
        assert "is not a word" not in result.message, f"the menu offers {word.name} but the command does not run it"


def test_the_page_tabs_to_tools_and_marks_banned_and_active_rows(tmp_path: Path):
    from zettcode.jit_harness.page import HarnessPage, HarnessTarget, TableRow, TableView
    from zettcode.tui import KeyEvent

    target = HarnessTarget("mine", tmp_path / "mine")
    page = HarnessPage(
        state="on",
        directory=tmp_path / "harness",
        views=(
            TableView("Harnesses", ("SESSION", "TITLE", "REPOSITORY", "DESCRIPTION"), []),
            TableView(
                "Tools",
                ("TOOL", "SOURCE", "STATUS", "DESCRIPTION"),
                [
                    TableRow(target, ("bad_tool", "jit/kit", "banned", "not allowed"), danger=True),
                    TableRow(target, ("read", "base", "active", "read a file"), current=True),
                    TableRow(target, ("later", "jit/kit", "available", "not loaded")),
                ],
            ),
        ),
        on_switch=lambda _target: None,
        on_close=lambda: None,
    )

    page.capture_event(KeyEvent(key="tab"), object())  # type: ignore[arg-type]

    assert page.title.startswith("Tools")
    assert [item.danger for item in page.list.items] == [True, False, False]
    assert [item.current for item in page.list.items] == [False, True, False]
    from zettcode.tui import DARK

    parts = page._tab_parts(DARK)
    assert ("[Tools]", DARK.accent) in parts and ("Harnesses", DARK.muted) in parts


def test_tools_from_the_request_and_the_jit_manifest_are_classified(tmp_path: Path):
    from zettcode.jit_harness.command import HarnessCommand

    repository = tmp_path / "kit"
    repository.mkdir()
    (repository / "__init__.py").write_text("", encoding="utf-8")
    (repository / "MANIFEST").write_text(
        'name = "kit"\nversion = "1"\ndescription = "helpers"\ntools = ["read", "delete"]\n',
        encoding="utf-8",
    )
    (repository / "BAN_TOOLS").write_text("delete\n", encoding="utf-8")
    offered = type("Tool", (), {"name": "read", "description": "read a file"})()
    context = type("Context", (), {"tools": (offered,)})()
    runtime = type("Runtime", (), {"context": context})()
    host = type("Host", (), {"agent": type("Agent", (), {"runtime": runtime})()})()

    rows = HarnessCommand._tool_rows(host, "mine", tmp_path)

    assert any(row.cells == ("read", "jit/kit", "active", "helpers") and row.current for row in rows)
    assert not any(row.cells[0] == "read" and row.cells[1] == "request" for row in rows), "no duplicate base row"
    assert any(row.cells[:3] == ("delete", "jit/kit", "banned") and row.danger for row in rows)
    assert all(row.target is None for row in rows), "tool rows are not harness targets"


def test_enter_on_a_tool_or_file_row_keeps_the_page(tmp_path: Path):
    from zettcode.jit_harness.page import HarnessPage, HarnessTarget, TableRow, TableView

    switched: list[HarnessTarget] = []
    target = HarnessTarget("mine", tmp_path / "mine")
    page = HarnessPage(
        state="on",
        directory=tmp_path / "harness",
        views=(
            TableView("Harnesses", ("A", "B", "C", "D"), [TableRow(target, ("mine", "", "", ""))]),
            TableView("Tools", ("A", "B", "C", "D"), [TableRow(None, ("read", "request", "active", ""))]),
            TableView("Files", ("A", "B", "C", "D"), [TableRow(None, ("README.md", "markdown", "1 B", ""))]),
        ),
        on_switch=switched.append,
        on_close=lambda: None,
    )

    page._show(1)
    page.list.activate()
    page._show(2)
    page.list.activate()
    page._show(3)

    assert switched == [] and page.index == 0, "only harness rows act, and Tab wraps"


def test_markdown_files_are_listed_with_their_size(tmp_path: Path):
    from zettcode.jit_harness.command import HarnessCommand

    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "README.md").write_text("hello\n", encoding="utf-8")

    (row,) = HarnessCommand._file_rows(tmp_path)

    assert row.cells[:2] == ("README.md", "hello")
    assert row.cells[2] == f"{(tmp_path / 'notes' / 'README.md').stat().st_size:,} B" and row.cells[3] == "notes"
    assert row.target is None


def test_the_harness_page_lists_sessions_and_switches_to_the_selected_one(tmp_path: Path):
    from zettcode.jit_harness.page import HarnessPage, HarnessTarget, TableRow, TableView

    switched: list[HarnessTarget] = []
    closed: list[int] = []
    mine = HarnessTarget("mine", tmp_path / "mine")
    other = HarnessTarget("other", tmp_path / "other")
    page = HarnessPage(
        state="on",
        directory=tmp_path / "harness",
        views=(
            TableView(
                "Harnesses",
                ("SESSION", "TITLE", "REPOSITORY", "DESCRIPTION"),
                [
                    TableRow(mine, ("mine", "Mine", "kit", "small helpers")),
                    TableRow(other, ("other", "Other", "notes", "project notes")),
                ],
            ),
        ),
        on_switch=switched.append,
        on_close=lambda: closed.append(1),
    )

    assert [item.value for item in page.list.items] == [mine, other]
    assert page.list.current is not None and page.list.current.value == mine, "the current session is selected first"
    page.list.activate()
    assert switched == [mine] and closed == [], "Enter on the current row is the page's own switch"

    page.list.select(1)
    page.list.activate()
    assert switched == [mine, other], "Enter on another row borrows that harness"


async def test_the_panel_lists_every_session_harness_and_borrows_on_enter(tmp_path: Path):
    from zettcode.engine.harness_paths import harness_root
    from zettcode.jit_harness.selection import HarnessChoices

    config = _configured(tmp_path)
    root = harness_root(config)
    for session_id, repository in (("mine", "kit"), ("other", "notes")):
        (root / session_id / repository).mkdir(parents=True)
        (root / session_id / repository / "__init__.py").write_text("", encoding="utf-8")
    client = _Switch(config)
    choices = HarnessChoices()

    result, shell = await _run("", client, choices)
    page = _page(result)
    assert page.list.items[0].value.label == "mine", "the current session is first"
    assert page.list.items[0].current and not page.list.items[1].current
    assert page.list.current is not None and page.list.current.value.label == "mine"
    assert page.list.items[1].value.directory == root / "other"

    page.list.activate()
    assert shell.closed == 1 and choices.target("mine") is None, "the current row closes the panel"

    page.list.select(1)
    page.list.activate()
    assert choices.target("mine") is not None and choices.target("mine").directory == root / "other", (
        "another row borrows that harness"
    )


async def test_the_panel_says_when_the_chosen_folder_is_gone(tmp_path: Path):
    from zettcode.engine.harness_paths import harness_root
    from zettcode.jit_harness.selection import HarnessChoices

    config = _configured(tmp_path)
    other = harness_root(config) / "other"
    (other / "notes").mkdir(parents=True)
    (other / "notes" / "__init__.py").write_text("", encoding="utf-8")
    client = _Switch(config)
    result, shell = await _run("", client, HarnessChoices())
    page = _page(result)
    other.joinpath("notes", "__init__.py").unlink()
    other.joinpath("notes").rmdir()
    other.rmdir()

    page.list.select(
        next(
            index
            for index, item in enumerate(page.list.items)
            if item.value is not None and item.value.directory == other
        )
    )
    page.list.activate()

    assert shell.closed == 1 and any("folder is gone" in notice for notice in shell.ui.notices)


async def test_harness_alone_opens_the_panel_and_changes_nothing(tmp_path: Path):
    from zettcode.jit_harness.page import HarnessPage

    client = _Switch(_configured(tmp_path))

    result, shell = await _run("", client)

    assert isinstance(result.widget, HarnessPage), "the picker takes the whole screen"
    page = _page(result)
    assert [item.value.label for item in page.list.items] == ["mine"], "the current session is always a row"
    assert page.list.current is not None and page.list.current.value.label == "mine"
    assert "No harness yet" in page.list.current.description
    assert result.message == ""
    assert client.switched == [] and shell.prompts == [], "looking at the harness is not touching it"


async def test_the_panel_scans_harnesses_beyond_the_current_workspace(tmp_path: Path):
    config = _configured(tmp_path)
    workspace = config.harness_dir / "other-workspace-1234abcd"
    session = workspace / "someone"
    (session / "kit").mkdir(parents=True)
    (session / "kit" / "__init__.py").write_text("", encoding="utf-8")

    result, _ = await _run("", _Switch(config))
    page = _page(result)
    row = next(item for item in page.list.items if item.value is not None and item.value.directory == session)
    assert row.value.label == "other-workspace-1234abcd/someone"


async def test_a_repository_row_names_its_session_and_title(tmp_path: Path):
    from datetime import datetime, timezone

    from zettcode.engine.harness_paths import harness_root
    from zettcode.engine.storage.metadata import SESSION_METADATA_FILE, SessionMetadata, write_session_metadata

    config = _configured(tmp_path)
    other = harness_root(config) / "other"
    (other / "notes").mkdir(parents=True)
    (other / "notes" / "__init__.py").write_text("", encoding="utf-8")
    stored = config.store / "workspace" / "other"
    stored.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    write_session_metadata(
        stored / SESSION_METADATA_FILE,
        SessionMetadata(session_id="other", created_at=now, updated_at=now, title="Write docs"),
    )

    result, _ = await _run("", _Switch(config))
    page = _page(result)
    row = next(item for item in page.list.items if item.value is not None and item.value.directory == other)
    assert "other" in row.label and "Write docs" in row.label and "notes" in row.description


async def test_the_panel_lists_a_legacy_folder_without_moving_it(tmp_path: Path):
    from zettcode.engine.harness_paths import harness_root

    config = _configured(tmp_path)
    session = config.harness_dir / "other"
    legacy = session / "old"
    (legacy).mkdir(parents=True)
    (legacy / "__init__.py").write_text("", encoding="utf-8")

    result, _ = await _run("", _Switch(config))
    page = _page(result)
    row = next(item for item in page.list.items if item.value is not None and item.value.directory == session)
    assert row.value.label == "other"
    assert legacy.is_dir(), "opening the picker reads the legacy folder"
    assert not (harness_root(config) / "other").exists(), "it does not migrate every session just by being listed"


async def test_a_harness_folder_without_a_stored_session_is_still_listed(tmp_path: Path):
    from zettcode.engine.harness_paths import harness_root

    config = _configured(tmp_path)
    gone = harness_root(config) / "gone"
    (gone / "old").mkdir(parents=True)
    (gone / "old" / "__init__.py").write_text("", encoding="utf-8")
    result, _ = await _run("", _Switch(config))
    page = _page(result)
    row = next(item for item in page.list.items if item.value is not None and item.value.directory == gone)
    assert row.value.directory == gone, "the folder is a harness whether or not its session is in the store"


async def test_the_panel_does_not_list_sessions_through_sessions_list(tmp_path: Path):
    client = _Switch(_configured(tmp_path))

    async def broken(*_args, **_kwargs):
        raise RuntimeError

    client.sessions = type("Sessions", (), {"list": broken})()

    result, _ = await _run("", client)
    assert result.widget is not None, "scanning the harness tree does not depend on a session-store call"


async def test_the_panel_borrows_another_sessions_harness(tmp_path: Path):
    from zettcode.engine.harness_paths import harness_root
    from zettcode.jit_harness.selection import HarnessChoices

    config = _configured(tmp_path)
    session = harness_root(config) / "other"
    other = session / "notes"
    other.mkdir(parents=True)
    (other / "__init__.py").write_text("", encoding="utf-8")
    choices = HarnessChoices()

    result, shell = await _run("", _Switch(config), choices)
    page = _page(result)
    page.list.select(
        next(
            index
            for index, item in enumerate(page.list.items)
            if item.value is not None and item.value.directory == session
        )
    )
    page.list.activate()

    assert choices.target("mine") is not None and choices.target("mine").directory == session
    assert shell.closed == 1, "choosing a harness closes the picker"


async def test_the_current_row_returns_to_the_sessions_own_harness(tmp_path: Path):
    from zettcode.engine.harness_paths import harness_root
    from zettcode.jit_harness.selection import HarnessChoices

    config = _configured(tmp_path)
    other = harness_root(config) / "other"
    other.mkdir(parents=True)
    choices = HarnessChoices()
    choices.select("mine", "other", other)

    result, _ = await _run("", _Switch(config), choices)
    page = _page(result)
    page.list.activate()

    assert choices.target("mine") is None


def test_selecting_the_same_borrowed_harness_twice_keeps_the_host(tmp_path: Path):
    from zettcode.jit_harness.selection import HarnessChoices

    choices = HarnessChoices()
    calls: list[str] = []
    choices.add_listener(calls.append)
    target = tmp_path / "other"

    choices.select("mine", "other", target)
    choices.select("mine", "other", target)

    assert calls == ["mine"], "re-choosing the row already in use does not forget the loaded host"


def test_a_borrowed_harness_replaces_the_sessions_directory(tmp_path: Path):
    from zettcode.jit_harness.extension import SwitchedHarness
    from zettcode.jit_harness.selection import HarnessChoices

    choices = HarnessChoices()
    extension = SwitchedHarness(tmp_path / "root", HarnessSwitch(), choices=choices)
    other = tmp_path / "other"
    choices.select("mine", "other", other)

    assert extension.session_directory("mine") == other
    choices.clear("mine")
    assert extension.session_directory("mine") == tmp_path / "root" / "mine"


async def test_reset_names_the_borrowed_folder(tmp_path: Path):
    from zettcode.jit_harness.selection import HarnessChoices

    config = _configured(tmp_path)
    other = tmp_path / "other"
    (other / "kit").mkdir(parents=True)
    (other / "kit" / "__init__.py").write_text("", encoding="utf-8")
    choices = HarnessChoices()
    choices.select("mine", "other", other)

    result, _ = await _run("reset", _Switch(config, harness=True), choices)

    assert str(other) in result.message and "borrowed" in result.message, "reset names the folder actually in use"


async def test_gen_turns_the_harness_on_first_and_asks_for_one_tool_as_one_turn(tmp_path: Path):
    client = _Switch(_configured(tmp_path))

    result, shell = await _run("gen", client)

    assert client.events == ["switch:True", "prompt"], "the turn mounts the tools, so the switch has to move first"
    (text, shown) = shell.prompts[0]
    assert shown == "/harness gen", "the reader sees the command, not the brief"
    assert "repo_create" in text and "repo_load" in text, (
        "the brief names the tools that build and check the repository"
    )
    assert "Do not change the workspace" in text, "a tool is built in the harness's folder, never in the project"
    assert result.message == "" and result.widget is None, "the turn is the answer"


async def test_gen_says_so_when_no_turn_could_be_started(tmp_path: Path):
    """Nothing else refuses a prompt here, but a turn that did not start is said: the switch stays on, the reader knows."""
    client = _Switch(_configured(tmp_path), started=False)

    result, _ = await _run("gen", client)
    assert client.harness is True, "the switch moved before the turn was refused"
    assert "turn did not start" in result.message and "/harness gen" in result.message
    assert "not sent" not in result.message, "a reader who wrote nothing is not told their nothing went nowhere"

    with_description, _ = await _run("gen fix the  parser", _Switch(_configured(tmp_path), started=False))

    assert "not sent" in with_description.message and "press Up" in with_description.message, (
        "the line never went out, and the message says Up brings it back (test_composer_lock holds the recall)"
    )


async def test_gen_asks_for_the_session_before_it_turns_anything_on(tmp_path: Path):
    """A turn cannot start in a session another process holds, so the switch does not move for one that cannot, and a
    description that went with the draft is said not to have been sent rather than silently dropped."""
    client = _Switch(_configured(tmp_path), locked=True)

    result, shell = await _run("gen", client)
    assert client.switched == [], "no switch for a run that would do nothing"
    assert shell.prompts == []
    assert "another ZettCode process" in result.message
    assert "not sent" not in result.message, "a reader who wrote nothing sent nothing"

    with_description, _ = await _run("gen fix the  parser", _Switch(_configured(tmp_path), locked=True))

    assert "not sent" in with_description.message


async def test_reset_only_switches_back_and_deletes_nothing(tmp_path: Path):
    """`reset` means "no more just-in-time harness": it flips the switch and leaves every file where it is."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)
    (mine / "kit" / "__init__.py").write_text("print(1)\n", encoding="utf-8")
    before = {path.relative_to(mine): path.read_bytes() for path in mine.rglob("*") if path.is_file()}
    client = _Switch(config, harness=True)

    result, _ = await _run("reset", client)

    assert client.harness is False and client.switched == [False], "the switch is the whole of it"
    after = {path.relative_to(mine): path.read_bytes() for path in mine.rglob("*") if path.is_file()}
    assert after == before, "not a byte of the session's tools was touched"
    assert str(mine) in result.message, "the folder is named, so a reader who wants it gone knows what to remove"
    assert "folder this session's tools live in is still there" in result.message, "the folder it kept is reported"
    assert "on Windows close ZettCode first" in result.message, "the child still works in there, and Windows knows it"
    assert "is not there" not in result.message, "the folder it found is not called missing"
    assert "later requests have none of its tools" in result.message, "and what changes is the next request"


async def test_reset_says_when_the_folder_is_not_there(tmp_path: Path):
    """A session with no folder is a folder that is not there — not a claim about what it ever wrote, which this
    command cannot see (`harness_dir` may have moved, or the reader may have deleted it)."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    assert not mine.exists()

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert "there is no folder at" in result.message and "nothing here to remove" in result.message, result.message
    assert "is still there" not in result.message, "nothing is claimed to be there"


async def test_reset_says_when_the_path_is_taken_by_something_that_is_not_a_folder(tmp_path: Path):
    """`is_dir` is false for a file sitting where the folder would be; saying 'no folder there' would be a lie."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    mine.parent.mkdir(parents=True)
    mine.write_text("in the way", encoding="utf-8")

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert "is there but is not a folder" in result.message, result.message
    assert "move it aside first" in result.message, "and what to do about it, since gen cannot write past it"
    assert "there is no folder at" not in result.message
    assert mine.read_text(encoding="utf-8") == "in the way", "and it was left alone"


@pytest.mark.skipif(os.name == "nt", reason="creating a symbolic link needs a privilege on Windows")
async def test_reset_sees_a_dangling_link_where_the_folder_would_be(tmp_path: Path):
    """`exists()` follows the link and answers False, but the name is taken: gen cannot make a folder there either."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    mine.parent.mkdir(parents=True)
    mine.symlink_to(tmp_path / "gone")

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert "is there but is not a folder" in result.message, result.message
    assert "there is no folder at" not in result.message
    assert mine.is_symlink(), "and the link was left alone"


async def test_reset_does_not_ask_for_the_session_to_itself(tmp_path: Path):
    """Flipping this window's own switch takes nothing from another process, so a held session is no reason to refuse."""
    client = _Switch(_configured(tmp_path), harness=True, locked=True)

    result, _ = await _run("reset", client)

    assert client.switched == [False], "the switch moves even when the session is held elsewhere"
    assert "another ZettCode process" not in result.message


async def test_a_word_the_command_does_not_take_lists_the_ones_it_does(tmp_path: Path):
    """``on`` and ``off`` used to be this command's; a reader who still types one is pointed at both switches."""
    client = _Switch(_configured(tmp_path))

    result, shell = await _run("on", client)

    assert "not a word" in result.message
    bullets: list[str] = []
    for line in result.message.split("\n"):
        if line.startswith("- "):
            bullets.append(line)
        elif line.startswith("  ") and bullets:
            bullets[-1] += " " + line.strip()
    assert [bullet.split(" — ")[0] for bullet in bullets] == [
        "- `/harness`",
        "- `/harness gen [description]`",
        "- `/harness reset`",
        "- `/plugins`",
    ], bullets
    assert "told to treat it as a requirement" in bullets[1], "the gen line says what a description is for"
    assert client.switched == [] and shell.prompts == [], "a typo changes nothing"
    assert shell.ui.messages == [], "a usage error is the result's message, not something the command writes"


async def test_reset_takes_nothing_after_it(tmp_path: Path):
    """`gen` takes a description; there is nothing to say about a switch, so a word after `reset` is a usage error."""
    client = _Switch(_configured(tmp_path))

    result, shell = await _run("reset now", client)

    assert "takes nothing after it" in result.message
    assert client.switched == [] and shell.prompts == [], "nothing runs on a usage error"


async def test_gen_passes_what_the_reader_wrote_after_the_word(tmp_path: Path):
    """The rest of the line is the reader's requirement, not the command's advice: it goes in verbatim, and the floor
    is restated after it, because the last paragraph of a message is the one that is acted on."""
    from zettcode.jit_harness.command import GEN_ASKED, GEN_BRIEF, GEN_FLOOR_LAST

    client = _Switch(_configured(tmp_path))

    result, shell = await _run("gen a tool that lists the TODO markers in docs/", client)

    assert client.events == ["switch:True", "prompt"], "the switch still goes first"
    (text, shown) = shell.prompts[0]
    assert text.startswith(GEN_BRIEF) and GEN_ASKED in text, "the brief is the base, the reader's words follow it"
    assert "a tool that lists the TODO markers in docs/" in text, "verbatim"
    assert text.index(GEN_ASKED) < text.index("TODO markers"), "nothing of the brief can be read as the newer word"
    assert text.rstrip().endswith(GEN_FLOOR_LAST.strip()), "and the floor is the last thing said"
    assert shown == "/harness gen a tool that lists the TODO markers in docs/"
    assert result.message == "" and result.widget is None, "the turn is the answer"


async def test_gen_without_a_description_reads_the_brief_alone(tmp_path: Path):
    """The one-word command is what it was: the default brief, and `/harness gen` in the transcript."""
    from zettcode.jit_harness.command import GEN_BRIEF

    client = _Switch(_configured(tmp_path))

    _, shell = await _run("gen", client)

    assert shell.prompts == [(GEN_BRIEF, "/harness gen")]


async def test_a_description_of_only_whitespace_is_no_description(tmp_path: Path):
    from zettcode.jit_harness.command import GEN_BRIEF

    client = _Switch(_configured(tmp_path))

    _, shell = await _run("gen \t  ", client)

    assert shell.prompts == [(GEN_BRIEF, "/harness gen")], "spaces after the word ask for nothing in particular"


async def test_a_chinese_description_with_quotes_and_a_line_break_arrives_verbatim(tmp_path: Path):
    """The reader's own words are not re-tokenised, so quotes, spacing and a pasted line break all survive."""
    from zettcode.jit_harness.command import GEN_BRIEF

    asked = '修复  "解析器" 的空指针:\n只读,\t不要联网，也不要写  docs/'
    client = _Switch(_configured(tmp_path))

    _, shell = await _run(f"gen  {asked}", client)

    (text, shown) = shell.prompts[0]
    assert asked in text, text[-400:]
    assert text.startswith(GEN_BRIEF)
    assert shown == '/harness gen 修复  "解析器" 的空指针: 只读, 不要联网，也不要写  docs/', (
        "the row is one line, and the reader's own spacing is still theirs"
    )
    assert "\t" not in shown and "\n" not in shown, "a control character would be drawn into the row"


async def test_a_description_too_long_to_send_is_cut_and_says_so(tmp_path: Path):
    from zettcode.jit_harness.command import GEN_ASKED, GEN_BRIEF, GEN_FLOOR_LAST, MAX_DESCRIPTION, MAX_SHOWN
    from zettcode.tui.render import display_width

    asked = "x" * (MAX_DESCRIPTION + 500)
    client = _Switch(_configured(tmp_path))

    _, shell = await _run(f"gen {asked}", client)

    (text, shown) = shell.prompts[0]
    assert asked[:MAX_DESCRIPTION] in text, "everything up to the limit is sent"
    assert asked[: MAX_DESCRIPTION + 1] not in text, "and not one character more"
    assert f"cut at {MAX_DESCRIPTION} characters" in text, "a cut is said, not left looking like a short request"
    allowed = len(GEN_BRIEF) + len(GEN_ASKED) + len(GEN_FLOOR_LAST) + MAX_DESCRIPTION + 120
    assert len(text) <= allowed, "the brief does not grow with a paste"
    assert display_width(shown) == MAX_SHOWN and shown.endswith("\u2026"), "the transcript row stays one row wide"


async def test_a_description_exactly_at_the_limit_is_sent_whole(tmp_path: Path):
    """`>` is the boundary A16 promises: at the limit nothing is cut, one character past it is."""
    from zettcode.jit_harness.command import MAX_DESCRIPTION

    asked = "x" * MAX_DESCRIPTION
    client = _Switch(_configured(tmp_path))

    _, shell = await _run(f"gen {asked}", client)

    (text, _) = shell.prompts[0]
    assert shell.ui.notices == [], "a description that fits is not said to be cut"
    assert "cut at" not in text, "and the brief does not carry a cut marker"
    assert asked in text, "all of it was sent"


async def test_the_row_is_clamped_by_columns_so_a_wide_description_fits(tmp_path: Path):
    """120 Chinese characters are 240 columns: the budget is the row's width, not the string's length."""
    from zettcode.jit_harness.command import MAX_SHOWN
    from zettcode.tui.render import display_width

    asked = "修" * 200
    client = _Switch(_configured(tmp_path))

    _, shell = await _run(f"gen {asked}", client)

    (_, shown) = shell.prompts[0]
    assert shown.endswith("\u2026"), "a cut row says it was cut"
    assert display_width(shown) <= MAX_SHOWN, "the row fits the budget in columns"
    assert len(shown) < MAX_SHOWN, "so it holds fewer characters than the budget: this is what columns means"


async def test_a_description_that_was_cut_says_so_to_the_reader_before_the_turn(tmp_path: Path):
    """The model is told where its brief was cut, and the reader is told before the turn goes out, not after."""
    from zettcode.jit_harness.command import MAX_DESCRIPTION

    result, shell = await _run(f"gen {'x' * (MAX_DESCRIPTION + 500)}", _Switch(_configured(tmp_path)))
    (notice,) = shell.ui.notices
    assert f"cut at {MAX_DESCRIPTION} characters" in notice and "500 characters were not sent" in notice
    assert result.message == "", "the turn is still the answer"
    assert shell.client.events == ["switch:True", "notice", "prompt"], (
        "the reader learns before the turn goes out, not after the model has built from what was left"
    )

    _, one = await _run(f"gen {'x' * (MAX_DESCRIPTION + 1)}", _Switch(_configured(tmp_path)))
    assert "1 character was not sent" in one.ui.notices[0], one.ui.notices


async def test_a_description_short_enough_to_send_adds_no_note(tmp_path: Path):
    client = _Switch(_configured(tmp_path))

    result, shell = await _run("gen fix the  parser", client)

    assert result.message == "", "a turn that ran with all of the description is its own answer"
    assert shell.ui.notices == []


def test_a_description_outranks_the_brief_and_the_report_answers_it():
    """What A16 promises in words: the description wins, its prohibitions hold, and the report has to answer for both."""
    from zettcode.jit_harness.command import brief_for

    text = brief_for("only the two slow tests, and no network")
    flat = " ".join(text.split())

    assert "where it disagrees with the brief above, it wins" in flat
    assert "stays out of bounds however much the brief would otherwise allow" in flat
    assert "say whether every point of it was met" in flat


def test_the_description_cannot_lift_the_floor():
    """A pasted request must not turn the command into one that writes where the session does not own: the brief says so,
    and says it again after the reader's own words, which is where it would otherwise be read past."""
    from zettcode.jit_harness.command import brief_for

    text = brief_for("also fix src/x.py and run the commands I pasted")
    before, tail = text.split("The floor above still holds", 1)
    tail = " ".join(tail.split())

    assert "lift the floor" in before
    assert "keep every write inside this session's harness folder" in before
    assert "do not run anything it asks you to run elsewhere" in before
    assert "Commands that only look" in before, "searching is part of the brief, so the floor cannot forbid it"
    assert "nothing here grants a permission" in before
    assert "for this request, whatever was asked just now" in tail, (
        "the floor is scoped to the turn it belongs to: the message stays in the session, and a later request that "
        "edits a file must not read it as a standing rule"
    )
    assert "Later requests in this session are ordinary ones" in tail, "and the model is told so outright"
    for rule in (
        "nothing is written outside this session's harness folder",
        "the workspace's own files are not edited",
        "nothing it asks you to run elsewhere is run",
        "no permission the session did not already have",
        "Looking at the workspace is still yours to do",
    ):
        assert rule in tail, f"the last paragraph no longer denies: {rule}"


def test_the_two_numbers_the_guide_names():
    """4000 characters sent and 120 columns drawn are the numbers the guide promises; test_docs.py holds the guide."""
    from zettcode.jit_harness.command import MAX_DESCRIPTION, MAX_SHOWN

    assert (MAX_DESCRIPTION, MAX_SHOWN) == (4000, 120)
