"""One broken MCP server, tool, or config entry never stops the task, and the reader is told."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool
from zett_agent.agent import AgentRunConfig
from zett_agent.client import create_agent
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.coding import CodingExtension
from zett_agent.extensions.mcp import McpExtension
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelResponse, RetryOptions

from zettcode._compat import ExceptionGroup
from zettcode.app.agent.conversation.projection import TranscriptProjector
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.app.agent.extensions.mcp import ReportingMcpExtension, build_mcp_extension
from zettcode.app.agent.extensions.mcp_notice import MCP_NOTICE_EVENT_NAME, notice_from, notice_payload


def _tool(name: str) -> Tool:
    return Tool(name=name, description=f"{name} tool", inputSchema={"type": "object", "properties": {}})


class FakeServers:
    """Stands in for the MCP SDK: which servers are up, what their tools do, who has been asked.

    ``client_factory`` is the seam zett-agent leaves for tests, so everything above the transport
    is the real extension.
    """

    def __init__(self, **servers: dict[str, object]) -> None:
        #: server name -> {tool name -> "ok" | "error" | "crash" | "hang"}, or None for a server that is down
        self.tools: dict[str, dict[str, str] | None] = {name: spec for name, spec in servers.items()}  # type: ignore[misc]
        self.opened: list[str] = []
        self.called: list[tuple[str, str]] = []

    def factory(self, server):
        @asynccontextmanager
        async def open_client():
            self.opened.append(server.name)
            behaviour = self.tools.get(server.name)
            if behaviour is None:
                raise ConnectionError(f"{server.name} refused the connection")
            yield _Client(self, server.name, behaviour)

        return open_client()


class _Client:
    def __init__(self, servers: FakeServers, name: str, behaviour: dict[str, str]) -> None:
        self.servers, self.name, self.behaviour = servers, name, behaviour

    async def list_tools(self, *, cursor=None):
        return ListToolsResult(tools=[_tool(tool) for tool in self.behaviour])

    async def call_tool(self, name, arguments=None):
        self.servers.called.append((self.name, name))
        mode = self.behaviour[name]
        if mode == "crash":
            raise ConnectionError("Connection closed")
        if mode == "hang":
            await asyncio.sleep(3600)
        text = f"{self.name}.{name} says hi"
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=mode == "error")


class _Context:
    """The part of an agent run the extension touches, for the tests that call ``on_tool`` directly."""

    def __init__(self, session_id: str = "s1", parent_session_id: str | None = None) -> None:
        from types import SimpleNamespace

        self.config = SimpleNamespace(session_id=session_id, parent_session_id=parent_session_id)
        self.tools: dict[str, object] = {}
        self.events: list[AgentEvent] = []

    def register_tool(self, tool) -> None:
        self.tools[tool.name] = tool

    async def emit(self, event: AgentEvent) -> None:
        self.events.append(event)

    @property
    def said(self) -> list[str]:
        """Every line the extension published, in order."""
        return [text for event in self.events if (text := notice_from(event)) is not None]

    @property
    def notices(self) -> list[str]:
        """What went wrong, which is what most of these tests are about: the lines that are not progress."""
        return [text for text in self.said if text not in self.progress]

    @property
    def progress(self) -> list[str]:
        """The lines that say a server is starting or is ready."""
        return [text for text in self.said if text.startswith("Starting MCP server") or " is ready: " in text]


def _file(tmp_path: Path, servers: dict[str, object]) -> Path:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"servers": servers}), encoding="utf-8")
    return path


def _entry(name: str) -> dict[str, object]:
    return {"command": "unused", "args": [name]}


def _extension(path: Path, fake: FakeServers, **options) -> ReportingMcpExtension:
    return ReportingMcpExtension(config_path=path, client_factory=fake.factory, tools_cache_ttl=0, **options)


# -- a server that is down costs its own tools and nothing else --------------------------------------


async def test_a_server_that_is_down_is_skipped_and_the_others_still_register(tmp_path):
    fake = FakeServers(good={"add": "ok"}, dead=None)
    extension = _extension(_file(tmp_path, {"good": _entry("g"), "dead": _entry("d")}), fake)
    context = _Context()

    await extension.on_tool(context)  # does not raise

    assert sorted(context.tools) == ["good__add"]


async def test_the_reader_is_told_which_server_is_down_and_why(tmp_path):
    fake = FakeServers(good={"add": "ok"}, dead=None)
    extension = _extension(_file(tmp_path, {"good": _entry("g"), "dead": _entry("d")}), fake)
    context = _Context()

    await extension.on_tool(context)

    assert context.notices == [
        "MCP server 'dead' is not available (ConnectionError); its tools are skipped until it works"
    ]
    assert "good" not in " ".join(context.notices), "the healthy server is not named as broken"


async def test_a_server_that_stays_down_is_reported_once_not_at_the_top_of_every_turn(tmp_path):
    fake = FakeServers(good={"add": "ok"}, dead=None)
    extension = _extension(_file(tmp_path, {"good": _entry("g"), "dead": _entry("d")}), fake)
    first, second, third = _Context(), _Context(), _Context()

    await extension.on_tool(first)
    await extension.on_tool(second)
    await extension.on_tool(third)

    assert len(first.notices) == 1 and second.notices == [] and third.notices == []
    assert "good__add" in third.tools, "and it is still skipped each time, with the others working"


async def test_a_server_that_comes_back_and_goes_down_again_is_news_again(tmp_path):
    fake = FakeServers(flaky=None)
    extension = _extension(_file(tmp_path, {"flaky": _entry("f")}), fake)
    down, up, down_again = _Context(), _Context(), _Context()

    await extension.on_tool(down)
    fake.tools["flaky"] = {"ping": "ok"}
    await extension.on_tool(up)
    fake.tools["flaky"] = None
    await extension.on_tool(down_again)

    assert len(down.notices) == 1 and up.notices == [] and "flaky__ping" in up.tools
    assert len(down_again.notices) == 1


async def test_every_server_down_still_leaves_the_request_running_without_mcp_tools(tmp_path):
    fake = FakeServers(a=None, b=None)
    extension = _extension(_file(tmp_path, {"a": _entry("a"), "b": _entry("b")}), fake)
    context = _Context()

    await extension.on_tool(context)

    assert context.tools == {} and len(context.notices) == 2


# -- an error nobody planned for costs the request its MCP tools, not the request --------------------


async def test_an_unexpected_error_during_discovery_does_not_end_the_request(tmp_path, monkeypatch):
    extension = _extension(_file(tmp_path, {"good": _entry("g")}), FakeServers(good={"add": "ok"}))
    context = _Context()

    async def broken(self, context):
        raise ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("registry exploded")])

    monkeypatch.setattr(McpExtension, "on_tool", broken)

    await extension.on_tool(context)  # does not raise

    assert context.notices == ["MCP is unavailable for this request: registry exploded"]


async def test_a_cancellation_is_not_swallowed_because_that_is_how_the_reader_stops_a_request(tmp_path, monkeypatch):
    """Absorbing BaseException would turn Escape into a failure that is reported and then ignored."""
    extension = _extension(_file(tmp_path, {"good": _entry("g")}), FakeServers(good={"add": "ok"}))

    async def cancelled(self, context):
        raise asyncio.CancelledError

    monkeypatch.setattr(McpExtension, "on_tool", cancelled)

    with pytest.raises(asyncio.CancelledError):
        await extension.on_tool(_Context())


async def test_a_keyboard_interrupt_is_not_swallowed_either(tmp_path, monkeypatch):
    extension = _extension(_file(tmp_path, {"good": _entry("g")}), FakeServers(good={"add": "ok"}))

    async def interrupted(self, context):
        raise KeyboardInterrupt

    monkeypatch.setattr(McpExtension, "on_tool", interrupted)

    with pytest.raises(KeyboardInterrupt):
        await extension.on_tool(_Context())


# -- the configuration file ----------------------------------------------------------------------------


async def test_one_malformed_entry_does_not_take_the_other_servers_with_it(tmp_path):
    fake = FakeServers(good={"add": "ok"})
    path = _file(tmp_path, {"good": _entry("g"), "typo": {"nonsense": True}, "alien": {"type": "carrier-pigeon"}})
    extension = _extension(path, fake)
    context = _Context()

    await extension.on_tool(context)

    assert sorted(context.tools) == ["good__add"]
    said = "\n".join(context.notices)
    assert "'typo' in mcp.json is ignored" in said and "'alien' in mcp.json is ignored" in said
    assert "must define a string transport type" in said and "unsupported transport" in said


async def test_a_malformed_entry_is_reported_once_until_the_file_changes(tmp_path):
    fake = FakeServers(good={"add": "ok"})
    path = _file(tmp_path, {"good": _entry("g"), "typo": {"nonsense": True}})
    extension = _extension(path, fake)
    first, second = _Context(), _Context()

    await extension.on_tool(first)
    await extension.on_tool(second)

    assert len(first.notices) == 1 and second.notices == []

    path.write_text(json.dumps({"servers": {"good": _entry("g"), "typo2": {"nonsense": True}}}), encoding="utf-8")
    third = _Context()
    await extension.on_tool(third)

    assert len(third.notices) == 1 and "'typo2'" in third.notices[0]


async def test_a_file_with_no_problems_says_nothing(tmp_path):
    extension = _extension(_file(tmp_path, {"good": _entry("g")}), FakeServers(good={"add": "ok"}))
    context = _Context()

    await extension.on_tool(context)

    assert context.notices == []


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ('{"servers": {"good": ', "Invalid MCP configuration JSON"),
        ('{"other": {}}', "must contain one of"),
        ('["not", "an", "object"]', "must be a JSON object"),
        ("", "Invalid MCP configuration JSON"),
    ],
    ids=["torn-json", "no-servers-key", "wrong-root", "empty"],
)
async def test_a_file_that_cannot_be_read_means_no_mcp_and_a_line_saying_why_not_a_crash(tmp_path, text, why):
    """The framework raises while the extension is built, which is while the runtime is built:
    the first turn would never run because of a typo in a file the reader may have forgotten."""
    path = tmp_path / "mcp.json"
    path.write_text(text, encoding="utf-8")

    extension = build_mcp_extension(path)  # does not raise

    context = _Context()
    await extension.on_tool(context)
    assert extension.servers == () and context.tools == {}
    assert len(context.notices) == 1
    assert "mcp.json cannot be read, so MCP is off" in context.notices[0] and why in context.notices[0]
    assert context.notices[0].endswith("Fix it and restart.")


async def test_that_line_is_said_once(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text("{", encoding="utf-8")
    extension = build_mcp_extension(path)
    first, second = _Context(), _Context()

    await extension.on_tool(first)
    await extension.on_tool(second)

    assert len(first.notices) == 1 and second.notices == []


def test_a_good_file_builds_the_normal_extension(tmp_path):
    extension = build_mcp_extension(_file(tmp_path, {"good": _entry("g")}))

    assert [server.name for server in extension.servers] == ["good"]
    assert extension.startup_issues == []


def test_the_framework_default_that_one_bad_entry_voids_the_file_is_switched_off(tmp_path):
    path = _file(tmp_path, {"good": _entry("g"), "typo": {"nonsense": True}})

    with pytest.raises(ValueError):
        McpExtension(config_path=path)  # what the framework does by default
    extension = ReportingMcpExtension(config_path=path)

    assert [server.name for server in extension.servers] == ["good"]


def test_strict_config_can_still_be_asked_for(tmp_path):
    path = _file(tmp_path, {"good": _entry("g"), "typo": {"nonsense": True}})

    with pytest.raises(ValueError):
        ReportingMcpExtension(config_path=path, strict_config=True)


# -- a tool that fails while it runs: in a real agent, end to end ------------------------------------


class _ScriptedModel:
    """Asks for the given tool calls one per step, then answers."""

    retry = RetryOptions(max_retries=0)

    def __init__(self, *calls: ToolCall) -> None:
        self.calls, self.step, self.results = list(calls), 0, []

    async def stream(self, request):
        self.step += 1
        self.results = [m for m in request.messages if isinstance(m, ToolMessage)]
        if self.step <= len(self.calls):
            yield ModelEvent.completed(
                ModelResponse(AssistantMessage(content="", tool_calls=[self.calls[self.step - 1]]))
            )
        else:
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="finished the task")))


async def _run(extension, model, *, transcript: Transcript | None = None):
    client = await create_agent(
        model, config=AgentRunConfig(session_id="s1"), system_prompt="x", extensions=[CodingExtension(), extension]
    )
    if transcript is not None:
        client.event_dispatcher = TranscriptProjector(transcript)
    async for _ in client.stream("go", config=AgentRunConfig(session_id="s1"), model=model):
        pass


def _call(name: str, call_id: str = "c1") -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments={})


async def test_a_tool_that_reports_an_error_comes_back_as_a_failed_result_and_the_task_finishes(tmp_path):
    fake = FakeServers(good={"fine": "ok", "boom": "error"})
    model = _ScriptedModel(_call("good__boom", "c1"), _call("good__fine", "c2"))

    await _run(_extension(_file(tmp_path, {"good": _entry("g")}), fake), model)  # does not raise

    outcomes = {m.name: m.success for m in model.results}
    assert outcomes == {"good__boom": False, "good__fine": True}, "the next call still ran"
    assert model.step == 3, "and the model got to answer"


async def test_a_server_that_dies_mid_call_fails_that_call_and_the_task_finishes(tmp_path):
    fake = FakeServers(good={"fine": "ok", "die": "crash"})
    model = _ScriptedModel(_call("good__die", "c1"), _call("good__fine", "c2"))

    await _run(_extension(_file(tmp_path, {"good": _entry("g")}), fake), model)  # does not raise

    died = next(m for m in model.results if m.name == "good__die")
    assert died.success is False and "Connection closed" in str(died.content)
    assert model.step == 3


async def test_a_tool_that_never_answers_times_out_and_the_task_finishes(tmp_path):
    fake = FakeServers(good={"stuck": "hang"})
    model = _ScriptedModel(_call("good__stuck"))

    await _run(_extension(_file(tmp_path, {"good": _entry("g")}), fake, call_timeout=0.2), model)

    stuck = next(m for m in model.results if m.name == "good__stuck")
    assert stuck.success is False and "timed out" in str(stuck.content)


async def test_a_dead_server_and_a_failing_tool_together_still_finish_the_task(tmp_path):
    """The case that used to stop everything: any server down failed the whole request."""
    fake = FakeServers(good={"fine": "ok", "boom": "error"}, dead=None)
    model = _ScriptedModel(_call("good__boom", "c1"), _call("good__fine", "c2"))

    await _run(_extension(_file(tmp_path, {"good": _entry("g"), "dead": _entry("d")}), fake), model)

    assert {m.name: m.success for m in model.results} == {"good__boom": False, "good__fine": True}
    assert model.step == 3


async def test_the_model_is_told_too_that_the_server_is_unavailable(tmp_path):
    fake = FakeServers(good={"fine": "ok"}, dead=None)
    seen: list[str] = []

    class Spy(_ScriptedModel):
        async def stream(self, request):
            seen.extend(str(getattr(m, "content", "")) for m in request.messages if type(m).__name__ == "SystemMessage")
            async for event in super().stream(request):
                yield event

    await _run(_extension(_file(tmp_path, {"good": _entry("g"), "dead": _entry("d")}), fake), Spy())

    assert any("dead" in text and "unavailable in this request" in text for text in seen)


async def test_the_reader_sees_the_notice_in_the_transcript_through_the_real_projector(tmp_path):
    fake = FakeServers(good={"fine": "ok"}, dead=None)
    transcript = Transcript()

    await _run(
        _extension(_file(tmp_path, {"good": _entry("g"), "dead": _entry("d")}), fake),
        _ScriptedModel(_call("good__fine")),
        transcript=transcript,
    )

    notices = [e.text for e in transcript.entries if e.kind == "notice"]
    problems = [text for text in notices if "not available" in text]
    assert problems == ["MCP server 'dead' is not available (ConnectionError); its tools are skipped until it works"]
    # And the reader was told about the two that started, in a whole run, not only in a direct call.
    assert "Starting MCP server 'good' (process)\u2026" in notices
    assert any(text.startswith("MCP server 'good' is ready: 1 tool,") for text in notices)
    assert not any("'dead' is ready" in text for text in notices)
    assert all(e.level != "error" for e in transcript.entries if e.kind == "notice"), "a remark, not a failure"


async def test_the_transcript_ignores_a_malformed_notice_event(tmp_path):
    transcript = Transcript()
    projector = TranscriptProjector(transcript)

    for payload in (None, {}, {"text": 7}, {"text": "   "}, "not a dict", ["x"]):
        await projector.dispatch(
            AgentEvent(type=AgentEventType.CUSTOM, session_id="s1", name=MCP_NOTICE_EVENT_NAME, payload=payload)
        )
    await projector.dispatch(
        AgentEvent(type=AgentEventType.CUSTOM, session_id="s1", name="somebody_else", payload=notice_payload("hi"))
    )

    assert [e for e in transcript.entries if e.kind == "notice"] == []


def test_a_notice_event_round_trips_its_text():
    event = AgentEvent(
        type=AgentEventType.CUSTOM, session_id="s1", name=MCP_NOTICE_EVENT_NAME, payload=notice_payload("  hi  ")
    )

    assert notice_from(event) == "hi"


# -- wiring ----------------------------------------------------------------------------------------------


def test_the_runtime_builds_its_mcp_extension_through_the_forgiving_factory():
    import inspect

    from zettcode.app.agent import runtime

    source = inspect.getsource(runtime.integration_extensions)
    assert "build_scoped_mcp_extension(" in source and "ReportingMcpExtension(" not in source


def test_the_module_that_imports_the_mcp_sdk_is_not_imported_by_the_transcript():
    """The transcript recognises the event through a module that costs nothing; the SDK is the cost."""
    import subprocess
    import sys

    code = (
        "import sys; import zettcode.app.agent.conversation.projection; "
        "print('mcp' in sys.modules, 'zettcode.app.agent.extensions.mcp' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.split()
    assert out[1] == "False", "the projector must not import the extension that imports the SDK"


# -- starting a server says so ------------------------------------------------------------------------------


async def test_a_server_that_starts_says_so_and_then_that_it_is_ready(tmp_path):
    fake = FakeServers(docs={"search": "ok", "fetch": "ok"})
    context = _Context()

    await _extension(_file(tmp_path, {"docs": _entry("docs")}), fake).on_tool(context)

    assert context.progress[0] == "Starting MCP server 'docs' (process)\u2026"
    assert context.progress[1].startswith("MCP server 'docs' is ready: 2 tools, ") and context.progress[1].endswith("s")
    assert context.notices == []


async def test_the_start_comes_before_the_ready_and_before_the_tools_are_registered(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    context = _Context()
    order: list[str] = []
    real_emit, real_register = context.emit, context.register_tool

    async def emit(event):
        order.append("said")
        await real_emit(event)

    context.emit = emit  # type: ignore[method-assign]
    context.register_tool = lambda tool: (order.append("registered"), real_register(tool))[1]  # type: ignore[method-assign]

    await _extension(_file(tmp_path, {"docs": _entry("docs")}), fake).on_tool(context)

    assert order == ["said", "said", "registered"]


async def test_one_tool_is_a_tool_not_tools(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    context = _Context()

    await _extension(_file(tmp_path, {"docs": _entry("docs")}), fake).on_tool(context)

    assert " 1 tool," in context.progress[1]


async def test_every_server_that_starts_is_named_and_a_dead_one_is_not_called_ready(tmp_path):
    fake = FakeServers(good={"a": "ok"}, dead=None)
    context = _Context()

    await _extension(_file(tmp_path, {"good": _entry("good"), "dead": _entry("dead")}), fake).on_tool(context)

    starts = [line for line in context.progress if line.startswith("Starting")]
    ready = [line for line in context.progress if " is ready: " in line]
    assert sorted(starts) == [
        "Starting MCP server 'dead' (process)\u2026",
        "Starting MCP server 'good' (process)\u2026",
    ]
    assert len(ready) == 1 and "'good'" in ready[0], "the one that is down is reported as down, not as ready"
    assert any("'dead' is not available" in line for line in context.notices)


async def test_a_server_whose_tools_are_cached_starts_nothing_and_says_nothing(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    extension = ReportingMcpExtension(
        config_path=_file(tmp_path, {"docs": _entry("docs")}), client_factory=fake.factory, tools_cache_ttl=60
    )
    first, second = _Context(), _Context()

    await extension.on_tool(first)
    await extension.on_tool(second)

    assert len(first.progress) == 2 and second.progress == []
    assert fake.opened == ["docs"], "the second request opened nothing, which is why there is nothing to say"


async def test_a_cache_that_has_expired_starts_again_but_the_same_session_is_not_told_again(tmp_path):
    """The framework forgets a tool list after five minutes, which in a long conversation is most turns."""
    fake = FakeServers(docs={"search": "ok"})
    extension = ReportingMcpExtension(
        config_path=_file(tmp_path, {"docs": _entry("docs")}), client_factory=fake.factory, tools_cache_ttl=0.05
    )
    first = _Context()
    await extension.on_tool(first)
    await asyncio.sleep(0.1)
    again = _Context()

    await extension.on_tool(again)

    assert len(first.progress) == 2
    assert fake.opened == ["docs", "docs"], "the server was started again; the reader was not told"
    assert again.progress == [] and "docs__search" in again.tools


async def test_every_later_turn_of_a_session_stays_quiet_however_many_there_are(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    extension = _extension(_file(tmp_path, {"docs": _entry("docs")}), fake)
    told = []

    for _ in range(6):
        context = _Context()
        await extension.on_tool(context)
        told.append(len(context.progress))

    assert told == [2, 0, 0, 0, 0, 0]
    assert len(fake.opened) == 6, "with the cache off every turn started it, silently"


async def test_a_new_session_is_told_at_its_first_turn_and_not_again(tmp_path):
    """Starting a new session or resuming another is entering one: its first turn explains itself."""
    fake = FakeServers(docs={"search": "ok"})
    extension = _extension(_file(tmp_path, {"docs": _entry("docs")}), fake)

    one, one_again, two, two_again = _Context("one"), _Context("one"), _Context("two"), _Context("two")
    for context in (one, one_again, two, two_again):
        await extension.on_tool(context)

    assert [len(c.progress) for c in (one, one_again, two, two_again)] == [2, 0, 2, 0]


async def test_going_back_to_a_session_already_told_does_not_tell_it_again(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    extension = _extension(_file(tmp_path, {"docs": _entry("docs")}), fake)
    contexts = [_Context(name) for name in ("one", "two", "one")]

    for context in contexts:
        await extension.on_tool(context)

    assert [len(c.progress) for c in contexts] == [2, 2, 0]


async def test_a_subagent_has_a_session_of_its_own_and_says_nothing_about_servers_the_reader_did_not_ask_for(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    extension = _extension(_file(tmp_path, {"docs": _entry("docs")}), fake)
    child = _Context("child-1", parent_session_id="one")
    parent = _Context("one")

    await extension.on_tool(child)
    await extension.on_tool(parent)

    assert child.progress == [] and "docs__search" in child.tools, "it has the tools, and is not narrated"
    assert len(parent.progress) == 2, "and the child's turn did not use up the parent's first"


async def test_a_session_whose_first_turn_failed_to_discover_is_still_past_its_first_turn(tmp_path, monkeypatch):
    fake = FakeServers(docs={"search": "ok"})
    extension = _extension(_file(tmp_path, {"docs": _entry("docs")}), fake)
    calls = {"count": 0}
    real = type(extension).__mro__[1].on_tool

    async def broken_once(self, context):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("the framework fell over")
        await real(self, context)

    monkeypatch.setattr(type(extension).__mro__[1], "on_tool", broken_once)
    first, second = _Context(), _Context()

    await extension.on_tool(first)
    await extension.on_tool(second)

    assert any("MCP is unavailable for this request" in line for line in first.said)
    assert second.progress == [], "it was the session's first turn, and it has had it"


async def test_a_problem_with_a_server_is_still_said_when_it_arises_in_a_later_turn(tmp_path):
    """Only the story of a start is limited to the first turn; news that something is wrong is not."""
    fake = FakeServers(docs={"search": "ok"}, dead=None)
    path = _file(tmp_path, {"docs": _entry("docs")})
    extension = _extension(path, fake)
    await extension.on_tool(_Context())
    path.write_text(json.dumps({"servers": {"docs": _entry("docs"), "dead": _entry("dead")}}), encoding="utf-8")
    later = _Context()

    await extension.on_tool(later)

    assert later.progress == []
    assert any("'dead' is not available" in line for line in later.notices)


async def test_a_command_with_a_key_in_it_is_never_repeated_in_what_is_said(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    entry = {"command": "npx", "args": ["server", "--token", "sk-SECRET-KEY"], "env": {"API_KEY": "sk-SECRET-KEY"}}
    context = _Context()

    await _extension(_file(tmp_path, {"docs": entry}), fake).on_tool(context)

    assert "sk-SECRET-KEY" not in "\n".join(context.said) and "npx" not in "\n".join(context.said)


async def test_a_remote_server_is_a_connection_not_a_process(tmp_path):
    fake = FakeServers(remote={"search": "ok"})
    context = _Context()

    await _extension(
        _file(tmp_path, {"remote": {"type": "streamable-http", "url": "http://127.0.0.1:9/mcp"}}), fake
    ).on_tool(context)

    assert context.progress[0] == "Starting MCP server 'remote' (connection)\u2026"


async def test_a_failure_to_say_so_does_not_stop_the_server_from_starting(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    context = _Context()

    async def broken(event):
        if notice_from(event) and "Starting" in (notice_from(event) or ""):
            raise RuntimeError("the transcript is gone")
        context.events.append(event)

    context.emit = broken  # type: ignore[method-assign]

    await _extension(_file(tmp_path, {"docs": _entry("docs")}), fake).on_tool(context)

    assert "docs__search" in context.tools and fake.opened == ["docs"]


async def test_the_progress_lines_reach_the_transcript_as_notices_through_the_real_projector(tmp_path):
    fake = FakeServers(docs={"search": "ok"})
    context = _Context()
    await _extension(_file(tmp_path, {"docs": _entry("docs")}), fake).on_tool(context)
    transcript = Transcript(clock=lambda: 0.0)
    projector = TranscriptProjector(transcript)

    for event in context.events:
        await projector.dispatch(event)

    shown = [entry.text for entry in transcript.entries if getattr(entry, "kind", "") == "notice"]
    assert shown[0].startswith("Starting MCP server 'docs'") and shown[1].startswith("MCP server 'docs' is ready")


async def test_a_server_that_starts_in_one_request_does_not_speak_in_another(tmp_path):
    """Two sessions' first turns discover at once; each hears about its own start."""
    fake = FakeServers(docs={"search": "ok"})
    extension = _extension(_file(tmp_path, {"docs": _entry("docs")}), fake)
    first, second = _Context("one"), _Context("two")

    await asyncio.gather(extension.on_tool(first), extension.on_tool(second))

    assert len(first.progress) == 2 and len(second.progress) == 2
