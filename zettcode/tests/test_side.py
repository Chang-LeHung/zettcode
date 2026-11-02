"""Side questions: answered on screen, recorded, and never replayed.

A side question runs in the same session so the model sees the conversation it
is about, but everything it produces is stored with ``include_in_messages=False``
— the flag the runtime defines as "record it, never replay it" — and the tools
are the reading ones, because an edit made while asking would be invisible to the
conversation that continues afterwards.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.extensions.events import MessageAppendedEvent, MessageTiming
from zett_agent.messages import AssistantMessage, SystemMessage, UserMessage

from zettcode.app.agent.conversation.replay import replay
from zettcode.engine.dialogue.side import (
    ORIGIN,
    READ_ONLY_TOOLS,
    READER,
    SIDE,
    WATCHED,
    SideQuestions,
    is_side,
    is_watched_side,
    is_watched_side_line,
    question,
)
from zettcode.engine.export import build_trace
from zettcode.engine.storage import SessionStore


def _context(*, session_id: str = "s1") -> AgentRunContext:
    """Return a run context with the application's instructions in place."""
    state = AgentState()
    state._messages.append(SystemMessage(content="current instructions"))
    return AgentRunContext(AgentRunConfig(session_id=session_id), state, {})


def _appended(message) -> MessageAppendedEvent:
    """Return one append event for a message."""
    return MessageAppendedEvent(message=message, timing=MessageTiming.instant(), usage=None)


def _line(tags: dict[str, object]) -> SimpleNamespace:
    """Return a stored line with these tags: as much of one as the tag readers look at."""
    return SimpleNamespace(tags=tags)


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


def test_a_question_says_who_asked_it_and_whether_it_was_watched():
    """A plugin asks for itself and is drawn nowhere, so a resumed session must not put it back on screen."""
    # Who asked is recorded, and it is what decides the default: the reader's own question was watched, a plugin's
    # was not.
    asked = question("what does parse() do?")
    assert asked.attributes == {SIDE: True, ORIGIN: READER, WATCHED: True}
    recap = question("The user stepped away and is coming back.", origin="recap")
    assert recap.attributes == {SIDE: True, ORIGIN: "recap", WATCHED: False}
    # A plugin that does draw its own question says so, and the word overrides what the origin implies.
    assert question("q", origin="recap", watched=True).attributes[WATCHED] is True
    assert not is_watched_side(UserMessage(content="plain"))
    # A stored line, which is what a replay reads: the tag, then who asked, then — for a file written before both —
    # no. Nothing from such a file is restored, because the one thing that asked on its own back then was the recap.
    assert is_watched_side_line(_line({SIDE: True, ORIGIN: READER}))
    assert not is_watched_side_line(_line({SIDE: True, ORIGIN: "recap"}))
    assert is_watched_side_line(_line({SIDE: True, WATCHED: True}))
    assert not is_watched_side_line(_line({SIDE: True, WATCHED: False}))
    assert not is_watched_side_line(_line({SIDE: True}))
    assert not is_watched_side_line(_line({WATCHED: False}))


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
    # Both lines of the run say the reader watched it, since the front end drew the question it asked; the ordinary
    # turn carries no tag at all, which is not the same thing as a side exchange tagged False.
    assert [line.tags.get("watched") for line in lines] == [True, True, None]

    # … and the next request rebuilds its context without the side exchange.
    following = _context()
    await store.on_state(following)

    assert [_text(message) for message in following.state.messages] == ["current instructions", "now change it"]


async def test_a_side_exchange_the_reader_did_not_watch_is_not_restored(tmp_path: Path):
    """A plugin asks for itself — the recap does — and nothing of that exchange was ever on screen.

    Restoring it would show the plugin's own instructions as a question of the reader's and its answer as a reply
    nobody asked for, so both lines stay out of the transcript: they are in the file, and out of history.
    """
    store = await _side_then_ordinary(tmp_path, watched=False)

    lines = store.read("s1").messages
    # Written down as False, not left off: an absent tag means the reader watched it.
    assert [line.tags.get("watched") for line in lines] == [False, False, None]

    replayed = replay(store.read("s1"))
    entries = [getattr(entry, "text", "") for entry in replayed.transcript.entries]

    assert not any("what does parse() do?" in text for text in entries)
    assert not any("it splits the header" in text for text in entries)
    assert [entry for entry in replayed.transcript.entries if getattr(entry, "side", False)] == []
    assert any("now change it" in text for text in entries)
    assert [message.text for message in replayed.history] == ["now change it"]


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


async def _side_then_ordinary(tmp_path: Path, *, watched: bool = True) -> SessionStore:
    """Store one side question with its answer, then one ordinary turn.

    Args:
        watched: Whether the reader watched the side question, as ``/btw`` is and a plugin's own question is not.
    """
    store = SessionStore(tmp_path)
    context = _context()
    await store.on_state(context)

    await store.on_event(context, _appended(question("what does parse() do?", watched=watched)))
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
    context.tools.update({"read_file": object(), "write_file": object(), "bash": object()})

    await extension.before_turn(context)

    assert set(context.tools) == {"read_file", "glob", "grep"}
    assert set(context.tools) <= READ_ONLY_TOOLS


async def test_a_side_question_can_search_although_the_main_agent_has_no_search_tool():
    """The main agent searches with its shell; a side question has none, so it is given `glob` and `grep` itself."""
    extension = SideQuestions()
    context = _context()
    context.tools.update({"read": object(), "write_file": object(), "edit": object(), "bash": object()})

    extension.begin()
    await extension.on_tool(context)

    assert set(context.tools) == {"read", "glob", "grep"}
    assert callable(context.tools["grep"].handler)


async def test_a_search_tool_the_agent_already_has_is_not_registered_twice():
    extension = SideQuestions()
    context = _context()
    extension.begin()
    await extension.on_tool(context)

    await extension.on_tool(context)
    context.input_message = question("again?")
    await extension.before_turn(context)

    assert set(context.tools) == {"glob", "grep"}


async def test_a_run_marked_by_the_shell_is_pruned_before_the_model_sees_it():
    extension = SideQuestions()
    context = _context()
    context.tools.update({"read_file": object(), "write_file": object()})

    extension.begin()
    await extension.on_tool(context)  # the hook the tool list is registered in
    extension.end()
    await extension.on_tool(context)

    assert set(context.tools) == {"read_file", "glob", "grep"}
    assert extension.pending is False


async def test_an_ordinary_turn_keeps_every_tool():
    extension = SideQuestions()
    context = _context()
    context.input_message = UserMessage(content="change it")
    context.tools.update({"read_file": object(), "write_file": object(), "bash": object()})

    await extension.before_turn(context)

    assert set(context.tools) == {"read_file", "write_file", "bash"}


async def test_the_sdk_writes_down_whether_the_reader_watched_the_question(tmp_path: Path, monkeypatch):
    """The whole chain: ``ask(watched=...)`` reaches the stored tags a resumed transcript is read from."""
    import zettcode.sdk as zc
    from sdk_helpers import ScriptedModel, config_for, wire

    wire(monkeypatch, ScriptedModel("a summary", "another summary"))
    async with zc.Client(config=config_for(tmp_path)) as client:
        await client.session.ask("watched", watched=True)
        await client.session.ask("not watched", watched=False)
        stored = SessionStore(client.config.store, client.config.workspace).read(client.session.id)

    questions = [line for line in stored.messages if _text(line.message[0]) in {"watched", "not watched"}]
    assert [(line.message[0].attributes.get("side"), line.tags.get("watched")) for line in questions] == [
        (True, True),
        (True, False),
    ]
    assert all(line.message[0].include_in_messages is False for line in questions)


async def test_a_side_exchange_from_before_both_tags_is_not_restored(tmp_path: Path):
    """A file written before a question said who asked it holds the reader's ``/btw`` and the recap's asks alike.

    Nothing in it tells them apart — same tags, same metadata — so the cheaper error is taken: the exchange is not
    restored. Showing the recap's instructions as the reader's words is a wrong conversation; dropping an aside is a
    missing line. New writes carry both tags, so this only covers files from before them.
    """
    store = SessionStore(tmp_path)
    old = {"side": True}
    await store.append("s1", "r1", question("what does parse() do?"), tags=old)
    await store.append("s1", "r1", AssistantMessage(content="it splits the header"), tags=old)

    replayed = replay(store.read("s1"))
    entries = [getattr(entry, "text", "") for entry in replayed.transcript.entries]

    assert entries == []
    assert replayed.history == ()


async def test_a_side_exchange_that_names_the_reader_is_restored_without_the_watched_tag(tmp_path: Path):
    """A file from a version that wrote ``origin`` but not ``watched`` keeps the reader's own questions."""
    store = SessionStore(tmp_path)
    old = {"side": True, "origin": READER}
    await store.append("s1", "r1", question("what does parse() do?"), tags=old)
    await store.append("s1", "r1", AssistantMessage(content="it splits the header"), tags=old)

    replayed = replay(store.read("s1"))
    entries = [getattr(entry, "text", "") for entry in replayed.transcript.entries]
    assert [entry.text for entry in replayed.transcript.entries if getattr(entry, "side", False)] == [
        "what does parse() do?"
    ]
    assert any("it splits the header" in text for text in entries)


def test_the_sdk_spells_the_readers_origin_the_way_the_engine_does():
    """The SDK keeps the default as a literal — importing the engine there would break its lazy import — so pin it."""
    from inspect import signature

    from zettcode.sdk.session import Session

    for name in ("ask", "ask_stream"):
        assert signature(getattr(Session, name)).parameters["origin"].default == READER
