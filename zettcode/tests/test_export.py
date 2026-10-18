"""The HTML trace: how a stored session is grouped, escaped, and collapsed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from zett_agent.extensions.events import MessageTiming
from zett_agent.messages import AssistantMessage, SystemMessage, ToolCall, ToolMessage, UserMessage
from zett_agent.model import ModelUsage

from zettcode.app.agent.export import COLLAPSE_AFTER, build_trace, render_html
from zettcode.app.agent.storage import SessionStore

#: One call's timing: two seconds, ten seconds after the session opened.
STARTED = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)
TIMING = MessageTiming(started_at=STARTED, completed_at=STARTED + timedelta(seconds=2), duration_ns=2_000_000_000)


async def _session(tmp_path: Path):
    """Two turns: one with reasoning and a tool, one with markup in the prompt."""
    store = SessionStore(tmp_path)
    call = ToolCall(id="c1", name="read_file", arguments={"path": "app.py"})
    await store.append("s1", "r1", UserMessage(content="first question"), timing=TIMING)
    assistant = await store.append(
        "s1",
        "r1",
        AssistantMessage(content="first answer", reasoning="weighed it", tool_calls=[call]),
        timing=TIMING,
        usage=ModelUsage(input_tokens=1_000, output_tokens=100, cache_read_tokens=800),
    )
    await store.append(
        "s1",
        "r1",
        ToolMessage(tool_call_id="c1", name="read_file", content="import os", success=True),
        timing=TIMING,
        parent=assistant,
    )
    await store.append("s1", "r1", UserMessage(content="second question <script>alert(1)</script>"), timing=TIMING)
    await store.append("s1", "r1", AssistantMessage(content="second answer"), timing=TIMING)
    return store.read("s1")


async def test_turns_group_at_each_user_message(tmp_path: Path):
    trace = build_trace(
        await _session(tmp_path),
        title="Fix it",
        subtitle="s1 · /tmp",
        context_messages=(SystemMessage(content="You are ZettCode."),),
    )

    assert [section.label for section in trace.sections] == ["Turn 1", "Turn 2", "Context"]
    first, second = trace.sections[0], trace.sections[1]
    assert [event.kind for event in first.events] == ["user", "assistant", "tool"]
    assert first.title == "first question"
    assert first.stats == "3 events · 4.0 s"  # the answer and the tool each took two
    assert second.stats == "2 events · 2.0 s"
    assert first.events[1].calls == (("read_file", '{"path": "app.py"}'),)
    assert first.events[2].ok is True
    assert [event.kind for event in trace.sections[2].events] == ["system"]  # the live prompt


async def test_message_text_is_content_never_markup(tmp_path: Path):
    page = render_html(build_trace(await _session(tmp_path)))

    assert "<script>alert(1)</script>" not in page  # the message never became markup
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


async def test_a_repeated_instruction_is_pointed_at_instead_of_reprinted(tmp_path: Path):
    """The context carries the prompt once per request; the page says so once."""
    instruction = SystemMessage(content="You are ZettCode.")
    trace = build_trace(await _session(tmp_path), context_messages=(instruction, instruction))
    context = trace.sections[-1]

    assert [event.duplicate_of for event in context.events] == [None, 1]
    page = render_html(trace)
    assert "Same text as #1." in page
    assert page.count("You are ZettCode.") == 2  # printed once, and its copy payload


async def test_long_text_collapses_and_short_text_does_not(tmp_path: Path):
    long_prompt = SystemMessage(content="x" * (COLLAPSE_AFTER + 1))
    trace = build_trace(await _session(tmp_path), context_messages=(long_prompt,))
    page = render_html(trace)

    assert '<details class="block">' in page  # the long instruction starts closed
    assert '<div class="body">' in page  # the short user prompt does not
    assert f"{COLLAPSE_AFTER + 1} chars" in page


async def test_the_page_carries_the_trace_furniture(tmp_path: Path):
    trace = build_trace(
        await _session(tmp_path),
        title="Fix it",
        subtitle="s1 · /tmp/workspace",
        meta=(("Model", "gpt-5-mini"),),
        context_messages=(SystemMessage(content="You are ZettCode."),),
    )
    page = render_html(trace)

    for part in (
        "LLM interaction trace",
        "Raw message storage",
        "Turn 1",
        "Current request",
        "first question",
        "weighed it",
        "read_file",
        "gpt-5-mini",
    ):
        assert part in page
    assert 'class="turn is-current"' in page  # the first turn opens selected
    assert 'class="panel is-current"' in page
