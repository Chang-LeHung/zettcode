"""Why a model stopped, shown when it was not a normal ending; and ``/continue``, which picks the request up again.

Through the real shell and the real ``OpenAIProvider`` over an HTTP exchange written in the test, so the stop is what
the library classifies and the resume is what the library does.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from zett_agent.messages import AssistantMessage, UserMessage
from zett_agent.providers.openai import OpenAIProvider
from zett_agent.stop import StopInfo, StopReason

from test_model_failures import FAST, piece, sse
from zettcode.app.agent import runtime as runtime_module
from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.conversation.stops import stop_text
from zettcode.app.ui.app import ZettCodeApp
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.tui.testing import Harness

# -- the sentence --------------------------------------------------------------------------------------------------


def stop(reason: StopReason, **fields) -> StopInfo:
    return StopInfo(reason=reason, **fields)


@pytest.mark.parametrize("reason", [StopReason.END_TURN, StopReason.TOOL_USE])
def test_a_normal_ending_has_nothing_to_say(reason):
    assert stop_text(stop(reason)) == ""


def test_a_reply_that_hit_the_output_limit_says_so_and_offers_continue():
    said = stop_text(stop(StopReason.MAX_OUTPUT, raw="length"))

    assert "output limit" in said and "cut off" in said and "/continue" in said


def test_a_reply_cut_off_by_the_provider_offers_to_start_it_again():
    said = stop_text(stop(StopReason.INTERRUPTED, raw="error", message="upstream reset"))

    assert "cut off" in said and "upstream reset" in said and "/continue" in said


def test_a_refusal_says_what_the_provider_said_and_does_not_offer_continue_because_it_would_be_declined_again():
    said = stop_text(stop(StopReason.REFUSAL, raw="content_filter", message="blocked by policy", category="safety"))

    assert "declined" in said and "safety: blocked by policy" in said
    assert "/continue" not in said and "/model" in said


def test_a_full_context_offers_compact_not_continue():
    said = stop_text(stop(StopReason.CONTEXT_FULL))

    assert "/compact" in said and "/continue" not in said


def test_a_stop_nobody_knows_is_said_to_be_unknown_with_the_raw_word():
    said = stop_text(stop(StopReason.OTHER, raw="weird_new_reason"))

    assert "does not know" in said and "weird_new_reason" in said


def test_tool_calls_the_library_withheld_are_named_so_the_reader_knows_they_did_not_run():
    said = stop_text(stop(StopReason.REFUSAL, detail={"withheld_tool_calls": ["bash", "edit", "bash"]}))

    assert "bash, edit" in said and "not done" in said


def test_a_suggested_model_is_passed_on():
    assert "gpt-5" in stop_text(stop(StopReason.REFUSAL, recommended_model="gpt-5"))


def test_the_sentence_is_whole_sentences_ending_in_a_full_stop():
    for reason in StopReason:
        said = stop_text(stop(reason, message="odd words"))
        assert said == "" or said.endswith((".", "!", "?")), said


# -- the shell ----------------------------------------------------------------------------------------------------


@pytest.fixture
def shell(tmp_path: Path, monkeypatch):
    def build(handler) -> tuple[ZettCodeApp, Harness]:
        monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
        monkeypatch.setattr(
            runtime_module,
            "_build_provider",
            lambda selected: OpenAIProvider(
                "gpt-9", "k", transport=httpx.MockTransport(handler), base_url="https://x/v1", retry=FAST
            ),
        )
        (tmp_path / "work").mkdir(exist_ok=True)
        config = ZettCodeConfig(
            workspace=tmp_path / "work",
            models=(ModelConfig(model="gpt-9", token="k"),),
            store=tmp_path / "sessions",
            plugins_enabled=False,
            skills_enabled=False,
            mcp_enabled=False,
            sessions_enabled=False,
            tips=False,
            statusline_hidden=("pet",),
        )
        app = ZettCodeApp(ZettCodeAgent(runtime_module.ZettCodeEngine.preview(config)))
        app.app.resize(110, 30)
        app.app.mount()
        return app, Harness(app=app.app)

    return build


async def say(app: ZettCodeApp, harness: Harness, text: str) -> str:
    harness.write(text)
    harness.press("enter")
    await asyncio.wait_for(app.task, 10)
    return " ".join(harness.render().text.split())


def answering(*replies: str):
    """A provider that gives each request the next reply, a list of (text, finish_reason) chunks as one stream."""
    seen: list[dict] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if not str(body["messages"][0]["content"]).startswith("You are ZettCode"):
            # The title the shell asks for after a reply is a request of its own, and not the conversation's.
            return httpx.Response(200, text=sse(piece("A title"), piece(finish="stop")), headers=SSE)
        seen.append(body)
        return httpx.Response(200, text=queue.pop(0), headers=SSE)

    handler.requests = seen  # type: ignore[attr-defined]
    return handler


SSE = {"content-type": "text/event-stream"}
CUT_OFF = sse(piece("The answer begins"), piece(finish="length"))
WHOLE = sse(piece("All of it."), piece(finish="stop"))
REFUSED = sse(piece("I can't help with"), piece(finish="content_filter"))


async def test_a_reply_that_ran_into_the_output_limit_is_followed_by_the_line_that_says_so(shell):
    app, harness = shell(answering(CUT_OFF))

    screen = await say(app, harness, "write a lot")

    assert "The answer begins" in screen
    assert "output limit" in screen and "/continue" in screen


async def test_a_refusal_is_shown_as_one_and_not_as_an_answer(shell):
    app, harness = shell(answering(REFUSED))

    screen = await say(app, harness, "do something")

    assert "declined this request" in screen and "/continue" not in screen
    assert "Rephrase the request" in screen


async def test_a_reply_that_finished_normally_gets_no_such_line(shell):
    app, harness = shell(answering(WHOLE))

    screen = await say(app, harness, "hi")

    assert "All of it." in screen
    for word in ("output limit", "declined", "cut off", "does not know"):
        assert word not in screen


async def test_the_line_is_an_error_row_so_it_is_in_the_error_colour(shell):
    app, harness = shell(answering(CUT_OFF))
    await say(app, harness, "write a lot")

    rows = [e for e in app.transcript.entries if getattr(e, "level", None) == "error"]

    assert any("output limit" in e.text for e in rows)


# -- /continue -----------------------------------------------------------------------------------------------------


async def test_continue_after_a_cut_off_reply_asks_the_model_to_carry_on_and_shows_what_it_wrote(shell):
    handler = answering(CUT_OFF, sse(piece(" and here is the rest."), piece(finish="stop")))
    app, harness = shell(handler)
    await say(app, harness, "write a lot")

    screen = await say(app, harness, "/continue")

    assert len(handler.requests) == 2
    assert "reached the output limit" in screen, "the reader is told what is about to be done"
    assert "and here is the rest." in screen and "Continued for" in screen
    last = handler.requests[1]["messages"][-1]
    assert last["role"] == "user" and "continue" in last["content"].lower(), "the model is asked to carry on"


async def test_continue_does_not_send_anything_the_reader_typed_and_adds_no_user_row(shell):
    app, harness = shell(answering(CUT_OFF, WHOLE))
    await say(app, harness, "write a lot")
    users = lambda: [e for e in app.transcript.entries if getattr(e, "kind", None) == "user"]  # noqa: E731
    before = len(users())

    await say(app, harness, "/continue")

    assert len(users()) == before


async def test_continue_after_a_reply_that_finished_says_there_is_nothing_to_continue_and_calls_no_model(shell):
    handler = answering(WHOLE)
    app, harness = shell(handler)
    await say(app, harness, "hi")

    screen = await say(app, harness, "/continue")

    assert "nothing to resume" in screen and len(handler.requests) == 1


async def test_continue_after_a_refusal_says_why_it_would_not_help(shell):
    handler = answering(REFUSED)
    app, harness = shell(handler)
    await say(app, harness, "do something")

    screen = await say(app, harness, "/continue")

    assert "would be declined again" in screen and len(handler.requests) == 1


async def test_continue_in_a_session_with_nothing_in_it_says_so(shell):
    handler = answering()
    app, harness = shell(handler)

    screen = await say(app, harness, "/continue")

    assert "nothing to resume" in screen and handler.requests == []


async def test_continue_is_a_command_the_menu_offers_and_help_lists(shell):
    app, _ = shell(answering())

    from zettcode.app.ui.widgets import help_text

    assert any(c.name == "/continue" for c in app.commands)
    assert "`/continue`" in help_text(app.commands)


async def test_a_reply_the_provider_ended_with_an_error_is_shown_as_cut_off_and_continue_asks_for_it_again(shell):
    handler = answering(sse(piece("Half of an ans"), piece(finish="error")), WHOLE)
    app, harness = shell(handler)

    first = await say(app, harness, "question")
    assert "cut off before the model finished it" in first and "/continue" in first

    screen = await say(app, harness, "/continue")

    assert "start that response again" in screen or "start it again" in screen or "All of it." in screen
    assert "All of it." in screen and len(handler.requests) == 2
    told = handler.requests[1]["messages"][-1]
    assert told["role"] == "user" and "interrupt" in told["content"].lower(), "the model is told it was cut off"


# -- the file tools under their new names --------------------------------------------------------------------------


def test_the_agents_edit_tool_is_drawn_as_an_edit_with_its_diff_and_the_old_name_still_is_for_stored_sessions():
    from zettcode.app import Transcript, TranscriptSource
    from zettcode.tui import DARK

    for name in ("edit", "replace_in_file"):
        transcript = Transcript(clock=lambda: 0.0)
        transcript.start_tool("c", name, {"path": "a.py", "edits": [{"old_text": "x", "new_text": "y"}]})
        transcript.complete_tool("c", "Replaced 1 occurrence in a.py", wait=False)
        source = TranscriptSource(transcript, theme=DARK)
        text = "\n".join(source.line(i, 80).text for i in range(source.count(80)))

        assert "Edited a.py" in text, (name, text)


def test_read_is_drawn_as_a_read():
    from zettcode.app import Transcript, TranscriptSource
    from zettcode.tui import DARK

    transcript = Transcript(clock=lambda: 0.0)
    transcript.start_tool("c", "read", {"path": "a.py"})
    transcript.complete_tool("c", "print(1)", wait=False)
    source = TranscriptSource(transcript, theme=DARK)

    assert "Read a.py" in "\n".join(source.line(i, 80).text for i in range(source.count(80)))


# -- a stored session shows the same line ------------------------------------------------------------------------


def test_a_stored_reply_that_stopped_early_shows_the_same_line_when_the_session_is_opened_again():
    from zettcode.app.agent.conversation.replay import entries_added_by

    cut = AssistantMessage(content="The answer begins", stop=stop(StopReason.MAX_OUTPUT, raw="length"))
    whole = AssistantMessage(content="All of it.")

    assert entries_added_by(cut) == entries_added_by(whole) + 1, "the line is one more row, counted for the window"
    assert isinstance(UserMessage(content="x"), UserMessage)


async def test_a_stop_survives_the_session_store_so_a_session_opened_later_can_be_continued(tmp_path: Path):
    from zettcode.app.agent.storage import SessionStore

    store = SessionStore(tmp_path, tmp_path)
    cut = AssistantMessage(content="The answer begins", stop=stop(StopReason.MAX_OUTPUT, raw="length"))
    await store.append("s", "r", UserMessage(content="write a lot"))
    await store.append("s", "r", cut)

    stored = [line.message[0] for line in store.read("s").branch() if isinstance(line.message[0], AssistantMessage)]

    assert stored[-1].stop is not None and stored[-1].stop.reason is StopReason.MAX_OUTPUT


async def test_opening_a_stored_session_whose_last_reply_was_cut_short_shows_why_and_continue_works_on_it(
    shell, tmp_path: Path
):
    handler = answering(CUT_OFF, sse(piece(" the rest."), piece(finish="stop")))
    app, harness = shell(handler)
    await say(app, harness, "write a lot")
    session_id = app.agent.session_id

    app.agent.runtime.session_locks.release()  # the first shell has gone, as it would have
    app2, harness2 = shell(handler)
    await app2.resume_session(session_id)
    shown = " ".join(harness2.render().text.split())

    assert "The answer begins" in shown and "output limit" in shown
    assert "the rest." in await say(app2, harness2, "/continue")


async def test_a_continued_request_records_the_model_it_used_in_the_session_like_a_turn_does(shell):
    app, harness = shell(answering(CUT_OFF, WHOLE))
    await say(app, harness, "write a lot")
    app.agent.runtime.persistence.set_model(app.agent.session_id, "something else")

    await say(app, harness, "/continue")

    assert app.agent.runtime.persistence.session_model(app.agent.session_id) == app.agent.active_model.shown_name
