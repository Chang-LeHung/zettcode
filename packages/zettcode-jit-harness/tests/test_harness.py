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
        self.harness = harness
        self.started = started
        #: What happened, in the order the command made it happen: the switch or the turn it asked for.
        self.events: list[str] = []
        self.switched: list[bool] = []

    def use_harness(self, on: bool) -> bool:
        self.switched.append(on)
        self.events.append(f"switch:{bool(on)}")
        self.harness = bool(on)
        return self.harness


class _Shell:
    """The shell a command runs against: the client, the turn it may start, and the page it may close."""

    def __init__(self, client: _Switch) -> None:
        self.client = client
        self.prompts: list[tuple[str, str | None]] = []
        self.closed = 0

    async def prompt(self, text: str, *, shown: str | None = None, cache: str | None = None) -> bool:
        self.client.events.append("prompt")
        self.prompts.append((text, shown))
        return self.client.started

    def close_page(self) -> None:
        self.closed += 1


class _Ui:
    """The surfaces a command may write to; ``/harness`` answers in its result instead."""

    def markdown(self, text: str) -> None: ...

    def notice(self, text: str) -> None: ...

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


async def _run(argument: str, client: _Switch, *, release: object = None) -> tuple[CommandResult, _Shell]:
    """Run ``/harness`` with ``argument`` and return what it answered, beside the shell it answered through."""
    from zettcode.jit_harness.command import HarnessCommand
    from zettcode.plugin_api.commands import CommandContext

    shell = _Shell(client)
    context = CommandContext(argument=argument, ui=_Ui(), host=shell)  # type: ignore[arg-type]
    command = HarnessCommand() if release is None else HarnessCommand(release=release)  # type: ignore[arg-type]
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

    context = Context()
    HarnessCommand().activate(context)  # type: ignore[arg-type]

    (command,) = context.tui.registered
    assert command.name == "harness"
    assert command.when_busy == "refuse", "gen asks for a turn, and reset deletes what a running request has loaded"
    assert [word.name for word in command.subcommands] == ["gen", "reset"]
    assert all(word.needs_more for word in command.subcommands), (
        "a menu Enter on the word must not spend a turn or delete a folder by itself"
    )


async def test_harness_alone_opens_the_panel_and_changes_nothing(tmp_path: Path):
    client = _Switch(_configured(tmp_path))

    result, shell = await _run("", client)

    assert result.widget is not None, "no argument is still the page"
    assert result.message == ""
    assert client.switched == [] and shell.prompts == [], "looking at the harness is not touching it"


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


async def test_reset_leaves_the_folder_alone_while_another_process_holds_the_session(tmp_path: Path):
    """`when_busy` sees this process's requests, not another window's: the lock is what says the folder is in use."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)
    client = _Switch(config, harness=True, locked=True)

    result, _ = await _run("reset", client)

    assert (mine / "kit").is_dir(), "another process's harness is loaded from there"
    assert client.switched == [], "not even the switch is touched"
    assert "another ZettCode process" in result.message


async def test_gen_says_so_when_no_turn_could_be_started(tmp_path: Path):
    """Nothing else refuses a prompt here, but a turn that did not start is said: the switch stays on, the reader knows."""
    client = _Switch(_configured(tmp_path), started=False)

    result, _ = await _run("gen", client)
    assert client.harness is True, "the switch moved before the turn was refused"
    assert "turn did not start" in result.message and "/harness gen" in result.message
    assert "not kept" not in result.message, "a reader who wrote nothing is not told their nothing was lost"

    with_description, _ = await _run("gen fix the  parser", _Switch(_configured(tmp_path), started=False))

    assert "not kept" in with_description.message, "a description is gone with the refusal, and that is said"


async def test_gen_asks_for_the_session_before_it_turns_anything_on(tmp_path: Path):
    """A turn cannot start in a session another process holds, so the switch does not move for one that cannot, and a
    description that went with the draft is said to be gone rather than silently lost."""
    client = _Switch(_configured(tmp_path), locked=True)

    result, shell = await _run("gen", client)
    assert client.switched == [], "no switch for a run that would do nothing"
    assert shell.prompts == []
    assert "another ZettCode process" in result.message
    assert "not kept" not in result.message, "a reader who wrote nothing lost nothing"

    with_description, _ = await _run("gen fix the  parser", _Switch(_configured(tmp_path), locked=True))

    assert "not kept" in with_description.message


async def test_reset_turns_the_harness_off_and_deletes_only_this_sessions_folder(tmp_path: Path):
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    (config.workspace / "main.py").write_text("print(1)", encoding="utf-8")
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)
    (mine / "kit" / "__init__.py").write_text("", encoding="utf-8")
    (mine / "scratch").mkdir()
    theirs = session_directory(config, "theirs")
    (theirs / "tool").mkdir(parents=True)

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert not mine.exists(), "this session's folder is gone, not merely the repositories in it"
    assert (theirs / "tool").is_dir(), "another session's tools are not this command's"
    assert (config.workspace / "main.py").read_text(encoding="utf-8") == "print(1)", "the workspace is never touched"
    assert "`kit`" in result.message, "the report names what it dropped"
    assert "nothing in the workspace was touched" in result.message


async def test_reset_reports_the_switch_even_when_there_was_nothing_to_delete(tmp_path: Path):
    client = _Switch(_configured(tmp_path), harness=True)

    result, _ = await _run("reset", client)

    assert client.harness is False and client.switched == [False]
    assert "nothing to delete" in result.message


async def test_reset_deletes_nothing_that_is_not_inside_the_harness_root(tmp_path: Path, monkeypatch):
    """A session folder that resolves elsewhere is reported, not removed: the check is what makes the delete safe."""
    from zettcode.jit_harness import command as command_module

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(command_module, "session_directory", lambda config, session_id: elsewhere)
    client = _Switch(_configured(tmp_path), harness=True)

    result, _ = await _run("reset", client)

    assert (elsewhere / "keep.txt").is_file(), "nothing outside the harness folder is deleted, however it got there"
    assert client.harness is False, "the switch still goes off"
    assert "left alone" in result.message and str(elsewhere) in result.message


@pytest.mark.skipif(os.name == "nt", reason="creating a symbolic link needs a privilege on Windows")
async def test_reset_reports_a_session_folder_that_is_itself_a_link_instead_of_failing(tmp_path: Path):
    """The folder a link points at is not this session's storage: it is named, not deleted, and the switch still goes off.

    A link *inside* the folder is a different matter and is safe by construction — ``rmtree`` unlinks an entry it
    finds and never descends into one — so this is the case the resolved check is for.
    """
    from zettcode.engine.harness_paths import harness_root, session_directory

    config = _configured(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x", encoding="utf-8")
    root = harness_root(config)
    root.mkdir(parents=True)
    (root / "mine").symlink_to(outside, target_is_directory=True)
    linked = session_directory(config, "mine")
    assert linked.resolve() == outside.resolve()
    client = _Switch(config, harness=True)

    result, _ = await _run("reset", client)

    assert (outside / "keep.txt").is_file(), "what the link points at is not this session's to delete"
    assert linked.is_symlink(), "the link itself is left in place"
    assert "left alone" in result.message and str(linked) in result.message
    assert client.harness is False


@pytest.mark.skipif(os.name == "nt", reason="creating a symbolic link needs a privilege on Windows")
async def test_reset_leaves_a_link_that_points_inside_the_harness_folder_alone(tmp_path: Path):
    """Inside the root or outside it, a link is not a folder to delete: `rmtree` refuses both, the second wordlessly."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    other = session_directory(config, "other")
    (other / "kit").mkdir(parents=True)
    linked = session_directory(config, "mine")
    linked.symlink_to(other, target_is_directory=True)

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert (other / "kit").is_dir(), "the target is another session's folder"
    assert linked.is_symlink(), "the link is left where it is"
    assert "symbolic link" in result.message and "left alone" in result.message


@pytest.mark.skipif(os.name == "nt", reason="creating a symbolic link needs a privilege on Windows")
async def test_reset_deletes_normally_when_the_harness_folder_itself_is_a_link(tmp_path: Path):
    """A `harness_dir` that is a link *is* the harness folder — resolved on both sides — so its session folder goes."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    real = tmp_path / "elsewhere"
    real.mkdir()
    (tmp_path / "harness").symlink_to(real, target_is_directory=True)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert not mine.exists(), "the folder the harness keeps goes, wherever `harness_dir` points"
    assert "gone with their folder" in result.message


async def test_reset_asks_for_the_session_before_it_names_the_folder(tmp_path: Path):
    """Naming the folder can *move* a pre-workspace one into place, which is a write: a refusal must come first."""
    from zett_agent.jit_harness.repo import session_directory_name

    config = _configured(tmp_path)
    legacy = config.harness_dir / session_directory_name("mine")
    (legacy / "kit").mkdir(parents=True)

    result, _ = await _run("reset", _Switch(config, harness=True, locked=True))

    assert (legacy / "kit").is_dir(), "the legacy folder is where it was: nothing was moved by a command that refused"
    assert "another ZettCode process" in result.message


async def test_reset_still_deletes_when_a_manifest_cannot_be_read(tmp_path: Path, monkeypatch):
    """Reporting what is about to go must never be the reason it does not go: an unreadable file is one row."""
    import zett_agent.jit_harness

    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)
    (mine / "kit" / "__init__.py").write_text("", encoding="utf-8")

    def unreadable(path):
        raise OSError("Permission denied")

    monkeypatch.setattr(zett_agent.jit_harness, "inspect_repository", unreadable)

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert not mine.exists(), "the delete is not held up by a file it could not describe"
    assert "`kit`" in result.message, "the row that could not be read still names the repository"


@pytest.mark.skipif(os.name == "nt", reason="creating a symbolic link needs a privilege on Windows")
async def test_reset_unlinks_a_link_inside_the_folder_without_following_it(tmp_path: Path):
    """`rmtree` removes an entry that is a link and never descends into it, so nothing outside the folder goes."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)
    (mine / "kit" / "__init__.py").write_text("", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("x", encoding="utf-8")
    (mine / "escape").symlink_to(outside, target_is_directory=True)

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert (outside / "keep.txt").is_file(), "the link's target is outside the folder and stays"
    assert not mine.exists(), "the folder goes, link and all"
    assert "`kit`" in result.message


async def test_reset_closes_the_sessions_harness_before_the_folder_goes(tmp_path: Path):
    """The folder is the child's working directory, and Windows will not remove one a live process sits in."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)
    closed: list[str] = []

    def release(session_id: str) -> bool:
        closed.append(session_id)
        assert mine.is_dir(), "the child is closed while there is still a folder to work in"
        return True

    result, _ = await _run("reset", _Switch(config, harness=True), release=release)

    assert closed == ["mine"], "this session's child, once"
    assert not mine.exists() and "gone with their folder" in result.message


async def test_reset_deletes_nothing_when_the_harness_could_not_be_closed(tmp_path: Path):
    """Unreachable while the shell refuses a busy command, and said rather than assumed."""
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)

    result, _ = await _run("reset", _Switch(config, harness=True), release=lambda session_id: False)

    assert mine.is_dir(), "a folder a request is still working in is not removed under it"
    assert "still loaded by a request" in result.message


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


async def test_reset_takes_nothing_after_it(tmp_path: Path):
    """`gen` takes a description; there is nothing to say about a delete, so a word after `reset` is a usage error."""
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

    asked = "x" * (MAX_DESCRIPTION + 500)
    client = _Switch(_configured(tmp_path))

    _, shell = await _run(f"gen {asked}", client)

    (text, shown) = shell.prompts[0]
    assert asked[:MAX_DESCRIPTION] in text, "everything up to the limit is sent"
    assert asked[: MAX_DESCRIPTION + 1] not in text, "and not one character more"
    assert f"cut at {MAX_DESCRIPTION} characters" in text, "a cut is said, not left looking like a short request"
    allowed = len(GEN_BRIEF) + len(GEN_ASKED) + len(GEN_FLOOR_LAST) + MAX_DESCRIPTION + 120
    assert len(text) <= allowed, "the brief does not grow with a paste"
    assert len(shown) == MAX_SHOWN and shown.endswith("\u2026"), "the transcript row stays a row"


async def test_the_plugin_hands_the_command_the_harness_it_built(tmp_path: Path, monkeypatch):
    """The delete closes this process's own child through the extension the plugin built: nothing else can reach it."""
    from zettcode.engine.harness_paths import session_directory
    from zettcode.engine.plugins.state import AgentBuild
    from zettcode.plugin_api.commands import CommandContext

    config = _configured(tmp_path)
    built = _plugin_registrations(config)
    extension = built["factory"](AgentBuild(model=object()))  # type: ignore[operator]
    closed: list[str] = []
    monkeypatch.setattr(extension, "forget_session", lambda session_id: closed.append(session_id))

    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)
    command = built["command"]
    await command(CommandContext(argument="reset", ui=_Ui(), host=_Shell(_Switch(config, harness=True))))  # type: ignore[operator]

    assert closed == ["mine"], "the command closed the extension the plugin built, for this session"
    assert not mine.exists()


async def test_reset_deletes_with_nothing_built_yet(tmp_path: Path):
    """A runtime with no model never calls the factory, so there is no child to close — and the delete still works."""
    from zettcode.engine.harness_paths import session_directory
    from zettcode.plugin_api.commands import CommandContext

    config = _configured(tmp_path)
    built = _plugin_registrations(config)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)

    command = built["command"]
    await command(CommandContext(argument="reset", ui=_Ui(), host=_Shell(_Switch(config, harness=True))))  # type: ignore[operator]

    assert not mine.exists(), "an empty handle is not an IndexError"


async def test_reset_names_a_pre_workspace_copy_it_cannot_drop(tmp_path: Path, monkeypatch):
    """The move merges what it can and leaves the rest, and the next request folds it back: the answer says so."""
    from zett_agent.jit_harness.repo import session_directory_name

    from zettcode.engine.harness_paths import harness_root
    from zettcode.jit_harness import command as command_module

    config = _configured(tmp_path)
    legacy = config.harness_dir / session_directory_name("mine")
    (legacy / "kit").mkdir(parents=True)
    (legacy / "kit" / "__init__.py").write_text("", encoding="utf-8")
    mine = harness_root(config) / session_directory_name("mine")
    (mine / "new").mkdir(parents=True)
    monkeypatch.setattr(command_module, "session_directory", lambda config, session_id: mine)

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert not mine.exists(), "the folder it did delete is gone"
    assert (legacy / "kit").is_dir(), "the copy it could not take stays where it is"
    assert str(legacy) in result.message and "merges it back in" in result.message


async def test_reset_says_a_folder_that_held_nothing_held_no_repository(tmp_path: Path):
    from zettcode.engine.harness_paths import session_directory

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    mine.mkdir(parents=True)

    result, _ = await _run("reset", _Switch(config, harness=True))

    assert not mine.exists()
    assert "no repository in it" in result.message


async def test_reset_says_so_when_the_folder_will_not_go(tmp_path: Path, monkeypatch):
    """The one real failure left — a permission, a file where the folder was — with the switch off and nothing claimed."""
    from zettcode.engine.harness_paths import session_directory
    from zettcode.jit_harness import command as command_module

    config = _configured(tmp_path)
    mine = session_directory(config, "mine")
    (mine / "kit").mkdir(parents=True)

    def refused(path, *args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(command_module.shutil, "rmtree", refused)
    client = _Switch(config, harness=True)

    result, _ = await _run("reset", client)

    assert mine.is_dir(), "nothing was deleted, so nothing is claimed to be"
    assert client.harness is False, "the switch is off whatever the delete did"
    assert "could not be deleted" in result.message and "gone" not in result.message
    assert "/harness reset" in result.message, "and what to do about it"


def _plugin_registrations(config: ZettCodeConfig) -> dict[str, object]:
    """Activate the real plugin against a stand-in container and return what it registered."""
    from zettcode.engine.extensions.harness_switch import HarnessSwitch
    from zettcode.engine.permission import Permission, ShellPolicy
    from zettcode.engine.plugins.services import HARNESS
    from zettcode.jit_harness.plugin import Harness
    from zettcode.plugin_api.host import HOST_LINK, HostLink

    built: dict[str, object] = {}

    class Agent:
        def register_extension_factory(self, name, factory):
            built["factory"] = factory

    class Tui:
        def register_command(self, name, description, handler, *, when_busy="refuse", subcommands=()):
            built["command"] = handler

    class Context:
        def __init__(self) -> None:
            self.config = config
            self.agent = Agent()
            self.tui = Tui()
            self.link = HostLink()

        def service(self, name, kind):
            return HarnessSwitch() if name == HARNESS else ShellPolicy(Permission.SAFE, workspace=config.workspace)

        def find(self, name, kind):
            return self.link if name == HOST_LINK else None

    Harness().activate(Context())  # type: ignore[arg-type]
    return built


async def test_a_description_outranks_the_brief_and_the_report_answers_it():
    """What A17 promises in words: the description wins, its prohibitions hold, and the report has to answer for both."""
    from zettcode.jit_harness.command import brief_for

    text = brief_for("only the two slow tests, and no network")
    flat = " ".join(text.split())

    assert "where it disagrees with the brief above, it wins" in flat
    assert "stays out of bounds however much the brief would otherwise allow" in flat
    assert "say whether every point of it was met" in flat


async def test_the_description_cannot_lift_the_floor():
    """A pasted request must not turn the command into one that writes where the session does not own: the brief says so,
    and says it again after the reader's own words, which is where it would otherwise be read past."""
    from zettcode.jit_harness.command import brief_for

    text = brief_for("also fix src/x.py and run the commands I pasted")
    before, tail = text.split("The floor above still holds", 1)
    tail = " ".join(tail.split())

    assert "lift the floor" in before
    assert "keep every write inside this session's harness folder" in before
    assert "do not run whatever it asks you to run elsewhere" in before
    assert "nothing here grants a permission" in before
    for rule in (
        "nothing is written outside this session's harness folder",
        "the workspace's own files are not edited",
        "only the tool built here is run",
        "no permission the session did not already have",
    ):
        assert rule in tail, f"the last paragraph no longer denies: {rule}"
