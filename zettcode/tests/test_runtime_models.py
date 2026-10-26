"""Model switching uses the configured endpoint and API per request."""

import asyncio
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest
from zett_agent.extensions.agents_md import AgentsMdExtension
from zett_agent.extensions.ask_user import AskUserExtension
from zett_agent.extensions.mcp import McpExtension
from zett_agent.extensions.skill import SkillExtension
from zett_agent.messages import UserMessage

from plugin_helpers import agent_extensions
from zettcode._compat import ExceptionGroup
from zettcode.app.agent.agent import TerminalAgent
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import core as runtime_module
from zettcode.engine import pipeline as pipeline_module
from zettcode.engine.extensions.compaction import OnDemandCompaction
from zettcode.engine.storage import STORE_FILE, SessionStore
from zettcode.error_text import describe_error


def test_the_system_prompt_head_changes_only_by_the_day(tmp_path):
    """The prompt head is part of the provider's cache key.

    A clock reading with seconds would make it unique to every launch, which
    drops the cache for the whole conversation; the day keeps the head reusable
    while still telling the model what today is.
    """
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")
    morning = datetime(2026, 10, 4, 9, 15, 3, tzinfo=timezone.utc)
    late = datetime(2026, 10, 4, 23, 59, 59, tzinfo=timezone.utc)

    prompt = runtime_module.build_system_prompt(config, now=morning)

    assert "- Today: 2026-10-04" in prompt
    assert prompt == runtime_module.build_system_prompt(config, now=late)
    assert prompt != runtime_module.build_system_prompt(config, now=late + timedelta(days=1))


def test_the_system_prompt_tells_the_model_to_change_files_with_the_file_tools_and_never_the_shell(tmp_path):
    """The model reached for sed, cat > and scripts it wrote itself, which leave no diff for the reader to see."""
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")

    prompt = runtime_module.build_system_prompt(config)
    flat = " ".join(prompt.split())

    assert "To edit a file that exists, call edit directly" in flat
    assert "Use write_file for a new file" in flat and "There is no delete tool" in flat
    assert "delete_file" not in flat
    for forbidden in ("sed", "awk", "perl -i", "python -c", "cat or echo with a redirection", "a heredoc", "tee"):
        assert forbidden in flat, forbidden
    assert "Never change a file's contents through the shell" in flat
    assert "retry it with corrected old_text; do not fall back to a shell command" in flat


def test_the_system_prompt_tells_the_model_to_read_with_the_file_tool_and_in_line_ranges(tmp_path):
    """The model reached for cat and sed to look at files, and for a whole long file when a range was enough."""
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")

    prompt = runtime_module.build_system_prompt(config)
    flat = " ".join(prompt.split())

    assert "Reading files: call read" in flat
    for refused in ("cat", "sed", "head", "tail", "nl", "awk"):
        assert refused in flat.split("Reading files:")[1], refused
    assert "start_line and line_count" in flat
    assert "a long file is read in the parts you need rather than whole" in flat
    assert "grep and glob are for finding what to read" in flat
    assert prompt.index("Reading files:") < prompt.index("Runtime environment:")


def test_the_file_editing_rule_comes_before_the_environment_snapshot_so_the_head_stays_cacheable(tmp_path):
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")

    prompt = runtime_module.build_system_prompt(config)

    assert prompt.index("Changing files:") < prompt.index("Runtime environment:")
    assert str(tmp_path) not in prompt[: prompt.index("Runtime environment:")], "nothing that varies sits above it"


def _config_with(tmp_path, **changes) -> ZettCodeConfig:
    """Return a minimal config, with one workspace-local change applied.

    The MCP file defaults to one that does not exist, so a developer's own
    ``~/.zettcode/mcp.json`` cannot decide what a test sees, and project
    instructions are off unless the test asks for them: each of these tests
    asserts the tuple its own integration contributes, and ``test_agents_md.py``
    covers the instructions that are on by default.
    """
    defaults = {"mcp_config": tmp_path / "absent-mcp.json", "agents_md_enabled": False, **changes}
    return ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        **defaults,
    )


def _mcp(extensions) -> McpExtension:
    """Return the composed MCP extension, wherever the tuple puts it."""
    return next(extension for extension in extensions if isinstance(extension, McpExtension))


def test_configured_skill_roots_are_discovered_and_advertised(tmp_path):
    skill = tmp_path / "skills" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review a diff with the team checklist\n---\n\nRead the diff twice.\n",
        encoding="utf-8",
    )

    config = _config_with(tmp_path, skill_roots=(tmp_path / "skills",))
    extension = next(item for item in agent_extensions(config) if isinstance(item, SkillExtension))

    catalog = {item.name: item for item in extension.skills}
    assert catalog["review"].description == "Review a diff with the team checklist"
    assert catalog["review"].path == (skill / "SKILL.md").resolve()


def test_mcp_is_loaded_only_when_a_server_file_exists(tmp_path):
    servers = tmp_path / "mcp.json"
    servers.write_text(
        '{"servers": {"docs": {"type": "streamable-http", "url": "http://127.0.0.1:9/mcp"}}}',
        encoding="utf-8",
    )

    loaded = agent_extensions(_config_with(tmp_path, mcp_config=servers))
    missing = agent_extensions(_config_with(tmp_path, mcp_config=tmp_path / "absent.json"))

    assert [server.name for server in _mcp(loaded).servers] == ["docs"]
    # With no server file there is nothing to load, so no MCP instructions are
    # added to the request at all.
    assert not any(isinstance(extension, McpExtension) for extension in missing)


def test_the_optional_integrations_can_be_disabled(tmp_path):
    servers = tmp_path / "mcp.json"
    servers.write_text('{"servers": {}}', encoding="utf-8")

    extensions = agent_extensions(
        _config_with(
            tmp_path,
            agents_md_enabled=False,
            ask_user_enabled=False,
            skills_enabled=False,
            mcp_enabled=False,
            mcp_config=servers,
        )
    )

    assert not any(
        isinstance(extension, (AgentsMdExtension, AskUserExtension, SkillExtension, McpExtension))
        for extension in extensions
    )


async def test_the_runtime_starts_loading_its_token_counter_with_the_provider(tmp_path, monkeypatch):
    """`/context` must not fetch a vocabulary on the reader's keystroke.

    The counter belongs to the runtime, so its load begins where the provider's
    does — behind the first frame — rather than the first time a panel asks for
    it. Nothing waits for it there: the deadline still governs how long a report
    will wait, and `aclose` releases the wait when the shell leaves first.
    """
    loaded: list[str] = []

    def loader(name: str):
        loaded.append(name)
        return lambda text: [0] * len(text)

    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    monkeypatch.setattr("zett_agent.client.create_agent", lambda model, **kwargs: type("C", (), {})())
    runtime = runtime_module.ZettCodeEngine.preview(_config_with(tmp_path))
    runtime.tokenizer = runtime_module.Tokenizer(deadline=5.0, loader=loader)

    runtime.start()
    deadline = time.perf_counter() + 5.0
    while not loaded and time.perf_counter() < deadline:
        await asyncio.sleep(0.01)

    assert loaded == [runtime.tokenizer.encoding], "the load begins with the runtime, not with the panel"
    await runtime.aclose()


async def test_closing_a_runtime_does_not_wait_for_a_counter_still_loading(tmp_path, monkeypatch):
    """A vocabulary still downloading is nobody's answer once the shell has gone."""
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    monkeypatch.setattr("zett_agent.client.create_agent", lambda model, **kwargs: type("C", (), {})())
    runtime = runtime_module.ZettCodeEngine.preview(_config_with(tmp_path))
    runtime.tokenizer = runtime_module.Tokenizer(deadline=30.0, loader=lambda name: time.sleep(30.0))
    runtime.start()
    await asyncio.sleep(0.02)

    started = time.perf_counter()
    await asyncio.wait_for(runtime.aclose(), 5.0)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, f"closing waited {elapsed:.2f}s for a counter load"


def test_the_runtime_module_costs_nothing_until_it_starts(tmp_path):
    """The provider, MCP, and subagent SDKs must not be in the graph the shell pays for.

    The subagent extension imports its SQLite store, which imports SQLAlchemy —
    a database nothing here uses. It is built with the runtime, behind the first
    frame, so a module-level import of it would quietly cost every launch.
    """
    script = "\n".join(
        [
            "import sys",
            "from pathlib import Path",
            "import zettcode.engine.core as runtime_module",
            "from zettcode.config import ModelConfig, ZettCodeConfig",
            "config = ZettCodeConfig(",
            "    workspace=Path(sys.argv[1]),",
            "    models=(ModelConfig(model='m', token='t'),),",
            "    store=Path(sys.argv[1]),",
            ")",
            "runtime_module.ZettCodeEngine.preview(config)",
            "heavy = ('anthropic', 'openai', 'mcp', 'sqlalchemy', 'zett_agent.extensions.subagent')",
            "print(*(name in sys.modules for name in heavy))",
        ]
    )

    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False False False False"


@pytest.mark.parametrize(
    ("models", "sdks"),
    [
        ((False,), ("openai", "openai.resources")),
        ((True,), ("anthropic",)),
        ((False, True), ("openai", "openai.resources", "anthropic")),
        ((True, False), ("openai", "openai.resources", "anthropic")),
    ],
    ids=["openai-only", "anthropic-only", "both", "both-reversed"],
)
@pytest.mark.parametrize(("subagent", "mcp"), [(True, True), (False, False)])
def test_the_warm_up_names_every_module_a_request_needs(tmp_path, monkeypatch, models, sdks, subagent, mcp):
    """The SDKs of every configured model are warmed, and the optional modules follow the config.

    Every configured entry, not only the active one: ``/model`` can select an entry that speaks the
    other API, and the adapter built for it imports its SDK in the constructor — doing that on the
    event loop, in the middle of a turn, is the freeze this warm-up exists to avoid. An entry that
    is not configured cannot be selected, so a run that only talks to OpenAI-compatible endpoints
    leaves ``anthropic`` unimported, on a thread that would have competed with the interface.

    OpenAI's resource tree is named as well as the package: the first request imports it — five
    hundred modules, 430 ms measured — and that is the loop's, unless it was done here.
    """
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=tuple(
            ModelConfig(model=f"m{index}", token="t", anthropic=anthropic) for index, anthropic in enumerate(models)
        ),
        store=tmp_path / "sessions",
        subagent_enabled=subagent,
        mcp_enabled=mcp,
        mcp_config=tmp_path / "absent-mcp.json",
    )

    names = runtime_module.ZettCodeEngine.preview(config).warm_modules()

    assert names == (
        *sdks,
        "zett_agent.client",
        "zettcode.engine.extensions.files",
        *(("zett_agent.extensions.subagent",) if subagent else ()),
        *(("zett_agent.extensions.mcp",) if mcp else ()),
    )


async def test_a_close_while_the_imports_are_running_does_not_wait_for_them(tmp_path, monkeypatch):
    """Leaving before the first turn must not wait for an import nobody needs any more."""
    original = pipeline_module.importlib.import_module

    class SlowImports:
        """Stand in for a model SDK: slow enough that a close mid-import is visible."""

        def import_module(self, name: str, package: str | None = None) -> object:
            time.sleep(1.0)
            return original(name, package)

    async def fake_create_agent(model, **kwargs):
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr(pipeline_module, "importlib", SlowImports())
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    runtime = runtime_module.ZettCodeEngine.preview(_config_with(tmp_path))
    warm = runtime.start()
    await asyncio.sleep(0)

    started = time.perf_counter()
    await asyncio.wait_for(runtime.aclose(), 2.0)
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5, f"closing waited {elapsed:.2f}s for the imports"
    assert warm.cancelled()
    # Nothing was built, so there is no client to have closed and no second one
    # to leak: the provider list is empty and the request never happened.
    assert runtime.client is None
    assert runtime._models == {}
    assert runtime._imports is not None and runtime._imports.done


async def test_an_anthropic_model_builds_the_messages_adapter(tmp_path, monkeypatch):
    """``anthropic = true`` reaches zett-agent's Messages adapter, and only it.

    The two adapters take different constructor arguments — the OpenAI one is
    told which protocol to speak, the Anthropic one has no Responses mode to
    pick — so the branch is what decides which request shape leaves the process.
    """
    built: list[dict[str, object]] = []

    class FakeAnthropic:
        def __init__(self, model, token, *, base_url):
            built.append({"model": model, "token": token, "base_url": base_url})

        async def aclose(self):
            pass

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            raise AssertionError("an Anthropic entry must not build the OpenAI adapter")

    async def fake_create_agent(model, **kwargs):
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.anthropic.AnthropicProvider", FakeAnthropic)
    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeOpenAI)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    monkeypatch.setattr("zettcode.config.DEFAULT_MCP_CONFIG", tmp_path / "absent-mcp.json")
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="claude-sonnet-4-5", token="anthropic-key", anthropic=True),),
        store=tmp_path / "sessions",
    )

    runtime = await runtime_module.ZettCodeEngine.create(config)

    # The Messages API lives at the Anthropic root itself, so an entry that
    # names no base_url is called there rather than at an OpenAI default.
    assert built == [{"model": "claude-sonnet-4-5", "token": "anthropic-key", "base_url": "https://api.anthropic.com"}]
    assert runtime.active_model.api == "anthropic"
    await runtime.aclose()


@pytest.mark.parametrize(
    ("written", "called"),
    [
        # The route the client appends is removed, the prefix in front of it stays.
        ("https://gw.example/anthropic/v1/messages", "https://gw.example/anthropic"),
        ("https://gw.example/anthropic", "https://gw.example/anthropic"),
    ],
)
async def test_an_anthropic_entry_hands_the_adapter_the_corrected_base_url(tmp_path, monkeypatch, written, called):
    """The entry is corrected once, at the config, and the adapter is built with that."""
    built: list[str] = []

    class FakeAnthropic:
        def __init__(self, model, token, *, base_url):
            built.append(base_url)

        async def aclose(self):
            pass

    async def fake_create_agent(model, **kwargs):
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.anthropic.AnthropicProvider", FakeAnthropic)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    monkeypatch.setattr("zettcode.config.DEFAULT_MCP_CONFIG", tmp_path / "absent-mcp.json")
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="claude", token="t", anthropic=True, base_url=written),),
        store=tmp_path / "sessions",
    )

    runtime = await runtime_module.ZettCodeEngine.create(config)

    assert built == [called]
    await runtime.aclose()


def test_the_agent_names_the_file_its_session_is_stored_in(tmp_path):
    """`/context` shows it, so it has to be the store's own path and not a guess."""
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
    )
    agent = TerminalAgent.preview(config)

    path = agent.session_path()

    assert path.parent.name == agent.session_id, "one directory per session"
    assert path.name == STORE_FILE, "the conversation file the store appends to"
    assert path.is_relative_to((tmp_path / "sessions").resolve())


async def test_a_preview_runtime_starts_once_and_only_then(tmp_path, monkeypatch):
    """The shell paints from the preview; the provider appears on the first turn."""
    created: list[object] = []

    class FakeProvider:
        def __init__(self, model, token, *, base_url, response):
            self.closed = False
            created.append(self)

        async def aclose(self):
            self.closed = True

    async def fake_create_agent(model, **kwargs):
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)

    runtime = runtime_module.ZettCodeEngine.preview(_config_with(tmp_path))

    assert runtime.client is None and runtime.model is None
    # Compaction is armed from the preview: the budget belongs to the model, so
    # `/compact` has a threshold to force past even before the first turn.
    assert runtime.compaction.max_tokens == 102_400
    with pytest.raises(RuntimeError, match="has not started"):
        _ = runtime.provider
    assert created == []

    first = runtime.start()
    assert runtime.start() is first
    await first

    assert len(created) == 1
    assert runtime.started is runtime.client
    assert runtime.provider is created[0]
    await runtime.aclose()
    assert created[0].closed is True


async def test_the_harness_switches_choose_the_tools_the_model_may_use(tmp_path, monkeypatch):
    """``task`` and ``todo_write`` are the two the config owns; the defaults show."""
    from zett_agent.extensions.subagent import SubAgentExtension
    from zett_agent.extensions.todo import TodoWriteExtension

    given: list[list[object]] = []

    class FakeProvider:
        def __init__(self, model, token, *, base_url, response):
            self.closed = False

        async def aclose(self):
            self.closed = True

    async def fake_create_agent(model, **kwargs):
        given.append(list(kwargs["extensions"]))
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)

    cases = ((True, False), (False, True))
    for subagent, todowrite in cases:
        config = _config_with(tmp_path, subagent_enabled=subagent, todowrite_enabled=todowrite)
        await runtime_module.ZettCodeEngine.preview(config).start()

    for (subagent, todowrite), extensions in zip(cases, given, strict=True):
        kinds = [type(extension) for extension in extensions]
        # The task tool is the framework's extension or ZettCode's subclass of it.
        assert any(isinstance(extension, SubAgentExtension) for extension in extensions) is subagent
        assert (TodoWriteExtension in kinds) is todowrite


#: How long each import takes in the warm-up test below, and the longest the event loop may go without
#: turning while they run. The delay is the signal: a warm-up that ran on the loop would stall it for at
#: least one whole import, so the limit sits well under that. It also sits well over what the import
#: *thread* can do to a loop that is waiting for the interpreter lock: compiling a large module with no
#: bytecode cache, which is what a fresh CI checkout has, held it for 150-210 ms. A limit just under the
#: delay (0.15 s against 0.2 s) failed about half of the Python 3.10 runs there, for a loop that was never
#: blocked by the warm-up at all.
WARM_UP_IMPORT_SECONDS = 0.6
WARM_UP_LOOP_LIMIT = 0.35


async def test_the_warm_up_never_blocks_the_event_loop(tmp_path, monkeypatch):
    """Importing the SDKs blocks for hundreds of milliseconds; the loop must turn.

    The shell is already taking the reader's keys when the runtime warms, so a
    warm-up that runs on the loop freezes the interface for its whole duration —
    no keystroke echoes and no frame repaints until the provider exists.
    """
    calls: list[str] = []
    original = pipeline_module.importlib.import_module

    class SlowImports:
        """Stand in for the imports the warm-up pays for, at a test's speed."""

        def import_module(self, name: str, package: str | None = None) -> object:
            calls.append(name)
            time.sleep(WARM_UP_IMPORT_SECONDS)
            return original(name, package)

    async def fake_create_agent(model, **kwargs):
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr(pipeline_module, "importlib", SlowImports())
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    runtime = runtime_module.ZettCodeEngine.preview(_config_with(tmp_path))

    gaps: list[float] = []
    state = {"last": time.perf_counter()}

    async def tick() -> None:
        while not warm.done():
            await asyncio.sleep(0.001)
            now = time.perf_counter()
            gaps.append(now - state["last"])
            state["last"] = now

    warm = runtime.start()
    ticker = asyncio.ensure_future(tick())
    await asyncio.gather(warm, return_exceptions=True)
    ticker.cancel()
    await asyncio.gather(ticker, return_exceptions=True)

    assert calls, "the runtime never warmed the SDKs"
    assert gaps, "the event loop never turned while the runtime warmed"
    assert max(gaps) < WARM_UP_LOOP_LIMIT


async def test_a_text_only_model_reads_with_the_text_reader_and_a_model_with_search_gets_it_declared():
    """`read` returns a picture as an image part; a model that cannot take one is given `read_file` instead."""
    from zett_agent.agent import Agent, AgentRunConfig
    from zett_agent.events import AgentEventType
    from zett_agent.extensions.base import AgentExtension
    from zett_agent.messages import AssistantMessage
    from zett_agent.model import ModelEvent, ModelResponse, RetryOptions

    from zettcode.engine.extensions.capabilities import ModelCapabilities
    from zettcode.engine.extensions.files import CodingBundle
    from zettcode.engine.tools.files import read, read_file

    class Context:
        """The things the filter reads and changes."""

        def __init__(self, model: object) -> None:
            self.model = model
            self.tools = {read.name: read}
            self.server_tools: dict[str, object] = {}

        def register_tool(self, tool) -> None:
            self.tools[tool.name] = tool

        def register_server_tool(self, tool) -> None:
            self.server_tools[tool.type] = tool

    text_only = ModelConfig(model="text", token="t")
    takes_images = ModelConfig(model="vision", token="t", multimodal=True, web_search=True)

    class Model:
        retry = RetryOptions(max_retries=0)

        async def stream(self, request):
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="ok")))

    model = Model()
    providers = {text_only: model, takes_images: object()}
    capabilities = ModelCapabilities(providers)

    gated = Context(providers[text_only])
    await capabilities.on_tool(gated)
    assert gated.tools == {read_file.name: read_file}
    assert gated.server_tools == {}

    allowed = Context(providers[takes_images])
    await capabilities.on_tool(allowed)
    assert read.name in allowed.tools and read_file.name not in allowed.tools
    assert list(allowed.server_tools) == ["web_search"]

    # A request whose model this runtime did not build keeps the tools it has.
    unknown = Context(object())
    await capabilities.on_tool(unknown)
    assert read.name in unknown.tools and unknown.server_tools == {}

    # Through the real hooks the filter runs after the bundle that registers the
    # tool, which is the ordering the whole thing depends on.
    class Probe(AgentExtension):
        priority = 200

        def __init__(self) -> None:
            self.offered: list[list[str]] = []

        async def on_tool(self, context) -> None:
            self.offered.append(sorted(context.tools))

    probe = Probe()
    agent = await Agent.create(
        model,
        config=AgentRunConfig(session_id="test"),
        extensions=[CodingBundle(), capabilities, probe],
    )

    streamed = [event async for event in agent.stream("hello", config=AgentRunConfig(session_id="test"))]

    assert streamed[-1].type is AgentEventType.RUN_COMPLETED
    assert "read" not in probe.offered[0]
    assert "read_file" in probe.offered[0]
    assert "view_image" not in probe.offered[0] and "delete_file" not in probe.offered[0]


async def test_the_approval_memory_remembers_exact_commands_for_the_run():
    """The prompt promises one exact command for this run, not an allowlist."""
    from zett_agent.extensions.shell_approval import ShellApprovalMode

    from zettcode.engine.permission.approval import ShellApprovalMemory

    memory = ShellApprovalMemory()

    assert await memory.get_session_mode("session-1") is ShellApprovalMode.REVIEW
    assert await memory.is_allowed("session-1", "rm -rf build") is False

    await memory.set_session_mode("session-1", ShellApprovalMode.ALLOW_ALL)
    await memory.allow_command("rm -rf build")

    assert await memory.get_session_mode("session-1") is ShellApprovalMode.ALLOW_ALL
    assert await memory.is_allowed("session-1", "rm -rf build") is True
    assert await memory.is_allowed("session-1", "rm -rf dist") is False
    # The policy is per session, and clearing it reviews again.
    assert await memory.get_session_mode("session-2") is ShellApprovalMode.REVIEW
    await memory.clear_session_mode("session-1")
    assert await memory.get_session_mode("session-1") is ShellApprovalMode.REVIEW


def test_error_reasons_are_unwrapped_from_their_groups_and_deduplicated():
    """A task-group failure says nothing; the reasons are its leaves."""
    grouped = ExceptionGroup(
        "unhandled errors in a TaskGroup",
        [
            ExceptionGroup("unhandled errors in a TaskGroup", [ConnectionError("All connection attempts failed")]),
            ConnectionError("All connection attempts failed"),
            ValueError("bad config"),
            KeyError("silent"),
        ],
    )

    assert describe_error(grouped) == "All connection attempts failed; bad config; 'silent'"
    assert describe_error(ValueError("plain")) == "plain"


async def test_runtime_switches_models_and_closes_every_provider(tmp_path, monkeypatch):
    created = []
    captured = {}

    class FakeProvider:
        def __init__(self, model, token, *, base_url, response):
            self.model = model
            self.token = token
            self.base_url = base_url
            self.response = response
            self.closed = False
            created.append(self)

        async def aclose(self):
            self.closed = True

    async def fake_create_agent(model, **kwargs):
        captured["model"] = model
        captured.update(kwargs)
        return type("FakeClient", (), {"event_dispatcher": None})()

    # The provider and the client are imported when the runtime starts, so the
    # doubles replace them where that import reads from.
    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    # A developer's own ~/.zettcode/mcp.json must not decide what this test sees.
    monkeypatch.setattr("zettcode.config.DEFAULT_MCP_CONFIG", tmp_path / "absent-mcp.json")
    first = ModelConfig(model="shared-id", display_model="First", token="first", base_url="http://first.test")
    second = ModelConfig(
        model="shared-id",
        display_model="Second",
        token="second",
        base_url="http://tds.com:8787",
        context_window=200_000,
        compact_percent=75,
    )
    config = ZettCodeConfig(workspace=tmp_path, models=(first, second), store=tmp_path / "sessions")
    await SessionStore(config.store, config.workspace).append(
        "existing-session", "old-request", UserMessage(content="earlier")
    )

    runtime = await runtime_module.ZettCodeEngine.create(config)
    assert runtime.session_id != "existing-session"
    assert captured["config"].session_id == runtime.session_id
    assert runtime.active_model is first
    assert captured["model"] is created[0]
    compaction = next(extension for extension in captured["extensions"] if isinstance(extension, OnDemandCompaction))
    assert compaction.model is None
    instructions = next(extension for extension in captured["extensions"] if isinstance(extension, AgentsMdExtension))
    assert instructions.directory == config.workspace
    assert any(isinstance(extension, SkillExtension) for extension in captured["extensions"])
    assert not any(isinstance(extension, McpExtension) for extension in captured["extensions"])
    # The tool list follows the model, so the capability filter is part of the run.
    from zettcode.engine.extensions.capabilities import ModelCapabilities

    assert any(isinstance(extension, ModelCapabilities) for extension in captured["extensions"])
    # The prompt can offer "always allow" only because the runtime hands the
    # extension something to remember the command in.
    assert runtime.approval.storage is not None

    selected = runtime.use_model("Second")
    assert selected is second
    assert runtime.model is created[1]
    # The compaction budget belongs to the model, so it moves with the choice.
    assert runtime.compaction.max_tokens == second.compaction_max_tokens == 150_000
    assert runtime.compaction.keep_recent_tokens == second.compaction_keep_tokens == 37_500
    assert created[1].base_url == "http://tds.com:8787"
    assert created[1].token == "second"
    assert runtime.use_model("First") is first
    assert runtime.model is created[0]
    assert len(created) == 2

    with pytest.raises(ValueError, match="Ambiguous model"):
        runtime.use_model("shared-id")
    assert runtime.active_model is first
    assert runtime.use_model(second) is second
    assert runtime.model is created[1]
    with pytest.raises(ValueError, match="Unknown model"):
        runtime.use_model("missing")
    assert runtime.active_model is second

    await runtime.aclose()
    assert all(provider.closed for provider in created)


async def test_the_runtime_shares_one_permission_policy_with_the_layers_that_enforce_it(tmp_path, monkeypatch):
    """The level is one object: the shell sets it, and the deny and approval layers read it.

    A copy in either layer would let `/permission` change what the picker shows and
    not what the agent does, so the test holds the runtime to a single instance and
    to the order the layers need: deny before approval.
    """
    from zett_agent.extensions.shell_approval import ShellApprovalExtension

    from zettcode.engine.permission import Permission, ShellDenyExtension

    captured: dict[str, object] = {}

    async def fake_create_agent(model, **kwargs):
        captured["extensions"] = kwargs["extensions"]
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    monkeypatch.setattr("zettcode.config.DEFAULT_MCP_CONFIG", tmp_path / "absent-mcp.json")

    runtime = await runtime_module.ZettCodeEngine.create(_config_with(tmp_path))
    extensions = captured["extensions"]
    deny = next(item for item in extensions if isinstance(item, ShellDenyExtension))
    approval = next(item for item in extensions if isinstance(item, ShellApprovalExtension))

    assert deny._policy is runtime.policy
    assert approval.storage._policy is runtime.policy
    assert ordered(extensions).index(deny) < ordered(extensions).index(approval)
    assert runtime.permission is Permission.ASK, "a run starts by asking"

    assert runtime.use_permission(" SAFE ") is Permission.SAFE
    assert runtime.policy.level is Permission.SAFE, "the level the layers read is the one that was set"
    with pytest.raises(ValueError, match="Try one of: deny, ask, safe, full"):
        runtime.use_permission("yolo")
    assert runtime.permission is Permission.SAFE, "a refused name leaves the level alone"

    runtime.approve_all_shell_commands()
    assert runtime.permission is Permission.FULL, "the old entry point is the full rung"
    await runtime.aclose()


def ordered(extensions):
    """Return extensions in the order the agent invokes them: ascending priority, stable."""
    return sorted(extensions, key=lambda extension: extension.priority)


def test_the_configured_allow_all_mode_starts_a_run_at_full(tmp_path, monkeypatch):
    from zett_agent.extensions.shell_approval import ShellApprovalMode

    from zettcode.engine.permission import Permission

    monkeypatch.chdir(tmp_path)

    default = runtime_module.ZettCodeEngine.preview(_config_with(tmp_path))
    allowing = runtime_module.ZettCodeEngine.preview(_config_with(tmp_path, shell_approval=ShellApprovalMode.ALLOW_ALL))

    assert default.permission is Permission.ASK
    assert allowing.permission is Permission.FULL
    assert default.policy.workspace == tmp_path, "git is judged against this workspace"


def test_the_tool_the_prompt_names_for_editing_is_one_the_agent_really_has(tmp_path):
    """The library renamed ``replace_in_file`` to ``edit``; a prompt naming a tool that is not offered sends the
    model looking for it."""
    from zettcode.engine.extensions.files import CodingBundle

    names = {tool.name for tool in CodingBundle().tools}
    prompt = runtime_module.build_system_prompt(
        ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "s")
    )

    for named in ("edit", "write_file"):
        assert named in names and named in prompt
    assert {"read", "bash"} <= names and not {"view_image", "read_file", "delete_file"} & names
    assert "replace_in_file" not in prompt
