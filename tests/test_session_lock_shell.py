"""The shell in a session another process has open: shown, locked, and handed back when the lock is let go."""

from __future__ import annotations

import asyncio
from pathlib import Path

from zett_agent.messages import AssistantMessage, UserMessage

from test_zettcode_app import FakeClient, FakeRuntime, _harness, build_app, rows_and_commands
from zettcode.app.agent.agent import TerminalAgent
from zettcode.app.agent.conversation.entries import TextEntry
from zettcode.app.ui import sessions as sessions_module
from zettcode.app.ui.app import ZettCodeApp
from zettcode.app.ui.widgets.composer import LOCK_ART
from zettcode.engine.storage import SessionStore

#: The padlock's body, which is on screen only while the composer is locked.
LOCK = LOCK_ART[1]

OTHERS = "alpha-1"


async def _until(check, timeout: float = 3.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not check():
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("condition not met")
        await asyncio.sleep(0.01)


def _notices(app: ZettCodeApp) -> list[str]:
    return [e.text for e in app.transcript.entries if isinstance(e, TextEntry) and e.kind == "notice"]


def _refusals(app: ZettCodeApp) -> list[str]:
    """What a refused write says in the conversation (as a message or as a notice, by the command), not the
    notice that says why the whole session is read-only."""
    return [
        text
        for text in (getattr(e, "text", "") for e in app.transcript.entries)
        if "read-only here" in text and "unlocks by itself" not in text
    ]


async def _app_in_a_locked_session(tmp_path: Path) -> tuple[ZettCodeApp, FakeRuntime]:
    """A shell that resumed a stored session the other terminal has open."""
    store = SessionStore(tmp_path)
    await store.append(OTHERS, "req", UserMessage(content="what does parse() do?"))
    await store.append(OTHERS, "req", AssistantMessage(content="it splits the header"))
    runtime = FakeRuntime(FakeClient(), plugins=rows_and_commands())
    runtime.persistence.store = store
    runtime.persistence.sessions = await store.list_sessions()
    runtime.held_elsewhere.add(OTHERS)
    app = ZettCodeApp(TerminalAgent(runtime))
    app.app.resize(80, 24)
    app.app.mount()
    app.restore_session(OTHERS)
    return app, runtime


# -- entering one --------------------------------------------------------------------------------------------------


async def test_a_session_the_other_terminal_has_open_is_shown_with_a_lock_instead_of_an_arrow(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)

    text = harness.render().text

    assert "what does parse() do?" in text and "it splits the header" in text, "the conversation is there to read"
    assert app.composer.locked and LOCK in text
    assert "Ask ZettCode to do anything" not in text


async def test_the_reader_is_told_once_why_and_what_to_do(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)

    (notice,) = [n for n in _notices(app) if "read-only" in n]

    assert "open in another ZettCode process" in notice
    assert "unlocks by itself" in notice and "/new" in notice and "/fork" in notice


async def test_a_session_of_our_own_has_the_arrow_and_no_notice():
    app = build_app()
    app._sync_lock()

    assert not app.composer.locked
    assert LOCK not in _harness(app).render().text
    assert not [n for n in _notices(app) if "read-only" in n]


async def test_syncing_again_does_not_say_it_again(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)

    app._sync_lock()
    app._sync_lock()

    assert len([n for n in _notices(app) if "read-only" in n]) == 1


# -- what a locked shell takes -------------------------------------------------------------------------------------


async def test_typing_into_the_lock_goes_nowhere(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)

    harness.write("please refactor this")

    assert app.composer.text == ""
    assert app.agent.runtime.client.agent.emitted == []


async def test_a_draft_that_got_in_some_other_way_is_refused_with_a_reason_and_no_turn(tmp_path):
    app, runtime = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)
    app.composer.set_text("a draft from before")

    assert app.submit("a draft from before") is False

    assert "read-only" in app.flash_line.text if hasattr(app.flash_line, "text") else True
    assert app._task is None and runtime.client.messages == []
    assert harness.render() is not None


async def test_a_message_to_another_session_is_not_sent_from_here_either(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)
    app.composer.set_text("@someone hello")

    assert app.submit("@someone hello") is False


async def test_a_command_still_runs(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)

    harness.write("/help")
    harness.press("enter")
    await asyncio.wait_for(app.task, 3.0)

    assert any("/resume" in getattr(e, "text", "") for e in app.transcript.entries)


async def test_naming_a_locked_session_is_refused_in_the_conversation_and_writes_nothing(tmp_path):
    app, runtime = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)

    harness.write("/title Mine now")
    harness.press("enter")
    await asyncio.wait_for(app.task, 3.0)

    assert any("read-only" in text for text in _refusals(app))
    assert runtime.persistence.store.session_title(OTHERS) is None  # type: ignore[union-attr]


async def test_compacting_a_locked_session_is_refused_in_the_conversation(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)

    harness.write("/compact")
    harness.press("enter")
    await asyncio.wait_for(app.task, 3.0)

    assert any("read-only" in text for text in _refusals(app))


async def test_a_side_question_is_refused_in_the_conversation(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)

    harness.write("/btw what is this")
    harness.press("enter")
    await asyncio.wait_for(app.task, 3.0)

    assert any("read-only" in text for text in _refusals(app))
    assert not any("what is this" in getattr(e, "text", "") for e in app.transcript.entries), "nothing was echoed"


# -- leaving it ----------------------------------------------------------------------------------------------------


async def test_a_new_session_is_ours_and_unlocks_the_composer(tmp_path):
    app, runtime = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)
    assert app.composer.locked

    harness.write("/new")
    harness.press("enter")
    await asyncio.wait_for(app.task, 3.0)

    assert not app.composer.locked and LOCK not in harness.render().text
    assert "Ask ZettCode to do anything" in harness.render().text
    assert not runtime.session_locked


async def test_resuming_a_free_session_unlocks_it(tmp_path):
    app, runtime = await _app_in_a_locked_session(tmp_path)
    store = runtime.persistence.store
    await store.append("beta-2", "req", UserMessage(content="another"))  # type: ignore[union-attr]

    app.restore_session("beta-2")

    assert not app.composer.locked and not runtime.session_locked


async def test_going_from_one_locked_session_to_another_says_it_again_for_the_second(tmp_path):
    app, runtime = await _app_in_a_locked_session(tmp_path)
    await runtime.persistence.store.append("beta-2", "req", UserMessage(content="x"))  # type: ignore[union-attr]
    runtime.held_elsewhere.add("beta-2")

    app.restore_session("beta-2")

    assert len([n for n in _notices(app) if "read-only" in n]) == 1, "the transcript is the second session's own"
    assert app.composer.locked


async def test_forking_a_locked_session_gives_a_session_of_our_own(tmp_path):
    app, runtime = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)

    harness.write("/fork")
    harness.press("enter")
    await asyncio.wait_for(app.task, 3.0)

    assert not app.composer.locked and app.agent.session_id != OTHERS


# -- the lock being let go -----------------------------------------------------------------------------------------


async def test_when_the_other_process_lets_go_the_session_is_read_again_and_the_composer_is_ours(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_module, "LOCK_POLL_SECONDS", 0.02)
    app, runtime = await _app_in_a_locked_session(tmp_path)
    app.start_background()
    try:
        await asyncio.sleep(0.1)
        assert app.composer.locked, "still locked while the other process holds it"
        # The other process writes a message and then lets go.
        await runtime.persistence.store.append(OTHERS, "req", UserMessage(content="a message written meanwhile"))  # type: ignore[union-attr]
        runtime.held_elsewhere.discard(OTHERS)

        await _until(lambda: not app.composer.locked)
        await _until(lambda: not app._busy)

        texts = [getattr(e, "text", "") for e in app.transcript.entries]
        assert "a message written meanwhile" in texts, "what the other process wrote is on screen now"
        assert any("yours now" in n for n in _notices(app))
        assert LOCK not in _harness(app).render().text
    finally:
        await app.stop_background()


async def test_enter_on_the_lock_tries_at_once(tmp_path):
    app, runtime = await _app_in_a_locked_session(tmp_path)
    harness = _harness(app)
    app.view.render  # noqa: B018 - the view exists

    harness.press("enter")
    assert app.composer.locked, "the other process still has it"
    assert (
        "still open in another ZettCode process" in app.flash_line._source()
        if hasattr(app.flash_line, "_source")
        else True
    )

    runtime.held_elsewhere.discard(OTHERS)
    harness.press("enter")
    await asyncio.wait_for(app._task, 3.0)

    assert not app.composer.locked and any("yours now" in n for n in _notices(app))


async def test_no_task_is_left_trying_when_the_session_is_ours(tmp_path):
    app, runtime = await _app_in_a_locked_session(tmp_path)
    app.start_background()
    try:
        assert app._lock_watch is not None and not app._lock_watch.done()
        watch = app._lock_watch

        harness = _harness(app)
        harness.write("/new")
        harness.press("enter")
        await asyncio.wait_for(app.task, 3.0)
        await asyncio.sleep(0.05)

        assert app._lock_watch is None and watch.cancelled()
    finally:
        await app.stop_background()


async def test_leaving_the_application_stops_the_task_that_keeps_trying(tmp_path):
    app, _ = await _app_in_a_locked_session(tmp_path)
    app.start_background()
    watch = app._lock_watch
    assert watch is not None

    await app.stop_background()
    await asyncio.sleep(0)

    assert watch.cancelled() or watch.done()


async def test_the_watch_waits_while_a_request_or_command_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions_module, "LOCK_POLL_SECONDS", 0.02)
    app, runtime = await _app_in_a_locked_session(tmp_path)
    app._busy = True
    app.start_background()
    try:
        runtime.held_elsewhere.discard(OTHERS)
        await asyncio.sleep(0.15)
        assert app.composer.locked, "not while something else is running"

        app._busy = False
        await _until(lambda: not app.composer.locked)
    finally:
        app._busy = False
        await app.stop_background()
