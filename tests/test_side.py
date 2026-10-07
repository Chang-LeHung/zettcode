"""Side questions: answered on screen, recorded, and never replayed.

A side question runs in the same session so the model sees the conversation it
is about, but everything it produces is stored with ``include_in_messages=False``
— the flag the runtime defines as "record it, never replay it" — and the tools
are the reading ones, because an edit made while asking would be invisible to the
conversation that continues afterwards.
"""

from __future__ import annotations

from pathlib import Path

from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.extensions.events import MessageAppendedEvent, MessageTiming
from zett_agent.messages import AssistantMessage, SystemMessage, UserMessage

from zettcode.app.agent.export import build_trace
from zettcode.app.agent.replay import replay
from zettcode.app.agent.side import READ_ONLY_TOOLS, SideQuestions, is_side, question
from zettcode.app.agent.storage import SessionStore


def _context(*, session_id: str = "s1") -> AgentRunContext:
    """Return a run context with the application's instructions in place."""
    state = AgentState()
    state._messages.append(SystemMessage(content="current instructions"))
    return AgentRunContext(AgentRunConfig(session_id=session_id), state, {})


def _appended(message) -> MessageAppendedEvent:
    """Return one append event for a message."""
    return MessageAppendedEvent(message=message, timing=MessageTiming.instant(), usage=None)


def _text(message) -> str:
    """Return a message's words, whichever field its type keeps them in."""
    return getattr(message, "text", None) or getattr(message, "content", "")


def test_the_question_is_a_user_message_that_is_not_replayed():
    message = question("what does parse() do?")

    assert isinstance(message, UserMessage)
    assert is_side(message)
    assert message.include_in_messages is False
    # Recorded all the same: the exchange stays in the file.
    assert message.persist is True
    assert not is_side(UserMessage(content="an ordinary question"))


async def test_the_store_records_a_side_exchange_without_replaying_it(tmp_path: Path):
    store = await _side_then_ordinary(tmp_path)

    # Everything is in the file, in order, and marked recorded-only …
    lines = store.read("s1").messages
    assert [_text(line.message[0]) for line in lines] == [
        "what does parse() do?",
        "it splits the header",
        "now change it",
    ]
    assert [line.message[0].include_in_messages for line in lines] == [False, False, True]
    assert [bool(line.tags.get("side")) for line in lines] == [True, True, False]

    # … and the next request rebuilds its context without the side exchange.
    following = _context()
    await store.on_state(following)

    assert [_text(message) for message in following.state.messages] == ["current instructions", "now change it"]


async def test_a_resumed_transcript_shows_the_side_exchange_but_history_does_not(tmp_path: Path):
    """The reader saw the answer, so it comes back on screen — and only there."""
    store = await _side_then_ordinary(tmp_path)

    replayed = replay(store.read("s1"))
    entries = [getattr(entry, "text", "") for entry in replayed.transcript.entries]
    side_rows = [entry for entry in replayed.transcript.entries if getattr(entry, "side", False)]

    assert any("what does parse() do?" in text for text in entries)
    assert any("it splits the header" in text for text in entries)
    assert [entry.text for entry in side_rows] == ["what does parse() do?"]
    assert any("now change it" in text for text in entries)
    # What the next request would carry is still the ordinary turn alone.
    assert [message.text for message in replayed.history] == ["now change it"]


async def test_an_exported_trace_leaves_the_side_exchange_out(tmp_path: Path):
    store = await _side_then_ordinary(tmp_path)

    trace = build_trace(store.read("s1"))
    texts = [event.text for section in trace.sections for event in section.events]

    assert not any("what does parse() do?" in text for text in texts)
    assert not any("it splits the header" in text for text in texts)
    assert any("now change it" in text for text in texts)


async def _side_then_ordinary(tmp_path: Path) -> SessionStore:
    """Store one side question with its answer, then one ordinary turn."""
    store = SessionStore(tmp_path)
    context = _context()
    await store.on_state(context)

    await store.on_event(context, _appended(question("what does parse() do?")))
    await store.on_event(context, _appended(AssistantMessage(content="it splits the header")))

    # The next request is an ordinary one, with its own bookkeeping.
    ordinary = _context()
    await store.on_state(ordinary)
    await store.on_event(ordinary, _appended(UserMessage(content="now change it")))
    return store


async def test_a_side_question_only_gets_the_reading_tools():
    extension = SideQuestions()
    context = _context()
    context.input_message = question("what does parse() do?")
    context.tools.update({"read_file": object(), "grep": object(), "write_file": object(), "run_shell": object()})

    await extension.before_turn(context)

    assert set(context.tools) == READ_ONLY_TOOLS - {"view_image", "glob", "read_skill"} | {"read_file", "grep"}
    assert set(context.tools) <= READ_ONLY_TOOLS


async def test_a_run_marked_by_the_shell_is_pruned_before_the_model_sees_it():
    extension = SideQuestions()
    context = _context()
    context.tools.update({"read_file": object(), "write_file": object()})

    extension.begin()
    await extension.on_tool(context)  # the hook the tool list is registered in
    extension.end()
    await extension.on_tool(context)

    assert set(context.tools) == {"read_file"}
    assert extension.pending is False


async def test_an_ordinary_turn_keeps_every_tool():
    extension = SideQuestions()
    context = _context()
    context.input_message = UserMessage(content="change it")
    context.tools.update({"read_file": object(), "write_file": object(), "run_shell": object()})

    await extension.before_turn(context)

    assert set(context.tools) == {"read_file", "write_file", "run_shell"}
