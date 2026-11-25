"""Active plugin inheritance through SDK spawns, model shell commands and every subagent profile."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import replace

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import ToolMessage

from sdk_helpers import ScriptedModel, asks_for, call, config_for, wire
from zettcode.daemon import CHILD_STATE_ENV
from zettcode.daemon.cli import _plugin_state
from zettcode.daemon.process import Daemons, SpawnFailed
from zettcode.daemon.run import Options, _client
from zettcode.daemon.state import Registry, State
from zettcode.engine.extensions.capabilities import ModelCapabilities
from zettcode.engine.extensions.subagents import subagent_extension
from zettcode.engine.plugins import CHILD_STATE, ChildSession, Plugin, PluginContext, load_plugins
from zettcode.sdk.builtins import AGENT_PLUGINS, _shared_with_children
from zettcode.sdk.client import Client
from zettcode.tools.shell import subprocess_environment


class Backend(Plugin[PluginContext]):
    name = "backend"
    priority = -100

    def __init__(self):
        self.target = "remote"

    def restore_child(self, state):
        self.target = state["target"]

    def export_child(self, child):
        assert child.kind == "daemon", "in-process subagents use fresh hooks, not a JSON roundtrip"
        return {"target": self.target}


def load(config, shared):
    return load_plugins(config, shared=shared, builtins=[*AGENT_PLUGINS, Backend], entry_points=())


def command(*argv):
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


async def test_active_sdk_spawn_exports_current_plugins(tmp_path, monkeypatch):
    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", load)
    seen = []

    async def spawn(workspace, **options):
        seen.append((workspace, options))
        return "spawned"

    monkeypatch.setattr("zettcode.sdk.daemons.spawn_daemon", spawn)
    async with Client(config=config_for(tmp_path)) as client:
        assert await client.spawn_daemon(name="worker") == "spawned"
        backend = next(plugin for plugin in client._agent.runtime.plugins.plugins if plugin.name == "backend")
        backend.target = "changed"
        await client.spawn_daemon(resume="saved")
    assert seen[0][0] == tmp_path / "project"
    assert seen[0][1]["plugin_state"] == {"backend": {"target": "remote"}}
    assert seen[1][1]["plugin_state"] == {"backend": {"target": "changed"}}


@pytest.mark.parametrize("permission", ["full", "safe"])
async def test_model_bash_has_handoff_without_changing_process_environment(tmp_path, monkeypatch, permission):
    from zettcode.engine.permission.sandbox import ShellSandbox

    if permission == "safe":
        sandbox = ShellSandbox(tmp_path)
        if not sandbox.available:
            pytest.skip(sandbox.unavailable_reason)
    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", load)
    monkeypatch.setenv(CHILD_STATE_ENV, "process sentinel")
    python = command(sys.executable, "-c", f"import os; print(os.environ[{CHILD_STATE_ENV!r}])")
    model = wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": python})), "done"))
    async with Client(config=config_for(tmp_path), permission=permission) as client:
        async with client.prompt("export") as run:
            async for _ in run:
                pass
    result = next(message for message in model.requests[-1].messages if isinstance(message, ToolMessage))
    assert json.loads(result.content) == {"backend": {"target": "remote"}}
    assert os.environ[CHILD_STATE_ENV] == "process sentinel"
    assert subprocess_environment() is None


async def test_plugin_replaced_bash_handler_sees_request_scoped_handoff(tmp_path, monkeypatch):
    class Replacing(Backend):
        async def on_tool_call(self, context, call, call_next):
            if call.name == "bash":
                return subprocess_environment()[CHILD_STATE_ENV]
            return await call_next()

    def plugins(config, shared):
        return load_plugins(config, shared=shared, builtins=[*AGENT_PLUGINS, Replacing], entry_points=())

    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", plugins)
    model = wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": "unused"})), "done"))
    async with Client(config=config_for(tmp_path), permission="full") as client:
        async with client.prompt("spawn through a plugin") as run:
            async for _ in run:
                pass
    result = next(message for message in model.requests[-1].messages if isinstance(message, ToolMessage))
    assert json.loads(result.content) == {"backend": {"target": "remote"}}
    assert subprocess_environment() is None


async def test_model_daemon_spawn_receives_state_and_removes_handoff(tmp_path, monkeypatch):
    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", load)
    # Run the real module command and argument parsing, replacing only the detached process in that interpreter.
    # The fixture script lives in tmp_path and needs no installed third-party plugin.
    script = tmp_path / "spawn.py"
    script.write_text(
        "import runpy, sys\n"
        "from zettcode.daemon.process import Daemons\n"
        "def start(self, workspace, **options):\n"
        " import json, os\n"
        " print('INHERITED=' + json.dumps(options['plugin_state']))\n"
        f" assert {CHILD_STATE_ENV!r} not in os.environ\n"
        " raise SystemExit(0)\n"
        "Daemons.start = start\n"
        "sys.argv = ['zettcode', 'daemon', 'spawn', '--workspace', sys.argv[1]]\n"
        "runpy.run_module('zettcode', run_name='__main__')\n",
        encoding="utf-8",
    )
    python = command(sys.executable, str(script), str(tmp_path))
    model = wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": python})), "done"))
    async with Client(config=config_for(tmp_path), permission="full") as client:
        async with client.prompt("spawn") as run:
            async for _ in run:
                pass
    result = next(message for message in model.requests[-1].messages if isinstance(message, ToolMessage))
    line = next(line for line in str(result.content).splitlines() if line.startswith("INHERITED="))
    assert json.loads(line.removeprefix("INHERITED=")) == {"backend": {"target": "remote"}}


@pytest.mark.parametrize("profile", ["explore", "coding", "reasoning"])
async def test_each_subagent_call_gets_fresh_profile_specific_extensions(tmp_path, monkeypatch, profile):
    from zettcode.engine.storage import SessionStore

    monkeypatch.chdir(tmp_path)
    made = []
    children = []

    class Marker(AgentExtension):
        # Replace explore's own file tools and coding's shared backend, not just an unrelated extra.
        name = {"explore": "FileTools", "coding": "CodingBundle", "reasoning": "backend-tools"}[profile]

        async def on_state(self, context):
            children.append(context.session_id)

    class Inheriting(Backend):
        def child_extensions(self, child):
            assert child.kind == "subagent" and child.profile == profile
            extension = Marker()
            made.append(extension)
            return (extension,)

    bundle = load_plugins(config_for(tmp_path), builtins=[Inheriting], entry_points=())
    store = SessionStore(tmp_path / "store", tmp_path)
    model = ScriptedModel(
        asks_for(call("task", {"description": "one", "prompt": "one", "subagent_type": profile})),
        "child one",
        asks_for(call("task", {"description": "two", "prompt": "two", "subagent_type": profile})),
        "child two",
        "parent done",
    )
    original = Marker()
    subagents = subagent_extension(
        model=model,
        persistence=store,
        capabilities=ModelCapabilities({}),
        shares=_shared_with_children(messaging=False),
        child_extensions=bundle.child_extensions,
    )
    parent = await Agent.create(model, config=AgentRunConfig(session_id="parent"), extensions=[original, subagents])
    async for _ in parent.stream("delegate"):
        pass
    assert len(made) == 2 and made[0] is not made[1] and original not in made
    assert len({session for session in children if session != "parent"}) == 2
    await store.close()


async def test_daemon_client_restores_state_before_activation(tmp_path, monkeypatch):
    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", load)
    monkeypatch.setenv("ZETTCODE_BROKER_DIR", str(tmp_path / "broker"))
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "absent.toml"))
    # Constructing a Client activates plugins but does not start any request.
    async with _client(
        Options(workspace=tmp_path, token="t", plugin_state={"backend": {"target": "inherited"}})
    ) as client:
        assert client.service(CHILD_STATE, dict) == {"backend": {"target": "inherited"}}
        assert client._agent.runtime.plugins.export_child(ChildSession("daemon")) == {
            "backend": {"target": "inherited"}
        }


async def test_inherited_activation_uses_sdk_configuration_surface(tmp_path, monkeypatch, capsys):
    from zettcode.daemon.run import serve
    from zettcode.sdk.errors import ConfigurationError

    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", load)
    config = config_for(tmp_path)
    with pytest.raises(ConfigurationError, match="Cannot inherit.*missing"):
        Client(config=config, shared={CHILD_STATE: {"missing": {}}})

    # Daemon factory uses that same SDK translation, and serve prints just the sentence.
    def factory(options):
        return Client(config=config, shared={CHILD_STATE: {"missing": {}}})

    monkeypatch.setattr("zettcode.daemon.run._client", factory)
    assert await serve(Options(workspace=tmp_path, token="test")) != 0
    error = capsys.readouterr().err
    assert "Cannot inherit" in error and "missing" in error and "Traceback" not in error


def test_missing_daemon_state_can_resume_as_an_ordinary_session(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "daemons")
    record = registry.record(tmp_path, "saved", create=True)
    assert not (record.folder / "state.json").exists()
    seen = []

    class Child:
        def __init__(self, argv, workspace, log, *, env):
            seen.append(env)

    monkeypatch.setattr("zettcode.daemon.process._Child", Child)
    monkeypatch.setattr(Daemons, "_await", lambda *args: record)
    Daemons(registry).start(tmp_path, resume="saved")
    assert json.loads(seen[0][CHILD_STATE_ENV]) == {}


def test_unreadable_daemon_state_is_not_treated_as_missing(tmp_path, monkeypatch):
    from pathlib import Path

    registry = Registry(tmp_path / "daemons")
    record = registry.record(tmp_path, "saved", create=True)
    path = record.folder / "state.json"
    raw = '{"protocol":999}'
    path.write_text(raw, encoding="utf-8")
    original = Path.stat

    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("access denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", denied)
    with pytest.raises(SpawnFailed, match="cannot be read.*zettcode daemon kill saved"):
        Daemons(registry).start(tmp_path, resume="saved")
    assert path.read_text(encoding="utf-8") == raw


def test_future_protocol_refuses_resume_with_explicit_remedy(tmp_path):
    registry = Registry(tmp_path / "daemons")
    record = registry.record(tmp_path, "saved", create=True)
    raw = '{"protocol":999,"plugin_state":{"backend":{"target":"remote"}}}'
    (record.folder / "state.json").write_text(raw, encoding="utf-8")
    with pytest.raises(SpawnFailed, match="unsupported protocol.*zettcode daemon kill saved"):
        Daemons(registry).start(tmp_path, resume="saved")
    assert (record.folder / "state.json").read_text(encoding="utf-8") == raw


def test_daemon_state_roundtrips_and_resume_keeps_inheritance(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemons"))
    registry = Registry()
    state = State(
        session_id="saved",
        workspace=str(tmp_path),
        pid=0,
        status="idle",
        token="t",
        started_at=0,
        plugin_state={"backend": {"target": "remote"}},
    )
    record = registry.record(tmp_path, "saved", create=True)
    record.save(state)
    assert State.load(record.folder).plugin_state == state.plugin_state
    seen = []

    class Child:
        def __init__(self, argv, workspace, log, *, env):
            seen.append(env)

    monkeypatch.setattr("zettcode.daemon.process._Child", Child)
    monkeypatch.setattr(Daemons, "_await", lambda *args: record)
    Daemons(registry).start(tmp_path, resume="saved")
    assert json.loads(seen[0][CHILD_STATE_ENV]) == state.plugin_state
    with pytest.raises(SpawnFailed, match="conflicts"):
        Daemons(registry).start(tmp_path, resume="saved", plugin_state={"backend": {"target": "local"}})
    with pytest.raises(SpawnFailed, match="JSON"):
        Daemons(registry).start(tmp_path, plugin_state={"backend": {"invalid": object()}})
    assert len(seen) == 1


def test_empty_saved_backend_can_inherit_and_cleanup_keeps_original_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemons"))
    registry = Registry()
    record = registry.record(tmp_path, "saved", create=True)
    record.save(
        State(
            session_id="saved",
            workspace=str(tmp_path),
            pid=0,
            status="idle",
            token="old",
            started_at=0,
            plugin_state={},
        )
    )
    seen = []

    class Child:
        def __init__(self, argv, workspace, log, *, env):
            seen.append(env)

        def abandon(self):
            pass

    monkeypatch.setattr("zettcode.daemon.process._Child", Child)
    monkeypatch.setattr(Daemons, "_await", lambda *args: record)
    Daemons(registry).start(tmp_path, resume="saved", plugin_state={"backend": {"target": "remote"}})
    assert json.loads(seen[-1][CHILD_STATE_ENV]) == {"backend": {"target": "remote"}}
    monkeypatch.setattr(Daemons, "_await", lambda *args: None)

    def locked(*args):
        raise OSError("record lock held")

    monkeypatch.setattr(Daemons, "_forget", locked)
    with pytest.raises(SpawnFailed, match="daemon stopped|daemon did not|could not start") as failure:
        Daemons(registry).start(tmp_path, resume="saved")
    assert "record lock held" not in str(failure.value)
    assert not list((registry.workspace(tmp_path) / ".spawn").glob("*.log"))


@pytest.mark.parametrize("raw", ["", "[]", "not-json", '{"backend":null}'])
def test_malformed_handoff_fails_closed_and_is_consumed(monkeypatch, raw):
    monkeypatch.setenv(CHILD_STATE_ENV, raw)
    with pytest.raises(ValueError):
        _plugin_state()
    assert CHILD_STATE_ENV not in os.environ


def test_companions_and_both_permission_restart_paths_keep_state(tmp_path, monkeypatch):
    from zettcode.daemon.companions import DaemonCompanions

    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemons"))
    registry = Registry()
    state = State(
        session_id="saved",
        workspace=str(tmp_path),
        pid=0,
        status="idle",
        token="t",
        started_at=0,
        plugin_state={"backend": {"target": "remote"}},
        plugin_arguments={"origin": {"option": True}},
    )
    record = registry.record(tmp_path, "saved", create=True)
    record.save(state)
    seen = []
    monkeypatch.setattr(Daemons, "start", lambda self, workspace, **kw: seen.append(kw) or record)
    daemons = Daemons(registry)
    daemons._start_again(record, "deny")
    daemons._put_back(record, state, "failed restart")
    companions = DaemonCompanions()
    companions._stopped = [replace(state)]
    companions.start()
    assert len(seen) == 3
    assert all(options["plugin_state"] == state.plugin_state for options in seen)
    assert all(options["plugin_arguments"] == state.plugin_arguments for options in seen)


@pytest.mark.parametrize("level,expected", [("deny", "deny"), ("ask", "deny"), ("safe", "safe"), ("full", "full")])
async def test_client_spawn_defaults_to_current_policy_but_allows_explicit_choice(
    tmp_path, monkeypatch, level, expected
):
    seen = []

    async def spawn(workspace, **options):
        seen.append(options)

    monkeypatch.setattr("zettcode.sdk.daemons.spawn_daemon", spawn)
    async with Client(config=config_for(tmp_path), permission="full") as client:
        client.use_permission(level, remember=False)
        await client.spawn_daemon()
        await client.spawn_daemon(permission="full")
    assert [item["permission"] for item in seen] == [expected, "full"]


async def test_actual_safe_shell_preserves_only_validated_task_handoff(tmp_path, monkeypatch):
    from zettcode.engine.permission.sandbox import ShellSandbox
    from zettcode.tools.shell import CommandFailed, run_command, shell_environment

    monkeypatch.chdir(tmp_path)
    sandbox = ShellSandbox(tmp_path)
    if not sandbox.available:
        pytest.skip(sandbox.unavailable_reason)
    monkeypatch.setenv(CHILD_STATE_ENV, "stale process value")
    monkeypatch.setenv("TEST_SECRET", "host secret")
    python = command(
        sys.executable,
        "-c",
        "import os,json; print(json.dumps({k:os.environ.get(k) for k in "
        f"[{CHILD_STATE_ENV!r},'TEST_SECRET','TASK_SECRET']}}))",
    )
    with shell_environment({CHILD_STATE_ENV: '{"backend":{"target":"remote"}}', "TASK_SECRET": "task secret"}):
        wrapped = sandbox.wrap(python, tmp_path)
        try:
            result = json.loads(await run_command(wrapped, 10, tmp_path))
        except CommandFailed as error:
            if "sandbox-exec: sandbox_apply: Operation not permitted" in str(error):
                pytest.skip("the test host refuses Seatbelt execution")
            raise
    assert json.loads(result[CHILD_STATE_ENV]) == {"backend": {"target": "remote"}}
    assert result["TEST_SECRET"] is None and result["TASK_SECRET"] is None
    assert CHILD_STATE_ENV not in sandbox.wrap("true", tmp_path)
    with shell_environment({CHILD_STATE_ENV: '{"backend":null}'}), pytest.raises(ValueError):
        sandbox.wrap("true", tmp_path)


@pytest.mark.parametrize("failure", ["before", "after", "removed"])
def test_real_failed_resume_restores_sole_descriptor(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemons"))
    registry = Registry()
    state = State(
        session_id="saved",
        workspace=str(tmp_path),
        pid=0,
        status="idle",
        token="old",
        started_at=0,
        permission="safe",
        plugin_arguments={"origin": {"enabled": True}},
        plugin_state={"backend": {"target": "remote"}},
    )
    record = registry.record(tmp_path, "saved", create=True)
    record.save(state)
    # A real interpreter runs Daemon.serve/mark and writes over the same record before failing to join. Its
    # client is deliberately tiny: no provider request or broker process is needed to exercise the transaction.
    script = tmp_path / "fail.py"
    script.write_text(
        "import asyncio,json,os,sys\n"
        "from types import SimpleNamespace as NS\n"
        "from zettcode.daemon.run import Daemon,Options\n"
        "from zettcode.daemon.state import Registry\n"
        "class Client:\n"
        " session=NS(id='saved',title=None)\n"
        " model=NS(name='fake',context_window=100)\n"
        " effort='low'\n"
        " def _export_daemon_state(self): return {'backend':{'target':'remote'}}\n"
        " async def join_sessions(self,*a,**k): return False\n"
        "workspace,token=sys.argv[1:]\n"
        f"if {failure == 'before'!r}: raise SystemExit('failure before mark')\n"
        "daemon=Daemon(Client(),Options(workspace=__import__('pathlib').Path(workspace),token=token))\n"
        # Abnormal process death bypasses serve's own rollback, testing the parent's restoration too.
        "if os.environ.get('CRASH_AFTER_MARK'):\n"
        " asyncio.run(daemon.mark('starting'))\n"
        f" if {failure == 'removed'!r}: daemon.record.remove()\n"
        " os._exit(2)\n"
        "raise SystemExit(asyncio.run(daemon.serve()))\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CRASH_AFTER_MARK", "1")
    monkeypatch.setattr(
        Daemons,
        "_command",
        lambda self, options: [
            sys.executable,
            str(script),
            str(options.workspace),
            options.token,
        ],
    )
    with pytest.raises(SpawnFailed):
        Daemons(registry).start(tmp_path, resume="saved")
    assert State.load(record.folder) == state
    assert not record.beating()
    assert registry.find("saved").state.plugin_state == state.plugin_state
    # The child that cleans up its own failed serve must preserve the descriptor too.
    monkeypatch.delenv("CRASH_AFTER_MARK")
    with pytest.raises(SpawnFailed):
        Daemons(registry).start(tmp_path, resume="saved")
    assert State.load(record.folder) == state


async def test_daemon_marks_actual_activated_state_and_refreshes_it(tmp_path, monkeypatch):
    from zettcode.daemon.run import Daemon

    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemons"))
    monkeypatch.setattr("zettcode.sdk.builtins.load_agent_plugins", load)
    async with Client(config=config_for(tmp_path)) as client:
        daemon = Daemon(client, Options(workspace=tmp_path, token="t"))
        await daemon.mark("starting")
        assert daemon.record.state.plugin_state == {"backend": {"target": "remote"}}
        backend = next(plugin for plugin in client._agent.runtime.plugins.plugins if plugin.name == "backend")
        backend.target = "changed"
        await daemon.mark("idle")
        saved = State.load(daemon.record.folder)
        assert saved.plugin_state == {"backend": {"target": "changed"}}
        backend.target = object()
        with pytest.raises(Exception, match="could not be exported"):
            await daemon.mark("working")
        assert State.load(daemon.record.folder) == saved
        assert daemon.stopping.is_set() and not daemon.record.beating()


def test_resume_preserves_arguments_when_omitted_and_explicit_empty_clears(tmp_path, monkeypatch):
    from zettcode.daemon import PLUGIN_ARGS_ENV

    registry = Registry(tmp_path / "daemons")
    record = registry.record(tmp_path, "saved", create=True)
    record.save(
        State(
            session_id="saved",
            workspace=str(tmp_path),
            pid=0,
            status="idle",
            token="old",
            started_at=0,
            plugin_arguments={"origin": {"enabled": True}},
        )
    )
    seen = []

    class Child:
        def __init__(self, argv, workspace, log, *, env):
            seen.append(env)

    monkeypatch.setattr("zettcode.daemon.process._Child", Child)
    monkeypatch.setattr(Daemons, "_await", lambda *args: record)
    Daemons(registry).start(tmp_path, resume="saved")
    Daemons(registry).start(tmp_path, resume="saved", plugin_arguments={})
    assert json.loads(seen[0][PLUGIN_ARGS_ENV]) == {"origin": {"enabled": True}}
    assert PLUGIN_ARGS_ENV not in seen[1]


async def test_sdk_normalizes_actual_launch_failure(tmp_path, monkeypatch):
    from zettcode.sdk.daemons import spawn_daemon
    from zettcode.sdk.errors import DaemonStartError

    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemons"))
    # Use the real Popen path, with an interpreter that does not exist.
    monkeypatch.setattr(Daemons, "_command", lambda self, options: [str(tmp_path / "missing-interpreter")])
    with pytest.raises(DaemonStartError, match="could not be launched"):
        await spawn_daemon(tmp_path)


def test_oversized_handoff_is_refused_before_launch(tmp_path, monkeypatch):
    launches = []
    monkeypatch.setattr("zettcode.daemon.process._Child", lambda *a, **kw: launches.append(kw))
    for options in (
        {"plugin_state": {"backend": {"target": "x" * 16384}}},
        {"plugin_arguments": {"origin": {"target": "x" * 16384}}},
        {"plugin_state": {"backend": {"target": "x" * 9000}}, "plugin_arguments": {"origin": {"target": "x" * 9000}}},
    ):
        with pytest.raises(SpawnFailed, match="16 KiB"):
            Daemons(Registry(tmp_path / "daemons")).start(tmp_path, **options)
    assert not launches


def test_launch_oserror_is_normalized_and_does_not_destroy_resume(tmp_path, monkeypatch):
    registry = Registry(tmp_path / "daemons")
    record = registry.record(tmp_path, "saved", create=True)
    state = State(session_id="saved", workspace=str(tmp_path), pid=0, status="idle", token="old", started_at=0)
    record.save(state)

    def fail(*args, **kwargs):
        raise OSError("argument list too long")

    monkeypatch.setattr("zettcode.daemon.process._Child", fail)
    with pytest.raises(SpawnFailed, match="could not be launched.*argument list too long"):
        Daemons(registry).start(tmp_path, resume="saved")
    assert State.load(record.folder) == state


@pytest.mark.parametrize(
    "key,value",
    [
        ("plugin_state", []),
        ("plugin_state", {"backend": None}),
        ("pid", "123"),
        ("pid", True),
        ("status", 5),
        ("started_at", float("nan")),
        ("plugin_arguments", {"origin": []}),
    ],
)
def test_malformed_durable_descriptor_is_not_believed_or_overwritten(tmp_path, key, value):
    from dataclasses import asdict

    record = Registry(tmp_path / "daemons").record(tmp_path, "saved", create=True)
    state = State(session_id="saved", workspace=str(tmp_path), pid=0, status="idle", token="old", started_at=0)
    raw = json.dumps({**asdict(state), key: value})
    (record.folder / "state.json").write_text(raw, encoding="utf-8")
    assert State.load(record.folder) is None
    with pytest.raises(OSError, match="malformed"):
        record.change(lambda current: state)
    with pytest.raises(SpawnFailed, match="malformed"):
        Daemons(Registry(tmp_path / "daemons")).start(tmp_path, resume="saved")
    assert (record.folder / "state.json").read_text(encoding="utf-8") == raw


def test_cli_resume_uses_only_explicit_plugin_overrides(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from zettcode.daemon.cli import daemon_program
    from zettcode.engine.plugins.cli import CliOption

    monkeypatch.setenv("ZETTCODE_DAEMON_DIR", str(tmp_path / "daemons"))
    monkeypatch.setattr(
        "zettcode.engine.plugins.cli.load_cached_options",
        lambda **kw: (
            ("origin", CliOption(("--target",), "target", default="local")),
            ("origin", CliOption(("--no-enabled",), "enabled", action="store_false", default=True)),
        ),
    )
    state = State(
        session_id="saved",
        workspace=str(tmp_path),
        pid=0,
        status="idle",
        token="old",
        started_at=0,
        plugin_arguments={"origin": {"target": "remote", "enabled": True, "unlisted": "keep"}},
    )
    record = Registry().record(tmp_path, "saved", create=True)
    record.save(state)
    seen = []

    def start(self, workspace, **options):
        seen.append(options["plugin_arguments"])
        return SimpleNamespace(state=None, session_id="saved")

    monkeypatch.setattr(Daemons, "start", start)
    assert daemon_program(["spawn", "--workspace", str(tmp_path), "--resume", "saved"]) == 0
    assert (
        daemon_program(
            [
                "spawn",
                "--workspace",
                str(tmp_path),
                "--resume",
                "saved",
                "--target",
                "local",
                "--no-enabled",
            ]
        )
        == 0
    )
    assert daemon_program(["spawn", "--workspace", str(tmp_path)]) == 0
    assert seen == [
        state.plugin_arguments,
        {"origin": {"target": "local", "enabled": False, "unlisted": "keep"}},
        {"origin": {"target": "local", "enabled": True}},
    ]


def test_duplicate_durable_keys_fail_closed_without_losing_backend(tmp_path):
    from dataclasses import asdict

    record = Registry(tmp_path / "daemons").record(tmp_path, "saved", create=True)
    state = State(session_id="saved", workspace=str(tmp_path), pid=0, status="idle", token="old", started_at=0)
    raw = json.dumps(asdict(state))[:-1] + ',"plugin_state":{"backend":{"host":"remote","host":"local"}}}'
    (record.folder / "state.json").write_text(raw, encoding="utf-8")
    assert State.load(record.folder) is None
    with pytest.raises(SpawnFailed, match="malformed"):
        Daemons(Registry(tmp_path / "daemons")).start(tmp_path, resume="saved")
    assert (record.folder / "state.json").read_text(encoding="utf-8") == raw
