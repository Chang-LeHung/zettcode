"""End-to-end tests for the ZettCode application layer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from zett_agent import (
    SHELL_APPROVAL_EVENT_NAME,
    AgentEvent,
    AgentEventType,
    AssistantMessage,
    TodoItem,
    TodoStatus,
    TodoWriteResult,
    ToolCall,
    ToolMessage,
    UserMessage,
)

from zettcode.app import Transcript, TranscriptSource, ZettCodeApp
from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.projection import TranscriptProjector
from zettcode.app.agent.storage import SessionInfo, SessionStore
from zettcode.app.commands import Command, CommandResult
from zettcode.app.ui.widgets import WELCOME, ApprovalChoice, ApprovalPage, SessionsPage, format_ago
from zettcode.config import ModelConfig
from zettcode.tui import DARK, LIGHT, ListItem, ListPage, Rect, walk
from zettcode.tui.testing import Harness


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

    async def stream(self, message, *, config=None, model=None):
        self.models.append(model)
        self.configs.append(config)
        if self.event_dispatcher is not None:
            self.event_dispatcher.begin_turn(message)
        for event in self.events:
            if self.event_dispatcher is not None:
                await self.event_dispatcher.dispatch(event)
            yield event
        if self.block:
            await asyncio.sleep(3600)


class FakePersistence:
    def __init__(self) -> None:
        self.sessions: list[SessionInfo] = []

    async def list_sessions(self, limit: int | None = None):
        return self.sessions[:limit] if limit is not None else list(self.sessions)


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


@dataclass
class FakeRuntime:
    client: object
    session_id: str = "session-0001"
    persistence: FakePersistence = field(default_factory=FakePersistence)
    todos: FakeTodos = field(default_factory=FakeTodos)
    config: FakeConfig = field(default_factory=FakeConfig)
    active_model: ModelConfig = field(init=False)
    model: object = field(init=False)
    auto_approved: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.active_model = self.config.models[0]
        self.model = self.active_model.model

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


def build_app(events: list[AgentEvent] | None = None, *, block: bool = False) -> ZettCodeApp:
    app = ZettCodeApp(ZettCodeAgent(FakeRuntime(FakeClient(events, block=block))))
    app.app.resize(60, 14)
    app.app.mount()
    return app


def _presented_page(app: ZettCodeApp) -> ListPage:
    """Return the page on top of the stack, wherever the shell wrapped it."""
    return next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, ListPage))


def _approval_page(app: ZettCodeApp) -> ApprovalPage:
    """Return the approval panel on top of the stack, inside its border."""
    return next(widget for widget in walk(app.app.screens.top.widget) if isinstance(widget, ApprovalPage))


def _sessions_page(app: ZettCodeApp) -> SessionsPage:
    """Return the session panel on top of the stack, inside its border."""
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

    async for _ in agent.stream("hello"):
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
    assert "glob" in collapsed and "grep" in collapsed
    assert "done" in collapsed

    assert transcript.toggle_latest_thinking()
    assert "checking" in "\n".join(_rendered(transcript, 40))


def test_a_placeholder_is_shown_before_anything_is_known():
    transcript = Transcript(clock=lambda: 0.0)

    transcript.begin_turn("slow question")
    rendered = "\n".join(_rendered(transcript, 40))

    assert [entry.kind for entry in transcript.entries] == ["user", "pending"]
    assert "Waiting for the model" in rendered

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
    assert "Waiting for the model" not in "\n".join(_rendered(transcript, 40))

    finished = Transcript(clock=lambda: 0.0)
    finished.begin_turn("question")
    finished.complete_thinking()

    assert [entry.kind for entry in finished.entries] == ["user"]


async def test_a_waiting_row_appears_as_soon_as_a_turn_starts():
    app = build_app(block=True)
    harness = _harness(app)

    harness.write("slow question")
    harness.press("enter")
    await asyncio.sleep(0.02)
    text = harness.render().text

    assert "slow question" in text
    assert "Waiting for the model" in text
    assert app.transcript.frame > 0
    assert "running" in text


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

    assert "find the bug" in text
    assert "Result" in text
    assert "bold finding" in text
    assert app.busy is False


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
    assert app._header_right() == "GPT-4o  "
    assert app.app._layout_dirty is True
    assert "GPT-4o" in harness.render().text

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


async def test_a_page_without_overlay_rows_is_presented_full_screen():
    app = build_app()
    page = ListPage([ListItem("a", "alpha")], title="Full")

    app._present(page, name="full")
    harness = _harness(app)
    harness.render()

    assert app.app.screens.top.name == "full"
    assert page.rect == Rect(0, 0, 60, 14)
    assert "alpha" in harness.render().text


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
    assert "GPT-4o" in harness.render().text


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
    # The panel sits at the bottom, so the conversation above it stays visible.
    assert page.rect.y > 0
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
            TodoItem(content="write the fix", status=TodoStatus.PROCESSING),
            TodoItem(content="run the tests", status=TodoStatus.PENDING),
        ),
        processing_index=1,
        processing=TodoItem(content="write the fix", status=TodoStatus.PROCESSING),
        completed=False,
    )
    harness = _harness(app)

    harness.write("go")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert app.panel.tasks[0] == ("completed", "inspect the repo")
    assert app.panel.tasks[1][0] == "processing"
    assert app.panel.preferred_height() == 4

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
    assert "/agent-3" in harness.render().text


async def test_a_registered_command_runs_its_own_handler():
    app = build_app()
    harness = _harness(app)
    arguments: list[str] = []

    async def custom_handler(argument: str) -> CommandResult:
        arguments.append(argument)
        return CommandResult(messages=(f"custom: {argument}",), relayout=True)

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
        return CommandResult(page=page)

    app.commands = (*app.commands, Command("/panel", "show a custom page", "app", show_page))
    app.composer.completer = type(app.composer.completer)(app.commands)
    harness.write("/panel")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = _presented_page(app)
    assert app.app.screens.top.name == "page"
    assert "Custom Page" in harness.render().text
    assert page.rect == Rect(0, 0, 60, 14)  # no overlay_rows, so it covers the screen

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


async def test_sessions_command_opens_a_panel_with_titles_and_ages(tmp_path):
    store = SessionStore(tmp_path)
    await store.append("alpha-1", "req", UserMessage(content="hi"))
    await store.append("beta-2", "req", UserMessage(content="hi"))
    await store.set_title("alpha-1", "Fix the parser crash")
    app = build_app()
    app.agent.runtime.persistence.sessions = await store.list_sessions()
    harness = _harness(app)

    harness.write("/sessions")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    page = _sessions_page(app)
    text = harness.render().text
    assert page.rect.y > 0
    assert "Fix the parser crash" in text
    assert text.count("just now") == 2
    # A session without a title keeps that column empty but still shows its id.
    assert "beta-2" in text
    assert [item.value for item in page.list.items] == ["beta-2", "alpha-1"]

    harness.press("down")
    harness.press("enter")

    assert app.agent.session_id == "alpha-1"
    assert app.app.screens.top.name != "page"


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
    assert any("session title: Fix the parser crash" in entry.text for entry in app.transcript.entries)


def _harness(app: ZettCodeApp) -> Harness:
    return Harness(app=app.app)


def _rendered(transcript: Transcript, width: int) -> list[str]:
    source = TranscriptSource(transcript, theme=DARK)
    return [source.line(index, width).text for index in range(source.count(width))]
