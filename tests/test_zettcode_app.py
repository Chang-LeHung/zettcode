"""End-to-end tests for the ZettCode application layer."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from math import ceil
from pathlib import Path

import pytest
from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.compaction import CompactedMessage
from zett_agent.extensions.events import MessageTiming
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_EVENT_NAME
from zett_agent.extensions.todo import TodoItem, TodoStatus, TodoWriteResult
from zett_agent.messages import (
    AssistantMessage,
    ImageContent,
    SystemMessage,
    TextContent,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from zett_agent.model import ModelRequest, ModelUsage, ReasoningEffort, ToolDefinition

from zettcode.app import Transcript, TranscriptSource, TranscriptView, ZettCodeApp
from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.context import ContextExtension, Tokenizer
from zettcode.app.agent.projection import TranscriptProjector
from zettcode.app.agent.rows import (
    BLINK_FRAMES,
    SWEEP_FRAMES,
    activity_glyph,
    clock_text,
    compact_path,
    duration_text,
    elapsed_text,
    sweep_step,
    terminal_safe,
)
from zettcode.app.agent.storage import SessionInfo, SessionStore
from zettcode.app.agent.usage import USAGE_EVENT_NAME, UsageExtension, UsageSnapshot
from zettcode.app.commands import Command, CommandResult
from zettcode.app.ui import app as app_module
from zettcode.app.ui import demo
from zettcode.app.ui.widgets import (
    WELCOME,
    ApprovalChoice,
    ApprovalPage,
    ContextPage,
    SessionsPage,
    bottom_panel,
    format_ago,
    help_text,
)
from zettcode.config import ModelConfig
from zettcode.plugins import BUILTIN_PLUGINS, PluginContainer, Plugins, ShellContext, UiBuilder
from zettcode.tui import DARK, LIGHT, Canvas, ListItem, ListPage, Rect, Span, Style, Text, TextLine, walk
from zettcode.tui.render import display_width
from zettcode.tui.testing import Harness, render_block


class FakeAgent:
    def __init__(self) -> None:
        self.emitted: list[tuple[object, object]] = []

    def emit_external_event(self, event, *, config=None) -> list[str]:
        self.emitted.append((event, config))
        return ["shell_approval"]


class FakeClient:
    def __init__(self, events: list[AgentEvent] | None = None, *, block: bool = False) -> None:
        self.agent = FakeAgent()
        self.events = events or []
        self.block = block
        self.event_dispatcher = None
        self.models: list[object] = []
        self.configs: list[object] = []
        self.efforts: list[object] = []
        self.messages: list[object] = []
        self.compactions: list[tuple[object, object]] = []

    async def stream(self, message, *, config=None, model=None, reasoning_effort=None):
        self.models.append(model)
        self.configs.append(config)
        self.efforts.append(reasoning_effort)
        self.messages.append(message)
        # The real client does not echo turns; the projector does, and only for
        # the prompts a reader typed. A compaction run's message is not one.
        if self.event_dispatcher is not None and isinstance(message, str):
            self.event_dispatcher.begin_turn(message)
        for event in self.events:
            if self.event_dispatcher is not None:
                await self.event_dispatcher.dispatch(event)
            yield event
        if self.block:
            await asyncio.sleep(3600)

    async def compact(self, *, config=None, model=None, metadata=None, tags=None):
        """Mirror ``AgentClient.compact``: one pass, its events dispatched in order."""
        self.compactions.append((config, model))
        session_id = config.session_id if config is not None else "session-0001"
        if self.event_dispatcher is not None:
            await self.event_dispatcher.dispatch(AgentEvent(AgentEventType.COMPACTION_STARTED, session_id))
            await self.event_dispatcher.dispatch(
                AgentEvent(AgentEventType.COMPACTION_TEXT_DELTA, session_id, delta="the parser was fixed")
            )
            await self.event_dispatcher.dispatch(
                AgentEvent(AgentEventType.COMPACTION_COMPLETED, session_id, applied=True)
            )
        if self.block:
            await asyncio.sleep(3600)
        return None


class FakePersistence:
    def __init__(self) -> None:
        self.sessions: list[SessionInfo] = []
        self.store: SessionStore | None = None

    async def list_sessions(self, limit: int | None = None):
        return self.sessions[:limit] if limit is not None else list(self.sessions)

    def read(self, session_id: str):
        if self.store is None:
            raise ValueError(f"Unknown session: {session_id}")
        return self.store.read(session_id)

    def session_title(self, session_id: str) -> str | None:
        if self.store is not None:
            return self.store.session_title(session_id)
        return next((info.title for info in self.sessions if info.session_id == session_id), None)

    async def set_title(self, session_id: str, title: str) -> None:
        if self.store is None:
            raise ValueError(f"Unknown session: {session_id}")
        await self.store.set_title(session_id, title)


class FakeTodos:
    def __init__(self) -> None:
        self.result = None
        self.queries: list[str] = []

    def todos(self, session_id: str):
        self.queries.append(session_id)
        return self.result


@dataclass
class FakeConfig:
    workspace: Path = Path("/tmp/workspace")
    models: tuple[ModelConfig, ...] = (
        ModelConfig(model="gpt-5-mini", token="test-token"),
        ModelConfig(model="gpt-4o", display_model="GPT-4o", token="test-token", multimodal=True),
    )
    reduced_motion: bool = False
    compaction_max_tokens: int = 128_000
    plugins_enabled: bool = True
    disabled_plugins: tuple[str, ...] = ()


@dataclass
class FakeRuntime:
    client: object
    session_id: str = "session-0001"
    persistence: FakePersistence = field(default_factory=FakePersistence)
    todos: FakeTodos = field(default_factory=FakeTodos)
    usage: UsageExtension = field(default_factory=UsageExtension)
    context: ContextExtension = field(default_factory=ContextExtension)
    effort: ReasoningEffort = ReasoningEffort.MEDIUM
    # A zero deadline keeps the fake offline: the estimate stands in for tiktoken.
    tokenizer: Tokenizer = field(default_factory=lambda: Tokenizer(deadline=0.0))
    config: FakeConfig = field(default_factory=FakeConfig)
    plugins: Plugins = field(default_factory=Plugins)
    active_model: ModelConfig = field(init=False)
    model: object = field(init=False)
    auto_approved: bool = field(default=False, init=False)
    start_calls: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.active_model = self.config.models[0]
        self.model = self.active_model.model

    async def start(self) -> FakeRuntime:
        """A real runtime builds its provider and client here; this one is ready."""
        self.start_calls += 1
        return self

    @property
    def started(self) -> object:
        """Mirror the real runtime's client accessor."""
        return self.client

    @property
    def provider(self) -> object:
        """Mirror the real runtime's provider accessor."""
        return self.model

    def set_event_dispatcher(self, dispatcher: object) -> None:
        """Mirror the real runtime's dispatcher seam."""
        self.client.event_dispatcher = dispatcher

    def use_model(self, name: str | ModelConfig) -> ModelConfig:
        entry = next(
            (
                entry
                for entry in self.config.models
                if entry is name or (isinstance(name, str) and name in (entry.model, entry.display_model))
            ),
            None,
        )
        if entry is None:
            raise ValueError(f"Unknown model: {name}")
        self.active_model = entry
        self.model = entry.model
        return entry

    def new_session(self) -> str:
        self.session_id = "session-0002"
        return self.session_id

    def use_session(self, session_id: str) -> None:
        self.session_id = session_id

    def approve_all_shell_commands(self) -> None:
        self.auto_approved = True

    def use_effort(self, name):
        try:
            self.effort = ReasoningEffort(name.strip().lower())
        except ValueError:
            levels = ", ".join(level.value for level in ReasoningEffort)
            raise ValueError(f"Unknown reasoning effort: {name}. Try one of: {levels}") from None
        return self.effort


def rows_and_commands(
    *,
    extra: tuple[tuple[str, str, UiBuilder], ...] = (),
    override: tuple[tuple[str, str, str, UiBuilder], ...] = (),
    commands: tuple[Command, ...] = (),
    failures: tuple[str, ...] = (),
) -> Plugins:
    """The shell's builtin rows plus the segments and commands one test adds.

    ``extra`` appends a segment to a side; ``override`` registers under a name
    the builtin already uses, which replaces it in place — the same merge the
    loader performs when a plugin loads after the builtins.
    """
    container = PluginContainer(FakeConfig())
    for plugin in BUILTIN_PLUGINS:
        plugin.activate(container)
        for region, side, name, builder in plugin.ui_slots():
            container.slots.add(region, side, name, builder)
    for region, side, builder in extra:
        getattr(container, f"register_{region}_{side}")(builder)
    for region, side, name, builder in override:
        container.slots.add(region, side, name, builder)
    return Plugins(commands=commands, rows=container.rows, failures=failures)


def build_app(
    events: list[AgentEvent] | None = None,
    *,
    block: bool = False,
    plugins: Plugins | None = None,
) -> ZettCodeApp:
    app = ZettCodeApp(
        ZettCodeAgent(FakeRuntime(FakeClient(events, block=block), plugins=plugins or rows_and_commands()))
    )
    app.app.resize(60, 14)
    app.app.mount()
    return app


def _presented_page(app: ZettCodeApp) -> ListPage:
    """Return the page on top of the stack, wherever the shell wrapped it."""
    return next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, ListPage))


def _approval_page(app: ZettCodeApp) -> ApprovalPage:
    """Return the approval panel on top of the stack."""
    return next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, ApprovalPage))


def _sessions_page(app: ZettCodeApp) -> SessionsPage:
    """Return the session panel on top of the stack."""
    return next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, SessionsPage))


def test_welcome_mark_is_compact_and_readable_in_both_themes():
    assert len(WELCOME.splitlines()) == 5
    assert WELCOME.splitlines()[0].strip() == "╭─────┬─────╮"
    assert WELCOME.splitlines()[2].split("╯", 1)[0].strip() + "╯" == "╰─────┴─────╯"
    for theme in (DARK, LIGHT):
        transcript = Transcript()
        transcript.welcome(WELCOME)
        source = TranscriptSource(transcript, theme=theme)
        logo = source.line(0, 60)
        title = source.line(1, 60)
        subtitle = source.line(2, 60)

        assert "✦" in title.text
        assert title.text.index("ZettCode") == subtitle.text.index("A focused")
        assert logo.spans[0].style.foreground == theme.accent
        assert title.spans[0].style.foreground == theme.accent
        assert title.spans[1].style.foreground == theme.text
        assert subtitle.spans[1].style.foreground == theme.subtle


async def test_agent_stream_uses_selected_session_and_model():
    runtime = FakeRuntime(FakeClient())
    agent = ZettCodeAgent(runtime)
    agent.use_session("session-0003")
    agent.use_model("GPT-4o")

    async for _ in agent.stream(("hello",)):
        pass

    assert runtime.client.configs[-1].session_id == "session-0003"
    assert runtime.client.models[-1] == "gpt-4o"
    assert agent.models == runtime.config.models
    assert agent.workspace == runtime.config.workspace


async def test_projector_maps_events_into_ordered_blocks():
    transcript = Transcript()
    projector = TranscriptProjector(transcript)
    projector.begin_turn("inspect the project")
    await projector.dispatch(AgentEvent(AgentEventType.REASONING_DELTA, "s", delta="checking"))
    await projector.dispatch(
        AgentEvent(
            AgentEventType.TOOL_STARTED,
            "s",
            tool_calls=[ToolCall("1", "glob", {"pattern": "*.py"}), ToolCall("2", "grep", {"pattern": "x"})],
        )
    )
    await projector.dispatch(
        AgentEvent(
            AgentEventType.TOOL_COMPLETED,
            "s",
            message=ToolMessage(tool_call_id="1", name="glob", content="a.py\nb.py"),
        )
    )
    await projector.dispatch(AgentEvent(AgentEventType.TEXT_DELTA, "s", delta="done"))

    assert [entry.kind for entry in transcript.entries] == ["user", "thinking", "tool", "tool", "answer"]

    collapsed = "\n".join(_rendered(transcript, 40))

    assert "inspect the project" in collapsed
    assert "checking" not in collapsed
    # The chain phrases the rows instead of repeating the tool names.
    assert "Listed *.py" in collapsed
    assert "Searched x" in collapsed
    assert "done" in collapsed

    assert transcript.toggle_latest_thinking()
    assert "checking" in "\n".join(_rendered(transcript, 40))


def test_a_placeholder_is_shown_before_anything_is_known():
    transcript = Transcript(clock=lambda: 0.0)

    transcript.begin_turn("slow question")
    rendered = "\n".join(_rendered(transcript, 40))

    assert [entry.kind for entry in transcript.entries] == ["user", "pending"]
    assert "Processing" in rendered

    thinking = transcript.start_thinking()
    transcript.append_thinking("now it is reasoning")

    assert [entry.kind for entry in transcript.entries] == ["user", "thinking"]
    assert thinking.kind == "thinking"

    assert transcript.toggle_latest_thinking()
    assert "now it is reasoning" in "\n".join(_rendered(transcript, 40))


def test_the_placeholder_is_removed_once_output_starts():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    transcript.append_answer("an answer")

    assert [entry.kind for entry in transcript.entries] == ["user", "answer"]
    assert "Processing" not in "\n".join(_rendered(transcript, 40))

    finished = Transcript(clock=lambda: 0.0)
    finished.begin_turn("question")
    finished.complete_thinking()

    assert [entry.kind for entry in finished.entries] == ["user"]


def test_a_request_waits_again_after_every_tool_batch():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    transcript.start_tool("1", "read_file", {"path": "a.py"})
    assert [entry.kind for entry in transcript.entries] == ["user", "tool"]

    transcript.complete_tool("1", "content")

    # The loop calls the model again once the batch has results, so the wait row
    # comes back below the rows it belongs to.
    assert [(entry.kind, getattr(entry, "title", "")) for entry in transcript.entries] == [
        ("user", ""),
        ("tool", "Read a.py"),
        ("pending", "Processing"),
    ]
    assert transcript.entries[-1].status == "running"

    transcript.append_answer("done")

    assert [entry.kind for entry in transcript.entries] == ["user", "tool", "answer"]


def test_a_wait_row_waits_for_the_whole_tool_batch():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    transcript.start_tool("1", "read_file", {"path": "a.py"})
    transcript.start_tool("2", "read_file", {"path": "b.py"})

    transcript.complete_tool("1", "content")

    # One result is not the batch: the model is not called until they all land.
    assert [entry.kind for entry in transcript.entries] == ["user", "tool", "tool"]

    transcript.complete_tool("2", "content")

    assert [entry.kind for entry in transcript.entries] == ["user", "tool", "tool", "pending"]


def test_terminal_safe_normalises_line_endings_before_replacing_controls():
    # CRLF and a lone carriage return are line breaks here, not stray bytes: a
    # tool that shells out to curl would otherwise end every line with a glyph.
    assert terminal_safe("a\r\nb\rc") == "a\nb\nc"
    assert terminal_safe("HTTP/1.1 200 OK\r\nServer: x\r\n") == "HTTP/1.1 200 OK\nServer: x\n"
    assert terminal_safe("coloured \x1b[31mred\x1b[0m") == "coloured red"
    assert terminal_safe("tab\there") == "tab here"
    assert terminal_safe("x\ty") == "x   y"
    assert "\ufffd" in terminal_safe("bell\x07")
    assert "\ufffd" not in terminal_safe("ok\r\n")


def test_a_tool_row_prints_crlf_output_without_replacement_glyphs():
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    transcript.start_tool("1", "run_shell", {"command": "curl -i localhost"})
    transcript.complete_tool("1", "HTTP/1.1 200 OK\r\nServer: ZettCode/1.0\r\n\r\nbody\r\n")

    rendered = "\n".join(_rendered(transcript, 60))

    assert "HTTP/1.1 200 OK" in rendered
    assert "Server: ZettCode/1.0" in rendered
    assert "\ufffd" not in rendered


def test_provider_wrappers_and_chat_preambles_never_reach_the_transcript():
    transcript = Transcript()
    transcript.begin_turn("question")
    transcript.append_thinking("<thinking>weighing options</thinking>")
    transcript.toggle_latest_thinking()
    transcript.append_answer("Assistant: ")  # the fragment that opens the answer
    transcript.append_answer("here is the fix")

    rendered = "\n".join(_rendered(transcript, 60))

    assert "weighing options" in rendered
    assert "thinking>" not in rendered
    assert "Assistant:" not in rendered
    assert "here is the fix" in rendered


async def test_a_waiting_row_appears_as_soon_as_a_turn_starts():
    app = build_app(block=True)
    harness = _harness(app)

    harness.write("slow question")
    harness.press("enter")
    await asyncio.sleep(0.02)
    text = harness.render().text

    assert "slow question" in text
    assert "Processing" in text
    assert app.transcript.frame > 0
    assert "running" in text


def test_the_running_marker_blinks_between_two_glyphs():
    bright = activity_glyph(0)
    faint = activity_glyph(BLINK_FRAMES)

    assert bright != faint
    # Each state holds for a whole half-blink, so the marker does not flicker at
    # the tick rate, and both are one column wide: the label never shifts.
    assert activity_glyph(BLINK_FRAMES - 1) == bright
    assert activity_glyph(BLINK_FRAMES * 2 - 1) == faint
    assert activity_glyph(BLINK_FRAMES * 2) == bright
    assert display_width(bright) == display_width(faint) == 1


@pytest.mark.parametrize(
    ("thinking", "needle", "label"),
    [
        (False, "Processing", "Processing"),
        (True, "Thinking", "Thinking  working"),
    ],
)
def test_a_running_wording_carries_a_travelling_highlight(thinking, needle, label):
    transcript = Transcript(clock=lambda: 0.0)
    transcript.begin_turn("question")
    if thinking:
        transcript.start_thinking()
    source = TranscriptView(transcript, theme=DARK).transcript_source

    def wording(frame: int) -> list:
        transcript.frame = frame
        transcript.version += 1
        rows = [source.line(index, 50) for index in range(source.count(50))]
        row = next(row for row in rows if needle in row.text)
        # The first run is the left margin merged with the marker; the rest is
        # the wording, split into one run per brightness step.
        return list(row.spans[1:])

    def peak_column(frame: int) -> int:
        column = 0
        for span in wording(frame):
            if span.style.foreground == DARK.text:
                return column
            column += display_width(span.text)
        return -1

    # The highlight arrives from the left and moves one column per step.
    def frame_for(step: int) -> int:
        """Return the first frame at which the highlight has reached ``step``."""
        return ceil(step * SWEEP_FRAMES)

    assert sweep_step(frame_for(5)) == 5
    assert peak_column(frame_for(5)) == 2
    assert peak_column(frame_for(8)) == 5

    # Nothing ever goes dark: every run keeps a colour from the bright end of
    # the palette, and the text itself never changes or shifts.
    for frame in (frame_for(step) for step in range(14)):
        runs = wording(frame)
        assert all(run.style.dim is False for run in runs)
        assert all(run.style.foreground != DARK.muted for run in runs)
        assert "".join(run.text for run in runs) == label


def test_the_blink_demo_keeps_frames_coming_and_advances_the_blink():
    transcript = Transcript(clock=lambda: 12.34)
    app = demo.build(transcript)
    root = app.screens.top.widget

    assert isinstance(root, demo.Blinking)
    before = transcript.version
    root.on_tick()

    # The counter is derived from the clock, one step per ANIMATION_SECONDS,
    # rather than counted per tick: the pace cannot depend on the frame rate.
    assert transcript.frame == 123
    assert transcript.version == before + 1


async def test_the_blink_demo_script_walks_a_turn():
    transcript = Transcript()
    turn = asyncio.create_task(demo.script(transcript))
    try:
        await asyncio.sleep(0)
        assert [entry.kind for entry in transcript.entries] == ["user", "pending"]
        assert transcript.entries[-1].status == "running"
    finally:
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


def test_the_blink_demo_can_be_slowed_down_while_it_runs(monkeypatch):
    monkeypatch.setattr(demo.rows_module, "SWEEP_FRAMES", 4.0)
    harness = Harness(app=demo.build())

    harness.press("]")
    assert demo.rows_module.SWEEP_FRAMES == 3.5
    assert "350 ms per column" in harness.render().text

    harness.press("[")
    harness.press("[")
    assert demo.rows_module.SWEEP_FRAMES == 4.5


async def test_app_streams_a_prompt_into_the_transcript():
    events = [
        AgentEvent(AgentEventType.REASONING_STARTED, "s"),
        AgentEvent(AgentEventType.REASONING_DELTA, "s", delta="weighing options"),
        AgentEvent(AgentEventType.REASONING_COMPLETED, "s"),
        AgentEvent(AgentEventType.TEXT_DELTA, "s", delta="# Result\n"),
        AgentEvent(AgentEventType.TEXT_DELTA, "s", delta="**bold** finding"),
        AgentEvent(AgentEventType.RUN_COMPLETED, "s", message=AssistantMessage(content="done")),
    ]
    app = build_app(events)
    harness = _harness(app)

    harness.write("find the bug")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    text = harness.render().text

    # The turn footer pushes the prompt out of the short test viewport, so the
    # prompt is checked in the model and the answer in what is on screen.
    assert any(entry.kind == "user" and entry.text == "find the bug" for entry in app.transcript.entries)
    assert "Result" in text
    assert "bold finding" in text
    assert "Processed for " in text
    assert app.busy is False


async def test_the_runtime_starts_with_the_first_turn_not_before():
    """The shell paints from the preview; the provider waits for a message."""
    app = build_app()
    harness = _harness(app)
    runtime = app.agent.runtime

    assert runtime.start_calls == 0

    harness.write("hello")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert runtime.start_calls == 1


async def test_plugin_commands_join_the_shell_and_run():
    """A command a plugin registered is offered last and handled like any other."""

    async def greet(argument: str) -> CommandResult:
        return CommandResult(notification=f"hello {argument}".strip())

    plugins = rows_and_commands(commands=(Command("/greet", "say hello", "plugin", greet),))
    app = build_app(plugins=plugins)
    harness = _harness(app)

    assert app.commands[-1].name == "/greet"
    assert "- `/greet` — say hello (`plugin`)" in help_text(app.commands)

    harness.write("/greet world")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert "hello world" in harness.render().text


async def test_plugin_load_failures_are_shown_at_startup():
    """A plugin that cannot load is reported instead of disappearing silently."""
    app = build_app(plugins=rows_and_commands(failures=("greeter: bad config",)))

    assert any(entry.text == "plugin: greeter: bad config" for entry in app.transcript.entries)


async def test_plugin_segments_join_the_header_and_status_rows():
    """A segment is drawn where it asked to be, and reads the current state."""
    seen: list[ShellContext] = []

    def header(context: ShellContext) -> str:
        seen.append(context)
        return "plug-header"

    def status(context: ShellContext) -> TextLine:
        muted = Style(foreground=context.display.theme.muted, bold=True)
        return TextLine((Span("plug-status", muted),))

    plugins = rows_and_commands(extra=(("header", "right", header), ("status", "right", status)))
    app = build_app(plugins=plugins)
    text = _harness(app).render().text
    status_line = app._status_right().text

    assert "plug-header" in text
    # A plugin segment follows the built-in content of its row.
    assert text.index("gpt-5-mini") < text.index("plug-header")
    assert status_line.index("^C stop") < status_line.index("plug-status")
    context = seen[0]
    assert context.model.name == "gpt-5-mini" and context.model.config.model == "gpt-5-mini"
    assert context.session.workspace == app.agent.workspace
    assert context.session.name == "New session" and context.session.title is None
    assert context.display.theme is app.app.theme
    assert context.model.efforts and context.model.effort in context.model.efforts
    assert context.activity.auto_shell is False and context.activity.busy is False
    assert context.activity.status == "ready" and context.activity.tasks == ()
    assert context.display.scrolled_up is False
    assert (context.display.width, context.display.height) == (60, 14)
    assert context.display.screen == "main"
    assert context.config is app.agent.runtime.config


async def test_a_broken_plugin_segment_only_drops_itself():
    """A builder that raises loses its own segment, not the frame."""

    def boom(context: ShellContext) -> str:
        raise RuntimeError("nope")

    plugins = rows_and_commands(extra=(("status", "right", boom), ("status", "right", lambda context: "still here")))
    app = build_app(plugins=plugins)

    assert "still here" in _harness(app).render().text


async def test_a_segment_that_returns_nothing_leaves_the_row_untouched():
    """None or an empty string draws no separator either."""
    plugins = rows_and_commands(extra=(("header", "right", lambda context: None),))
    decorated = build_app(plugins=plugins)._header_left()
    plain = build_app()._header_left()

    assert decorated.text == plain.text
    assert decorated.spans == plain.spans


async def test_a_plugin_can_take_a_builtin_row_side_over():
    """Registering under the builtin's slot name replaces it, side by side."""
    plugins = rows_and_commands(override=(("status", "left", "status_left", lambda context: "mine"),))
    app = build_app(plugins=plugins)

    assert app._status_left().text == "mine"
    # The slots it did not touch keep their builtin content.
    assert "gpt-5-mini" in app._header_right().text
    assert "^C stop" in app._status_right().text


async def test_a_declared_builder_can_take_the_side_over():
    """Returning ``(line, True)`` drops what the segments before it painted."""

    def drawn(context: ShellContext) -> tuple[str, bool]:
        return "mine", True

    plugins = rows_and_commands(extra=(("status", "left", drawn), ("status", "left", lambda context: "beside")))
    app = build_app(plugins=plugins)

    assert app._status_left().text == "mine · beside"
    assert "New session" not in app._status_left().text  # the builtin segment went away


async def test_the_compact_command_compacts_now():
    """`/compact` asks the client for one pass, and the pass keeps out of the session."""
    app = build_app()
    harness = _harness(app)

    harness.write("/compact")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    runtime = app.agent.runtime
    ((config, model),) = runtime.client.compactions
    assert config.session_id == app.agent.session_id  # the pass runs on the active session
    assert model is runtime.provider
    assert runtime.start_calls == 1
    # The pass dispatches its own events, so the row animates like every other run.
    assert any(entry.kind == "thinking" and entry.text == "the parser was fixed" for entry in app.transcript.entries)
    # It is not a turn: nothing was echoed as a user message.
    assert not any(entry.kind == "user" for entry in app.transcript.entries)
    assert runtime.client.messages == []


async def test_a_second_compact_without_a_new_message_is_refused(tmp_path):
    """Nothing new since the checkpoint: the command reports it instead of running."""
    store = SessionStore(tmp_path)
    node = await store.append("session-0001", "request-1", UserMessage(content="the parser crashes"))
    await store.checkpoint("session-0001", CompactedMessage(content="summary"), node, 0)

    app = build_app()
    app.agent.runtime.persistence.store = store
    harness = _harness(app)

    harness.write("/compact")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    errors = [entry for entry in app.transcript.entries if entry.kind == "notice" and entry.text.startswith("Already")]
    assert [entry.text for entry in errors] == ["Already compacted; send a message before compacting again"]
    assert app.agent.runtime.client.compactions == []  # the pass never ran


async def test_busy_work_keeps_the_frames_coming():
    """A waiting row animates from the frame counter, so work holds the token."""
    app = build_app(block=True)
    harness = _harness(app)

    harness.write("/compact")
    harness.press("enter")
    await asyncio.sleep(0)

    assert "activity" in app.app.scheduler.animations

    app.task.cancel()
    await asyncio.gather(app.task, return_exceptions=True)

    assert app.app.scheduler.animations == ()


async def test_the_projector_streams_a_compaction_into_its_own_row():
    """Compaction events drive a row like reasoning, plus the outcome notice."""
    app = build_app()

    await app.projector.dispatch(AgentEvent(AgentEventType.COMPACTION_STARTED, "session-0001"))
    await app.projector.dispatch(
        AgentEvent(AgentEventType.COMPACTION_TEXT_DELTA, "session-0001", delta="the parser was fixed")
    )
    await app.projector.dispatch(AgentEvent(AgentEventType.COMPACTION_COMPLETED, "session-0001", applied=True))

    rows = [entry for entry in app.transcript.entries if entry.kind == "thinking"]
    assert [row.title for row in rows] == ["Compacting"]
    assert rows[0].text == "the parser was fixed"
    assert rows[0].status == "completed"
    assert rows[0].duration is not None
    assert any(
        entry.kind == "notice" and "Context compaction applied" in entry.text for entry in app.transcript.entries
    )


async def test_a_failed_request_shows_the_reason_not_the_task_group():
    """An MCP server that is down fails the turn inside a task group."""
    app = build_app()
    harness = _harness(app)

    async def failing(parts):
        raise ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [ExceptionGroup("unhandled errors in a TaskGroup", [ConnectionError("All connection attempts failed")])],
        )
        yield  # pragma: no cover - unreachable, and what makes this a generator

    app.agent.stream = failing

    harness.write("你有哪些 skill")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    notices = [entry.text for entry in app.transcript.entries if entry.kind == "notice"]
    assert any(text == "error: All connection attempts failed" for text in notices)
    assert not any("TaskGroup" in text for text in notices)
    failed = [entry for entry in app.transcript.entries if entry.kind == "notice" and entry.level == "error"]
    assert any(entry.text.startswith("error: ") for entry in failed)


def test_elapsed_text_shows_hours_minutes_and_seconds():
    assert elapsed_text(0.4) == "0s"
    assert elapsed_text(3.2) == "3s"
    assert elapsed_text(59.6) == "1m 0s"
    assert elapsed_text(22 * 60 + 30) == "22m 30s"
    assert elapsed_text(59 * 60 + 59) == "59m 59s"
    assert elapsed_text(3600) == "1h 0m 0s"
    assert elapsed_text(2 * 3600 + 5 * 60 + 7) == "2h 5m 7s"
    assert elapsed_text(24 * 3600 + 1) == "24h 0m 1s"
    assert elapsed_text(-5) == "0s"


def test_row_durations_count_tenths_of_a_second():
    # A tenth is enough to see a row move, and milliseconds would change the
    # column's width on every repaint.
    assert duration_text(0.0) == "0.0 s"
    assert duration_text(0.34) == "0.3 s"
    assert duration_text(12.36) == "12.4 s"
    assert duration_text(None) == "done"

    now = [0.0]
    transcript = Transcript(clock=lambda: now[0])
    transcript.begin_turn("question")
    now[0] = 1.25
    transcript.advance_frame()

    assert "Processing  1.2 s" in "\n".join(_rendered(transcript, 40))

    # The reasoning row is read the same way, running or finished.
    now[0] = 0.0
    thinking = Transcript(clock=lambda: now[0])
    thinking.begin_turn("question")
    thinking.start_thinking()
    now[0] = 1.25
    thinking.advance_frame()

    assert "Thinking  1.2 s" in "\n".join(_rendered(thinking, 40))

    thinking.complete_thinking()

    assert "Thinking  1.2 s" in "\n".join(_rendered(thinking, 40))


def test_clock_text_formats_a_local_reading():
    assert clock_text(datetime(2026, 10, 3, 9, 5)) == "09:05"
    assert clock_text(datetime(2026, 10, 3, 23, 59)) == "23:59"


async def test_each_turn_reports_how_long_it_took(monkeypatch):
    app = build_app()
    harness = _harness(app)
    monkeypatch.setattr(app_module, "monotonic", iter([100.0, 131.5]).__next__)
    monkeypatch.setattr(app_module, "clock_text", lambda: "13:14")

    harness.write("find the bug")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert any(
        entry.kind == "notice" and entry.text == "Processed for 32s \u00b7 13:14" for entry in app.transcript.entries
    )
    assert "Processed for 32s \u00b7 13:14" in harness.render().text


async def test_app_refuses_a_second_prompt_and_ctrl_c_stops_the_first():
    app = build_app(block=True)
    harness = _harness(app)

    harness.write("first")
    harness.press("enter")
    await asyncio.sleep(0)
    harness.write("second")
    harness.press("enter")
    await asyncio.sleep(0)

    assert app.busy is True
    assert any("busy" in entry.text for entry in app.transcript.entries if entry.kind == "notice")

    harness.press("ctrl_c")
    await asyncio.wait_for(app.task, 2.0)

    assert app.busy is False
    assert any("stopped" in entry.text for entry in app.transcript.entries if entry.kind == "notice")


def _palette(theme) -> set[str]:
    """Return every colour one palette can paint, code tokens included."""
    values = {getattr(theme, attribute.name) for attribute in fields(theme) if attribute.name != "code"}
    values |= {getattr(theme.code, attribute.name) for attribute in fields(theme.code)}
    return {value for value in values if isinstance(value, str)}


def _run_context(session_id: str = "session-0001") -> AgentRunContext:
    """Build the run context a hook receives, for tests that call one directly."""
    return AgentRunContext(AgentRunConfig(session_id=session_id), AgentState(), {})


def test_the_terminal_title_follows_the_session():
    """The tab says what the session is about, like an editor tab does."""
    app = build_app()

    assert app.app.title() == "zettcode \u00b7 workspace"  # no session title yet

    app._session_title = "Fix the parser crash"

    assert app.app.title() == "Fix the parser crash"


async def test_ctrl_v_attaches_the_clipboard_image_to_the_prompt(monkeypatch):
    app = build_app()
    app.agent.runtime.active_model = app.agent.runtime.config.models[1]  # GPT-4o takes images
    harness = _harness(app)
    monkeypatch.setattr(app_module, "read_image", lambda: (b"png-bytes", "image/png"))

    harness.write("what is wrong here?")
    harness.press("ctrl_v")

    assert app.composer.text == "what is wrong here?[image #1]"
    assert harness.render().text.count("[image #1]") >= 1

    harness.press("enter")
    await asyncio.sleep(0.05)

    message = app.agent.runtime.client.messages[-1]
    assert isinstance(message, UserMessage)
    assert message.text == "what is wrong here?[image #1]"
    assert len(message.parts) == 2
    assert message.parts[1].source.data == b"png-bytes"


async def test_a_prompt_keeps_images_where_the_chips_were_written(monkeypatch):
    app = build_app()
    app.agent.runtime.active_model = app.agent.runtime.config.models[1]
    harness = _harness(app)
    monkeypatch.setattr(app_module, "read_image", lambda: (b"png-bytes", "image/png"))

    harness.write("this ")
    harness.press("ctrl_v")
    harness.write(" is broken")
    harness.press("enter")
    await asyncio.sleep(0.05)

    message = app.agent.runtime.client.messages[-1]
    assert isinstance(message, UserMessage)
    assert [part.text if isinstance(part, TextContent) else "image" for part in message.parts] == [
        "this [image #1]",
        "image",
        " is broken",
    ]


async def test_a_second_ctrl_v_adds_a_second_image(monkeypatch):
    app = build_app()
    app.agent.runtime.active_model = app.agent.runtime.config.models[1]
    harness = _harness(app)
    pending = [(b"first", "image/png"), (b"second", "image/png")]
    monkeypatch.setattr(app_module, "read_image", lambda: pending.pop(0))

    harness.press("ctrl_v")
    harness.press("ctrl_v")
    harness.write("compare")
    harness.press("enter")
    await asyncio.sleep(0.05)

    message = app.agent.runtime.client.messages[-1]
    assert isinstance(message, UserMessage)
    assert [part.source.data for part in message.parts if isinstance(part, ImageContent)] == [
        b"first",
        b"second",
    ]


async def test_attaching_says_so_when_there_is_nothing_to_attach(monkeypatch):
    app = build_app()
    app.agent.runtime.active_model = app.agent.runtime.config.models[1]
    harness = _harness(app)
    monkeypatch.setattr(app_module, "read_image", lambda: None)

    harness.press("ctrl_v")

    assert app.composer.text == ""
    assert any("no image on the clipboard" in getattr(entry, "text", "") for entry in app.transcript.entries)


async def test_a_model_without_image_input_refuses_an_attachment(monkeypatch):
    app = build_app()  # the default model is text-only
    harness = _harness(app)
    monkeypatch.setattr(app_module, "read_image", lambda: (b"png-bytes", "image/png"))

    harness.press("ctrl_v")

    assert app.composer.text == ""
    refused = [entry for entry in app.transcript.entries if "does not take images" in getattr(entry, "text", "")]
    assert refused and all(entry.level == "error" for entry in refused)


async def test_a_pasted_image_is_refused_by_a_model_that_cannot_read_it():
    """A base64 paste never goes past the clipboard, so the model is checked here."""
    app = build_app()  # the default model is text-only
    harness = _harness(app)
    data = b"\x89PNG\r\n\x1a\n" + b"pixels" * 60
    harness.paste("data:image/png;base64," + base64.b64encode(data).decode())

    harness.press("enter")
    await asyncio.sleep(0.05)

    assert app.agent.runtime.client.messages == []
    assert app.composer.text == "[image #1]"  # the draft is kept so it can be removed
    refused = [entry for entry in app.transcript.entries if "does not take images" in getattr(entry, "text", "")]
    assert refused and all(entry.level == "error" for entry in refused)


async def test_the_title_command_names_the_session(tmp_path):
    store = SessionStore(tmp_path)
    app = build_app()
    app.agent.runtime.persistence.store = store
    harness = _harness(app)

    harness.write("/title")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert any("no title yet" in entry.text for entry in app.transcript.entries)

    harness.write("/title  Fix the parser crash  ")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    # Trimmed, stored, and shown without waiting for the next turn.
    assert store.session_title("session-0001") == "Fix the parser crash"
    assert "Fix the parser crash" in app._status_left().text

    harness.write("/title")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert any("Fix the parser crash" in entry.text for entry in app.transcript.entries)

    harness.write("/title " + "x" * 300)
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert any("between 1 and" in entry.text for entry in app.transcript.entries)


async def test_the_context_command_reports_what_the_request_carries():
    app = build_app()
    harness = _harness(app)

    harness.write("/context")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    # Nothing has been assembled yet, so the command says so instead of showing a page of zeroes.
    assert app.app.screens.top.name != app_module.PAGE_SCREEN
    assert any("No request yet" in entry.text for entry in app.transcript.entries)

    request = ModelRequest(
        messages=(
            SystemMessage(content="You are ZettCode, a focused coding agent. " * 20),
            SystemMessage(content="# Filesystem environment"),
            UserMessage(content="add a --json flag"),
        ),
        tools=(ToolDefinition(name="read_file", description="read a file", parameters={"type": "object"}),),
    )
    await app.agent.runtime.context.before_model(_run_context(), request)

    harness.write("/context")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, ContextPage))
    assert [item.label for item in page.list.items] == [
        "Source",
        "System prompt",
        "Environment notes",
        "Tool schemas",
        "User messages",
    ]
    # The heading row is a row like any other, so its words sit over the
    # numbers; it is disabled, which is what keeps the selection off it.
    assert page.list.items[0].disabled is True
    assert page.list.current.label == "System prompt"
    text = harness.render().text
    assert "Context" in text and "tokens" in text
    # The title carries the window; the rows carry shares of the context.
    assert page.title.startswith("Context  ") and page.title.endswith(" / 128,000 tokens")
    # The window share is not repeated here; the rows carry the context shares,
    # which add up to the whole of what the next request would send.
    assert "%" not in page.title
    # The first row is the heading; every row under it is a share of the context.
    shares = [float(item.description.split("%")[0]) for item in page.list.items[1:]]
    assert 99.0 <= sum(shares) <= 101.0
    assert all(item.description.endswith(")") for item in page.list.items[1:])
    # The fake runtime never loads tiktoken, so the page has to admit the estimate.
    assert "chars/token" in text


async def test_resuming_a_session_makes_it_measurable_before_the_next_reply(tmp_path):
    """`/context` answers for a restored session, not just one that ran here."""
    """`/context` answers for a restored session, not just one that ran here."""
    store = SessionStore(tmp_path)
    await store.append("previous", "req", UserMessage(content="an earlier question"))
    await store.append("previous", "req", AssistantMessage(content="an earlier answer"))
    app = build_app()
    app.agent.runtime.persistence.store = store
    harness = _harness(app)

    harness.write("/use previous")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    harness.write("/context")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, ContextPage))
    assert [item.label for item in page.list.items] == [
        "Source",
        "System prompt",
        "User messages",
        "Assistant messages",
    ]
    # Nothing has been sent in this process, so the notes and tools are unknown.
    assert "notes and tools pending" in harness.render().text


async def test_the_effort_command_sets_the_level_the_next_request_carries():
    app = build_app()
    harness = _harness(app)

    harness.write("/effort XHIGH")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.effort == "xhigh"
    assert app._header_right().text.strip() == "gpt-5-mini \u00b7 xhigh"  # the header carries it

    harness.write("go")
    harness.press("enter")
    await asyncio.sleep(0.05)
    assert app.agent.runtime.client.efforts[-1] is ReasoningEffort.XHIGH

    harness.write("/effort faster")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert any("Unknown reasoning effort: faster" in getattr(entry, "text", "") for entry in app.transcript.entries)
    assert app.agent.effort == "xhigh"  # a refused level leaves the current one alone


async def test_switching_effort_announces_it_in_the_conversation():
    app = build_app()
    harness = _harness(app)

    harness.write("/effort high")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert any(
        entry.kind == "announcement" and entry.text == "Reasoning effort changed from medium to high."
        for entry in app.transcript.entries
    )

    # Picking the level already in force adds no second row.
    harness.write("/effort HIGH")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert [entry.text for entry in app.transcript.entries if entry.kind == "announcement"] == [
        "Reasoning effort changed from medium to high."
    ]


async def test_the_effort_command_opens_a_picker_over_the_levels():
    app = build_app()
    harness = _harness(app)

    harness.write("/effort")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, ListPage))
    assert [item.value for item in page.list.items] == list(app.agent.efforts)
    assert page.list.current.value == "medium"  # the level in force is highlighted

    harness.press("down")  # medium -> high
    harness.press("enter")

    assert app.agent.effort == "high"
    assert app.app.screens.top.name == "main"


async def test_the_theme_command_opens_a_panel_and_applies_the_choice():
    app = build_app()
    harness = _harness(app)

    harness.write("/theme")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, ListPage))
    assert app.app.screens.top.name == "page"
    assert [item.value for item in page.list.items] == ["dark", "light"]
    assert page.list.current.value == "dark"  # the active palette is highlighted
    assert harness.render().text.count("green-leaning") == 2

    harness.press("down")
    harness.press("enter")

    assert app.app.theme is LIGHT
    assert app.app.screens.top.name == "main"
    assert app.app.focused_widget() is app.composer


async def test_switching_the_theme_repaints_every_view():
    """No view keeps a cached colour from the palette that was active before."""
    app = build_app()
    harness = _harness(app)
    app.transcript.notice("hello")
    app.transcript.begin_turn("a question")
    app.transcript.append_answer("## Title\n\nbody with `code`")

    harness.write("/theme light")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    while len(app.app.screens) > 1:
        app.app.pop_screen()  # the success toast is its own screen
    harness.render()

    canvas = Canvas(app.app.width, app.app.height)
    app.app.screens.top.widget.render(canvas)
    painted = {
        colour
        for row in canvas.cells
        for cell in row
        for colour in (cell.style.foreground, cell.style.background)
        if colour is not None
    }

    assert app.app.theme is LIGHT
    assert not painted & (_palette(DARK) - _palette(LIGHT))


async def test_the_page_is_left_to_the_terminal_and_only_surfaces_are_painted():
    """A palette that names no page colour must not paint one.

    Mixing the two is what leaves patches: a filled page with foreground-only
    glyphs on top shows the terminal through them. Both built-in palettes leave
    the page to the terminal, so the only backgrounds on screen are the surfaces
    the shell means to raise; a palette that does name a page fills everything.
    """
    app = build_app()
    harness = _harness(app)
    app.transcript.begin_turn("a question")
    app.transcript.start_thinking()
    app.transcript.append_thinking("looking around")
    app.transcript.complete_thinking()
    app.transcript.append_answer("## Title\n\nprose with `code`")
    app.transcript.notice("Processed 1.0s")
    harness.render()

    for theme in (DARK, LIGHT):
        app.app.theme = theme
        harness.render()
        canvas = app.app.render()
        backgrounds = {cell.style.background for row in canvas.cells for cell in row}

        assert theme.background is None
        assert backgrounds == {None, theme.surface_alt}

        # A theme file may name a page, and then it is painted everywhere.
        app.app.theme = replace(theme, background="#123456")
        harness.render()
        painted = {cell.style.background for row in app.app.render().cells for cell in row}

        assert painted == {"#123456", theme.surface_alt}


async def test_app_slash_commands_change_theme_sessions_and_exit():
    app = build_app()
    harness = _harness(app)

    harness.write("/theme light")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert app.app.theme is LIGHT

    harness.write("/new")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert app.agent.session_id == "session-0002"

    harness.write("/help")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert any(entry.kind == "message" and "/sessions" in entry.text for entry in app.transcript.entries)

    harness.press("ctrl_d")
    assert app.app.running is False


async def test_new_session_clears_the_previous_visible_conversation():
    app = build_app()
    app.transcript.user_message("previous conversation")
    harness = _harness(app)

    harness.write("/new")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.session_id == "session-0002"
    assert "previous conversation" not in "\n".join(_rendered(app.transcript, 60))
    assert any(entry.kind == "welcome" for entry in app.transcript.entries)


async def test_model_command_lists_and_switches_models_for_the_next_request():
    app = build_app()
    harness = _harness(app)
    harness.render()

    harness.write("/model")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert app.app.screens.top.name == "page"
    assert "Select Model" in harness.render().text
    assert "GPT-4o" in harness.render().text
    harness.press("down")
    harness.press("enter")
    assert app.agent.active_model.model == "gpt-4o"
    assert app._header_right().text == "GPT-4o \u00b7 medium  "
    assert app.app._layout_dirty is True
    rendered = harness.render().text
    assert "Model changed from gpt-5-mini to GPT-4o." in rendered
    assert "GPT-4o" in rendered

    harness.write("hello")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert app.agent.runtime.client.models[-1] == "gpt-4o"


async def test_model_page_esc_restores_composer_without_selecting():
    app = build_app()
    app.app.resize(60, 24)
    harness = _harness(app)

    harness.write("/model")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert app.app.screens.top.name == "page"
    page = _presented_page(app)
    assert app.app.focused_widget() is page.list
    # The panel sits at the bottom, so the conversation above it stays visible.
    text = harness.render().text
    assert page.rect.y > 0
    assert "Type a task below, or /help for commands." in text
    assert "Select Model" in text

    harness.press("down")
    harness.press("escape")
    assert app.app.screens.top.name == "main"
    assert app.app.focused_widget() is app.composer
    assert app.agent.active_model.model == "gpt-5-mini"
    assert "Ask ZettCode" in harness.render().text


async def test_a_command_can_compose_its_own_panel():
    app = build_app()
    harness = _harness(app)

    async def show(argument: str) -> CommandResult:
        page = ListPage([ListItem("a", "alpha")], title="Panel", on_cancel=app.close_page)
        return CommandResult(widget=bottom_panel(page, rows=6))

    app.commands = (*app.commands, Command("/panel", "show a panel", "app", show))
    app.composer.completer = type(app.composer.completer)(app.commands)
    harness.write("/panel")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = _presented_page(app)
    harness.render()

    assert app.app.screens.top.name == "page"
    # The handler asked for six rows and a panel is not framed, so the page
    # fills them and the conversation above stays visible.
    assert page.rect.height == 6
    assert page.rect.bottom == app.app.height

    harness.press("escape")
    assert app.app.screens.top.name == "main"


async def test_ctrl_c_returns_from_the_model_page_without_cancelling_a_turn():
    app = build_app()
    harness = _harness(app)
    harness.write("/model")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    harness.press("ctrl_c")

    assert app.app.screens.top.name == "main"
    assert app.app.focused_widget() is app.composer
    assert app.agent.active_model.model == "gpt-5-mini"


async def test_model_can_still_be_selected_by_command_argument():
    app = build_app()
    harness = _harness(app)

    harness.write("/model GPT-4o")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.active_model.model == "gpt-4o"
    assert app.app.screens.top.name != "page"
    assert "Model changed from gpt-5-mini to GPT-4o." in harness.render().text


async def test_reselecting_the_current_model_adds_no_change_row():
    app = build_app()
    harness = _harness(app)

    harness.write("/model gpt-5-mini")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert not any(entry.kind == "announcement" for entry in app.transcript.entries)


def test_blank_row_replaces_the_rule_above_completions():
    app = build_app()
    harness = _harness(app)
    harness.write("/")
    harness.render()

    spacer = app.root.body.slots[4].widget
    assert isinstance(spacer, Text)
    assert spacer.content == ""
    assert spacer.rect.height == 1
    assert app.completions.rect.y == spacer.rect.bottom
    assert harness.render().lines[spacer.rect.y].strip() == ""


async def test_model_page_scrolls_many_entries_and_selects_offscreen_one():
    app = build_app()
    app.agent.runtime.config.models = tuple(
        ModelConfig(model=f"model-{index}", token="test-token") for index in range(16)
    )
    app.agent.runtime.active_model = app.agent.runtime.config.models[0]
    harness = _harness(app)

    harness.write("/model")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    page = _presented_page(app)
    harness.render()
    assert page.list.rect.height == 6
    for _ in range(12):
        harness.press("down")
    assert page.list.selected == 12
    harness.render()
    assert page.list.top > 0
    assert "model-12" in harness.render().text
    assert "model-0" not in harness.render().text
    harness.press("enter")
    assert app.agent.active_model.model == "model-12"
    assert app.app.screens.top.name != "page"


async def test_unknown_model_keeps_the_current_model():
    app = build_app()
    harness = _harness(app)

    harness.write("/model nonexistent")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.active_model.model == "gpt-5-mini"
    assert any("Unknown model" in entry.text for entry in app.transcript.entries)


def _approval_event(
    command: str = "rm -rf build", *, call_id: str = "call-1", remember_supported: bool = True
) -> AgentEvent:
    """Build the CUSTOM event the shell approval extension emits for one command."""
    return AgentEvent(
        AgentEventType.CUSTOM,
        "session-0001",
        name=SHELL_APPROVAL_EVENT_NAME,
        payload={
            "tool_call_id": call_id,
            "session_id": "session-0001",
            "command": command,
            "remember_supported": remember_supported,
        },
    )


async def test_app_asks_for_approval_in_a_bottom_panel():
    app = build_app()
    harness = _harness(app)

    await app.projector.dispatch(_approval_event())

    page = _approval_page(app)
    assert app.app.screens.top.name == "page"
    text = harness.render().text
    # The panel is anchored to the bottom edge of the screen.
    assert page.rect.bottom == app.app.height
    assert "Would you like to run the following command?" in text
    assert "Environment: local" in text
    assert "$ rm -rf build" in text
    assert "1. Yes, proceed (y)" in text
    assert "2. Yes, and don't ask again for this command (p)" in text
    assert "3. Yes, and stop asking for the rest of this run (a)" in text
    assert "4. No, and say what to do differently (esc)" in text

    harness.press("enter")

    event, config = app.agent.runtime.client.agent.emitted[0]
    assert event.name == "shell_approval_response"
    assert event.payload == {"tool_call_id": "call-1", "decision": "execute", "remember": False}
    assert config.session_id == "session-0001"
    assert app.app.screens.top.name == "main"


async def test_always_allow_remembers_only_the_exact_command():
    app = build_app()
    harness = _harness(app)

    await app.projector.dispatch(_approval_event())
    harness.press("p")

    event, _ = app.agent.runtime.client.agent.emitted[0]
    assert event.payload == {"tool_call_id": "call-1", "decision": "execute", "remember": True}
    assert app.agent.runtime.auto_approved is False


async def test_the_approval_panel_answers_to_arrows_numbers_and_letter_keys():
    app = build_app()
    harness = _harness(app)

    await app.projector.dispatch(_approval_event())

    page = _approval_page(app)
    harness.press("down")
    assert page.choice is ApprovalChoice.ALWAYS
    harness.press("up")
    assert page.choice is ApprovalChoice.RUN
    harness.press("3")
    assert page.choice is ApprovalChoice.RUN_AUTO


async def test_clicking_an_approval_option_answers_the_prompt():
    app = build_app()
    harness = _harness(app)

    await app.projector.dispatch(_approval_event())
    page = _approval_page(app)
    rows = harness.render().text.splitlines()
    target = next(index for index, line in enumerate(rows) if "2. Yes, and don't ask again" in line)

    harness.click(page.rect.x + 6, target)

    event, _ = app.agent.runtime.client.agent.emitted[0]
    assert event.payload == {"tool_call_id": "call-1", "decision": "execute", "remember": True}
    assert app.app.screens.top.name == "main"


async def test_auto_mode_approves_every_later_command():
    app = build_app()
    harness = _harness(app)

    await app.projector.dispatch(_approval_event())
    harness.press("a")

    event, _ = app.agent.runtime.client.agent.emitted[0]
    assert event.payload == {"tool_call_id": "call-1", "decision": "execute", "remember": False}
    assert app.agent.runtime.auto_approved is True
    assert any("auto mode" in entry.text for entry in app.transcript.entries)
    assert "auto" in harness.render().text.strip().splitlines()[-1]


async def test_the_approval_panel_hides_always_when_the_runtime_cannot_remember():
    app = build_app()
    harness = _harness(app)

    await app.projector.dispatch(_approval_event(remember_supported=False))

    text = harness.render().text
    assert "don't ask again for this command" not in text
    assert "2. Yes, and stop asking for the rest of this run (a)" in text


async def test_escape_aborts_the_pending_command():
    app = build_app()
    harness = _harness(app)

    await app.projector.dispatch(_approval_event())
    harness.press("escape")

    event, _ = app.agent.runtime.client.agent.emitted[0]
    assert event.payload == {"tool_call_id": "call-1", "decision": "abort", "remember": False}
    assert app.app.screens.top.name == "main"


async def test_ctrl_c_clears_the_composer_when_idle():
    app = build_app()
    harness = _harness(app)
    harness.write("draft text")

    harness.press("ctrl_c")

    assert app.composer.text == ""
    assert harness.exited is False


async def test_the_transcript_scrolls_with_the_mouse_wheel():
    app = build_app()
    harness = _harness(app)
    for index in range(60):
        app.transcript.notice(f"line {index}")
    harness.render()
    view = app.view
    x = view.rect.x + 1
    y = view.rect.y + 1
    tail = view.top

    assert view.follow_tail is True
    harness.scroll(x, y, up=True)

    assert view.top < tail
    assert view.follow_tail is False

    harness.scroll(x, y, up=False)

    assert view.top == tail
    assert view.follow_tail is True


async def test_a_scrolled_transcript_offers_back_to_bottom_by_click_and_escape():
    app = build_app()
    harness = _harness(app)
    for index in range(60):
        app.transcript.notice(f"line {index}")
    harness.render()
    view = app.view

    assert view.badge_rect() is None

    harness.press("page_up")
    harness.render()

    badge = view.badge_rect()
    assert badge is not None
    assert view.scrolled_up is True
    assert harness.render().text.splitlines()[badge.y].strip().endswith("back to bottom \u00b7 Esc")

    harness.mouse_down(badge.x + 1, badge.y)
    harness.mouse_up(badge.x + 1, badge.y)

    assert view.follow_tail is True
    assert view.badge_rect() is None

    harness.press("page_up")
    harness.render()
    assert view.scrolled_up is True

    harness.press("escape")

    assert view.follow_tail is True


async def test_ctrl_c_copies_the_transcript_selection():
    app = build_app()
    harness = _harness(app)
    for index in range(40):
        app.transcript.notice(f"line {index}")
    harness.render()
    view = app.view
    target = next(
        index for index in range(view.line_count()) if view.source.line(index, view.line_width).text.strip() == "line 3"
    )
    view.scroll_to(target)
    harness.render()
    x = view.rect.x + 2
    y = view.rect.y

    harness.mouse_down(x, y)
    harness.mouse_up(x + 6, y)

    selected = view.selected_text()
    assert selected == "line 3"
    assert harness.clipboard == selected

    app.app.clipboard = ""
    harness.press("ctrl_c")

    assert harness.clipboard == selected
    assert view.selected_text() == ""
    assert app.composer.text == ""


async def test_a_drag_over_a_panel_copies_the_rows_it_covered():
    """Panels draw text without owning it, so the drag copies the painted cells."""
    app = build_app()
    harness = _harness(app)
    harness.write("/model")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    page = _presented_page(app)
    harness.render()
    first = page.list.rect

    harness.mouse_down(first.x, first.y)
    harness.mouse_move(first.x + 24, first.y + 1)
    harness.mouse_up(first.x + 24, first.y + 1)

    assert "gpt-5-mini" in harness.clipboard
    assert "GPT-4o" in harness.clipboard


async def test_ctrl_c_copies_a_panel_selection_instead_of_closing_the_page():
    app = build_app()
    harness = _harness(app)
    harness.write("/model")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    page = _presented_page(app)
    harness.render()
    first = page.list.rect

    # The drag never reports a release, as when the pointer leaves the terminal.
    harness.mouse_down(first.x, first.y)
    harness.mouse_move(first.x + 24, first.y)
    harness.press("ctrl_c")

    assert "gpt-5-mini" in harness.clipboard
    assert _presented_page(app) is page


async def test_app_mirrors_the_agent_plan_into_the_panel():
    app = build_app(
        [
            AgentEvent(AgentEventType.TEXT_DELTA, "s", delta="working"),
            AgentEvent(AgentEventType.RUN_COMPLETED, "s", message=AssistantMessage(content="done")),
        ]
    )
    app.agent.runtime.todos.result = TodoWriteResult(
        todos=(
            TodoItem(content="inspect the repo", status=TodoStatus.COMPLETED),
            TodoItem(content="write the fix", status=TodoStatus.IN_PROGRESS),
            TodoItem(content="run the tests", status=TodoStatus.PENDING),
        ),
        in_progress_index=1,
        in_progress=TodoItem(content="write the fix", status=TodoStatus.IN_PROGRESS),
        completed=False,
    )
    harness = _harness(app)

    harness.write("go")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.panel.tasks[0] == ("completed", "inspect the repo")
    assert app.panel.tasks[1][0] == "in_progress"
    # Three tasks: a separator row, the frame, and the rows themselves.
    assert app.panel.preferred_height() == 6

    text = harness.render().text

    assert "inspect the repo" in text
    assert "run the tests" in text


async def test_the_slash_menu_lists_and_filters_commands():
    app = build_app()
    harness = _harness(app)

    harness.write("/")

    assert [item.value for item in app.completions.items][:3] == ["/help", "/new", "/use"]
    assert "show the commands and the keys" in harness.text()
    assert "[app]" in harness.text() and "[agent]" in harness.text()
    assert app.completions.items[0].type == "app"
    assert app.completions.items[1].type == "agent"

    harness.write("cl")

    assert [item.value for item in app.completions.items] == ["/clear"]
    assert "clear the transcript" in harness.text()

    harness.write(" ")

    # Once the draft leaves the bare command token the menu gets out of the way.
    assert app.completions.visible is False


async def test_app_and_agent_commands_are_routed_to_their_owners():
    app = build_app()
    harness = _harness(app)
    assert [(item.name, item.type) for item in app.commands[:3]] == [
        ("/help", "app"),
        ("/new", "agent"),
        ("/use", "agent"),
    ]

    harness.write("/new")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert app.agent.session_id == "session-0002"

    harness.write("/help")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    help_messages = [entry.text for entry in app.transcript.entries if entry.kind == "message"]
    assert any("/model" in message and "(`agent`)" in message and "(`app`)" in message for message in help_messages)


def test_slash_menu_caps_rows_and_scrolls_many_commands():
    app = build_app()

    async def no_op(argument: str) -> CommandResult:
        return CommandResult()

    extra = tuple(Command(f"/agent-{index}", f"action {index}", "agent", no_op) for index in range(15))
    app.commands = (*app.commands, *extra)
    app.composer.completer = type(app.composer.completer)(app.commands)
    harness = _harness(app)
    harness.write("/")

    assert len(app.completions.items) == len(app.commands)
    assert app.completions.visible_height == 6
    for _ in range(12):
        harness.press("down")
    assert app.completions.selected == 12
    harness.render()
    assert app.completions.top > 0
    # The highlighted row is scrolled into view; which command it is depends on
    # how many the shell registers, so read it back instead of naming it.
    assert app.commands[app.completions.selected].name in harness.render().text


async def test_a_registered_command_runs_its_own_handler():
    app = build_app()
    harness = _harness(app)
    arguments: list[str] = []

    async def custom_handler(argument: str) -> CommandResult:
        arguments.append(argument)
        return CommandResult(message=f"custom: {argument}", relayout=True)

    app.commands = (*app.commands, Command("/custom", "run a custom action", "app", custom_handler))
    app.composer.completer = type(app.composer.completer)(app.commands)
    harness.write("/custom hello")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert arguments == ["hello"]
    assert any("custom: hello" in entry.text for entry in app.transcript.entries)
    assert app.app._layout_dirty


async def test_command_output_is_rendered_as_markdown():
    app = build_app()
    harness = _harness(app)

    harness.write("/help")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    (entry,) = [item for item in app.transcript.entries if item.kind == "message"]
    rendered = "\n".join(_rendered(app.transcript, 60))

    assert entry.markdown is not None
    assert "**Commands**" in entry.text  # the handler returns Markdown source
    assert "Commands" in rendered and "\u00b7 /help" in rendered  # parsed, not raw
    assert "**" not in rendered  # the emphasis markers are consumed


async def test_a_command_can_present_its_own_widget():
    app = build_app()
    harness = _harness(app)

    async def show_page(argument: str) -> CommandResult:
        page = ListPage([ListItem("a", "alpha")], title="Custom Page", on_cancel=app.close_page)
        return CommandResult(widget=page)

    app.commands = (*app.commands, Command("/panel", "show a custom page", "app", show_page))
    app.composer.completer = type(app.composer.completer)(app.commands)
    harness.write("/panel")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = _presented_page(app)
    assert app.app.screens.top.name == "page"
    assert "Custom Page" in harness.render().text
    assert page.rect == Rect(0, 0, 60, 14)  # nothing wraps it, so it covers the screen

    harness.press("escape")
    assert app.app.screens.top.name == "main"


async def test_the_slash_menu_answers_to_arrows_and_escape():
    app = build_app()
    harness = _harness(app)

    harness.write("/")
    harness.press("down")
    assert app.completions.current.value == "/new"

    harness.press("up")
    assert app.completions.current.value == "/help"

    harness.press("escape")

    assert app.completions.visible is False
    assert app.composer.text == "/"


async def test_enter_completes_the_highlighted_command_once_then_runs_it():
    app = build_app()
    harness = _harness(app)

    harness.write("/se")
    assert [item.value for item in app.completions.items] == ["/sessions"]

    harness.press("enter")

    assert app.composer.text == "/sessions "
    assert app.completions.visible is False

    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.composer.text == ""
    assert any(entry.kind == "message" for entry in app.transcript.entries)


async def test_enter_runs_a_fully_typed_command_instead_of_completing_it():
    app = build_app()
    harness = _harness(app)

    harness.write("/help")
    assert app.completions.visible is True

    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert any(entry.kind == "message" and "/sessions" in entry.text for entry in app.transcript.entries)
    assert app.composer.text == ""
    assert app.completions.visible is False


async def test_history_still_works_while_the_menu_is_closed():
    app = build_app()
    harness = _harness(app)

    harness.write("/help")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    harness.press("up")

    assert app.composer.text == "/help"
    assert app.completions.visible is True


async def test_a_wrapping_draft_grows_the_composer_and_shrinks_the_transcript():
    """The composer's height is geometry: the boxes have to be laid out again."""
    app = build_app()
    harness = _harness(app)
    harness.render()
    composer_before, view_before = app.composer.rect, app.view.rect

    harness.write("x" * 200)
    harness.render()

    assert app.composer.rect.height == app.composer.preferred_height(app.composer.rect.width)
    assert app.composer.rect.height > composer_before.height
    assert app.composer.rect.height <= 8
    # The row above and the row below keep their size; the flexible transcript
    # absorbs the difference, which is what a re-layout is for.
    assert app.header.rect == Rect(0, 0, 60, 1)
    assert app.view.rect.height == view_before.height - (app.composer.rect.height - composer_before.height)


def test_format_ago_uses_the_coarsest_unit_that_fits():
    now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)

    assert format_ago(now - timedelta(seconds=5), now=now) == "just now"
    assert format_ago(now - timedelta(seconds=90), now=now) == "1m ago"
    assert format_ago(now - timedelta(hours=3), now=now) == "3h ago"
    assert format_ago(now - timedelta(days=2), now=now) == "2d ago"
    # A clock skew must not produce a negative age.
    assert format_ago(now + timedelta(minutes=1), now=now) == "just now"


def test_the_header_trims_a_wide_path_by_display_width():
    trimmed = compact_path(Path("/tmp") / ("\u6df1" * 30), limit=10)

    assert trimmed.startswith("\u2026")
    assert display_width(trimmed) <= 10


def test_the_sessions_panel_lines_wide_titles_up_in_one_column():
    now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    sessions = [
        SessionInfo("01a1010f", "Flask 实现 Python 服务器", now - timedelta(minutes=17), now - timedelta(minutes=17)),
        SessionInfo(
            "01a10119", "Python 实现 HTTP 服务器框架", now - timedelta(minutes=19), now - timedelta(minutes=19)
        ),
        SessionInfo("01a10116", None, now - timedelta(hours=3), now - timedelta(hours=3)),
    ]
    page = SessionsPage(sessions, on_select=lambda _: None, on_cancel=lambda: None, now=now)
    rows = [row for row in render_block(page, width=64, height=10, theme=DARK).splitlines() if "01a10" in row]

    assert len(rows) == 3
    # A wide title is padded by the columns it draws, so every age starts in the
    # same column however long the title above it is ...
    assert len({display_width(row[: row.index("ago")]) for row in rows}) == 1
    # ... and the ages are right-aligned, so "3h ago" lines up with "17m ago"
    # and the short id after them never steps in and out of column.
    assert len({display_width(row[: row.index("\u00b7")]) for row in rows}) == 1


async def test_switching_sessions_replaces_the_transcript_with_stored_history(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("previous", "req-1", UserMessage(content="old question"))
    await store.append("previous", "req-1", AssistantMessage(content="**old answer**"))
    await store.append("another", "req-2", UserMessage(content="different question"))
    app = build_app()
    app.agent.runtime.persistence.store = store
    app.agent.runtime.persistence.sessions = await store.list_sessions()
    app.transcript.notice("from the current session")
    harness = _harness(app)

    harness.write("/sessions")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    page = _sessions_page(app)
    harness.render()
    page.list.select(next(index for index, item in enumerate(page.list.items) if item.value == "previous"))
    harness.press("enter")

    assert app.agent.session_id == "previous"
    assert [entry.kind for entry in app.transcript.entries] == ["user", "answer"]
    rendered = "\n".join(_rendered(app.transcript, 60))
    assert "old question" in rendered
    assert "old answer" in rendered
    assert "different question" not in rendered
    assert "from the current session" not in rendered
    assert app.app.screens.top.name != "page"

    harness.write("follow up")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert app.agent.runtime.client.configs[-1].session_id == "previous"


async def test_restoring_history_keeps_message_and_tool_order(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("previous", "req-1", UserMessage(content="first question"))
    await store.append("previous", "req-1", AssistantMessage(content="first answer"))
    await store.append("previous", "req-2", UserMessage(content="inspect app.py"))
    await store.append(
        "previous",
        "req-2",
        AssistantMessage(tool_calls=(ToolCall("call-1", "read_file", {"path": "app.py"}),)),
    )
    await store.append(
        "previous",
        "req-2",
        ToolMessage(tool_call_id="call-1", name="read_file", content="def parse():\n    return 42"),
    )
    await store.append("previous", "req-2", AssistantMessage(content="**fixed**"))
    app = build_app()
    app.agent.runtime.persistence.store = store
    app.restore_session("previous")

    assert [entry.kind for entry in app.transcript.entries] == ["user", "answer", "user", "tool", "answer"]
    rendered = "\n".join(_rendered(app.transcript, 60))
    assert rendered.index("first question") < rendered.index("first answer") < rendered.index("inspect app.py")
    assert rendered.index("Read app.py") < rendered.index("return 42") < rendered.index("fixed")
    assert all(entry.kind != "pending" for entry in app.transcript.entries)


async def test_restoring_an_interrupted_tool_does_not_show_it_as_running(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("previous", "req", UserMessage(content="inspect app.py"))
    await store.append(
        "previous",
        "req",
        AssistantMessage(tool_calls=(ToolCall("call-1", "read_file", {"path": "app.py"}),)),
    )
    app = build_app()
    app.agent.runtime.persistence.store = store
    app.restore_session("previous")

    tool = next(entry for entry in app.transcript.entries if entry.kind == "tool")
    assert tool.status == "skipped"
    assert "Result unavailable" in tool.text
    assert "Running…" not in "\n".join(_rendered(app.transcript, 60))


async def test_restoring_a_fork_excludes_the_abandoned_branch(tmp_path):
    store = SessionStore(tmp_path)
    root = await store.append("forked", "req", UserMessage(content="root question"))
    await store.append("forked", "req", AssistantMessage(content="abandoned answer"))
    await store.append("forked", "req", AssistantMessage(content="active answer"), parent=root)
    app = build_app()
    app.agent.runtime.persistence.store = store
    app.restore_session("forked")

    assert [entry.kind for entry in app.transcript.entries] == ["user", "answer"]
    rendered = "\n".join(_rendered(app.transcript, 60))
    assert "root question" in rendered
    assert "active answer" in rendered
    assert "abandoned answer" not in rendered


async def test_use_command_restores_history_and_rejects_missing_session(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("previous", "req", UserMessage(content="saved question"))
    app = build_app()
    app.agent.runtime.persistence.store = store
    harness = _harness(app)

    harness.write("/use previous")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.session_id == "previous"
    assert any(entry.kind == "user" and entry.text == "saved question" for entry in app.transcript.entries)

    harness.write("/use missing")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.session_id == "previous"
    assert any(entry.kind == "notice" and "Unknown session: missing" in entry.text for entry in app.transcript.entries)


async def test_sessions_argument_restores_the_selected_history(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("previous", "req", UserMessage(content="direct selection"))
    app = build_app()
    app.agent.runtime.persistence.store = store
    harness = _harness(app)

    harness.write("/sessions previous")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.session_id == "previous"
    assert any(entry.kind == "user" and entry.text == "direct selection" for entry in app.transcript.entries)


async def test_sessions_command_opens_a_panel_with_titles_and_ages(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("alpha-1", "req", UserMessage(content="hi"))
    await store.append("beta-2", "req", UserMessage(content="hi"))
    await store.set_title("alpha-1", "Fix the parser crash")
    app = build_app()
    app.agent.runtime.persistence.sessions = await store.list_sessions()
    app.agent.runtime.persistence.store = store
    harness = _harness(app)

    harness.write("/sessions")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = _sessions_page(app)
    text = harness.render().text
    assert page.rect.bottom == app.app.height
    assert "Fix the parser crash" in text
    assert text.count("just now") == 2
    # A session without a title keeps that column empty but still shows its id.
    assert "beta-2" in text
    assert [item.value for item in page.list.items] == ["beta-2", "alpha-1"]

    harness.press("down")
    harness.press("enter")

    assert app.agent.session_id == "alpha-1"
    assert app.app.screens.top.name != "page"
    # Resuming a session puts its stored title, not its id, in the status line.
    assert "Fix the parser crash" in app._status_left().text


async def test_sessions_command_reports_an_empty_store():
    app = build_app()
    harness = _harness(app)

    harness.write("/sessions")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.app.screens.top.name == "main"
    assert any("No persisted sessions" in entry.text for entry in app.transcript.entries)


async def test_the_first_reply_names_the_session_in_the_background():
    app = build_app()
    harness = _harness(app)
    calls: list[str] = []

    async def fake_title(session_id: str) -> str | None:
        calls.append(session_id)
        return "Fix the parser crash"

    app.agent.title_session = fake_title
    harness.write("please fix the parser")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert app._title_task is not None
    await asyncio.wait_for(app._title_task, 2.0)

    assert calls == ["session-0001"]
    # Naming stays out of the transcript: the status line is where the title lands.
    assert not any("Fix the parser crash" in getattr(entry, "text", "") for entry in app.transcript.entries)
    assert "Fix the parser crash" in app._status_left().text
    assert "session-0001" not in app._status_left().text


async def test_an_unnamed_session_reads_as_a_new_session(tmp_path):
    """A fresh session has no title yet, and a blank status line reads like a bug."""
    app = build_app()
    app.agent.runtime.persistence.store = SessionStore(tmp_path)
    harness = _harness(app)

    assert "New session" in app._status_left().text

    harness.write("/title  Fix the parser crash  ")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert "Fix the parser crash" in app._status_left().text
    assert "New session" not in app._status_left().text


def test_the_sessions_panel_names_an_untitled_session():
    now = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
    sessions = [SessionInfo("01a1010f", None, now - timedelta(minutes=17), now - timedelta(minutes=17))]

    page = SessionsPage(sessions, on_select=lambda _: None, on_cancel=lambda: None, now=now)

    assert [item.label for item in page.list.items] == ["New session"]


async def test_the_status_line_mirrors_the_usage_extension():
    app = build_app()
    payload = UsageSnapshot(
        input_tokens=22_000,
        output_tokens=600,
        cache_read_tokens=17_000,
        seconds=6.0,
        requests=2,
        context_tokens=64_000,  # half of the 128k window the fake model declares
    ).to_payload()

    await app.projector.on_custom_event(
        AgentEvent(
            type=AgentEventType.CUSTOM,
            session_id="session-0001",
            name=USAGE_EVENT_NAME,
            payload=payload,
        )
    )

    status = app._status_left().text
    assert "\u219122.0k \u2193600" in status
    assert "77.3% cached" in status
    assert "100 tok/s" in status
    assert "\u00b7 ctx 50.0%" in status


async def test_resuming_a_session_restores_its_token_totals(tmp_path):
    store = SessionStore(tmp_path)
    timing = MessageTiming(started_at=datetime.now(UTC), completed_at=datetime.now(UTC), duration_ns=2_000_000_000)
    await store.append(
        "previous",
        "req",
        AssistantMessage(content="stored answer"),
        timing=timing,
        usage=ModelUsage(input_tokens=10_000, output_tokens=500, cache_read_tokens=8_000),
    )
    app = build_app()
    app.agent.runtime.persistence.store = store
    harness = _harness(app)

    harness.write("/use previous")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    status = app._status_left().text
    assert "\u219110.0k \u2193500" in status
    assert "80.0% cached" in status
    assert "250 tok/s" in status


async def test_a_new_session_starts_the_token_totals_over():
    app = build_app()
    app._usage = UsageSnapshot(input_tokens=900, output_tokens=90, seconds=3.0, requests=1)
    harness = _harness(app)

    harness.write("/new")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.agent.session_id != "session-0001"
    assert "\u2191" not in app._status_left().text


def _harness(app: ZettCodeApp) -> Harness:
    return Harness(app=app.app)


def _rendered(transcript: Transcript, width: int) -> list[str]:
    source = TranscriptSource(transcript, theme=DARK)
    return [source.line(index, width).text for index in range(source.count(width))]
