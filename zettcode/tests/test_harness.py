"""The just-in-time harness: off unless asked for, switched between requests, and never half-on."""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.events import AgentEventType
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import AssistantMessage, SystemMessage
from zett_agent.model import ModelEvent, ModelResponse, RetryOptions

from plugin_helpers import agent_extensions
from zettcode.config import ModelConfig, ZettCodeConfig, load_config
from zettcode.engine.extensions.harness import SwitchedHarness
from zettcode.engine.extensions.harness_switch import HarnessSwitch

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
    """`/harness on` does not rebuild anything: the same agent offers the tools from its next request."""
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
    (harness,) = [e for e in agent_extensions(config) if isinstance(e, SwitchedHarness)]

    assert harness.session_directory("abc").parent == (tmp_path / "harness").absolute()
    assert not harness.session_directory("abc").is_relative_to(tmp_path / "sessions")


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
        return runtime_module.ZettCodeEngine.preview(config)

    off, on = runtime(), runtime(jit_harness=True)
    assert off.harness.on is False and on.harness.on is True

    assert off.use_harness(True) is True and off.harness.on is True
    assert off.use_harness(False) is False and off.harness.on is False
