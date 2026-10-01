"""End-to-end tests for the ZettCode application layer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
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
)

from zettcode.app import Transcript, TranscriptSource, ZettCodeApp
from zettcode.app.projection import TranscriptProjector
from zettcode.tui_framework import DARK, LIGHT
from zettcode.tui_framework.testing import Harness


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

    async def stream(self, message, *, config=None):
        if self.event_dispatcher is not None:
            self.event_dispatcher.begin_turn(message)
        for event in self.events:
            if self.event_dispatcher is not None:
                await self.event_dispatcher.dispatch(event)
            yield event
        if self.block:
            await asyncio.sleep(3600)


class FakePersistence:
    async def list_sessions(self, limit: int | None = None):
        return []


class FakeTodos:
    def __init__(self) -> None:
        self.result = None
        self.queries: list[str] = []

    def todos(self, session_id: str):
        self.queries.append(session_id)
        return self.result


class FakeProvider:
    value = "deepseek"


@dataclass
class FakeConfig:
    workspace: Path = Path("/tmp/workspace")
    provider: FakeProvider = field(default_factory=FakeProvider)
    model: str = "deepseek-chat"
    reduced_motion: bool = False


@dataclass
class FakeRuntime:
    client: object
    session_id: str = "session-0001"
    persistence: FakePersistence = field(default_factory=FakePersistence)
    todos: FakeTodos = field(default_factory=FakeTodos)
    config: FakeConfig = field(default_factory=FakeConfig)

    def new_session(self) -> str:
        self.session_id = "session-0002"
        return self.session_id

    def use_session(self, session_id: str) -> None:
        self.session_id = session_id


def build_app(events: list[AgentEvent] | None = None, *, block: bool = False) -> ZettCodeApp:
    app = ZettCodeApp(FakeRuntime(FakeClient(events, block=block)))
    app.app.resize(60, 14)
    app.app.mount()
    return app


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
    assert app.runtime.session_id == "session-0002"

    harness.write("/help")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert any(entry.kind == "notice" and "/sessions" in entry.text for entry in app.transcript.entries)

    harness.press("ctrl_d")
    assert app.app.running is False


async def test_app_asks_for_approval_and_emits_the_decision():
    app = build_app()
    harness = _harness(app)
    request = AgentEvent(
        AgentEventType.CUSTOM,
        "session-0001",
        name=SHELL_APPROVAL_EVENT_NAME,
        payload={
            "tool_call_id": "call-1",
            "session_id": "session-0001",
            "command": "rm -rf build",
            "remember_supported": True,
        },
    )

    await app.projector.dispatch(request)

    assert len(app.app.screens) == 2
    assert "rm -rf build" in harness.render().text

    harness.press("right")
    harness.press("enter")

    event, config = app.runtime.client.agent.emitted[0]
    assert event.name == "shell_approval_response"
    assert event.payload == {"tool_call_id": "call-1", "decision": "execute", "remember": True}
    assert config.session_id == "session-0001"
    assert len(app.app.screens) == 1


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
    view.scroll_to(76)
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
    app.runtime.todos.result = TodoWriteResult(
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

    assert [item.value for item in app.completions.items][:3] == ["/help", "/new", "/sessions"]
    assert "show the commands and the keys" in harness.text()

    harness.write("cl")

    assert [item.value for item in app.completions.items] == ["/clear"]
    assert "clear the transcript" in harness.text()

    harness.write(" ")

    # Once the draft leaves the bare command token the menu gets out of the way.
    assert app.completions.visible is False


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
    assert any(entry.kind == "notice" for entry in app.transcript.entries)


async def test_enter_runs_a_fully_typed_command_instead_of_completing_it():
    app = build_app()
    harness = _harness(app)

    harness.write("/help")
    assert app.completions.visible is True

    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert any(entry.kind == "notice" and "/sessions" in entry.text for entry in app.transcript.entries)
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


def _harness(app: ZettCodeApp) -> Harness:
    return Harness(app=app.app)


def _rendered(transcript: Transcript, width: int) -> list[str]:
    source = TranscriptSource(transcript, theme=DARK)
    return [source.line(index, width).text for index in range(source.count(width))]
