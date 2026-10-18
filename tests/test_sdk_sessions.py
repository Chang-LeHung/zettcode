"""Sessions: many conversations in one client, reading them back, resuming, compacting, and the side channels."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import zettcode.sdk as zc
from sdk_helpers import ScriptedModel, asks_for, call, config_for, models, wire
from zettcode.sdk.errors import (
    NothingToDoError,
    RunTimeoutError,
    SessionBusyError,
    SessionLockedError,
    SessionNotFoundError,
)
from zettcode.sdk.types import Compaction, ContextReport, Message, ResumeInfo, SessionInfo


def make(tmp_path: Path, **changes) -> zc.Client:
    return zc.Client(config=config_for(tmp_path, **changes))


# -- several conversations ------------------------------------------------------------------------


async def test_a_new_session_is_empty_and_becomes_current_and_the_old_one_is_kept(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("in the first", "in the second"))
    async with make(tmp_path) as client:
        first = client.session
        await first.prompt("one")
        second = client.sessions.new()
        await second.prompt("two")

        assert second.id != first.id and client.session.id == second.id and second.current and not first.current
        assert [m.text for m in await first.history() if m.role == "user"] == ["one"]
        assert [m.text for m in await second.history() if m.role == "user"] == ["two"]


async def test_prompting_a_session_that_is_not_current_switches_back_to_it_with_its_conversation(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("a1", "b1", "a2"))
    async with make(tmp_path) as client:
        a = client.session
        await a.prompt("alpha question")
        b = client.sessions.new()
        await b.prompt("beta question")

        await a.prompt("alpha again")

        assert client.session.id == a.id
        seen = str(model.requests[2].messages)
        assert "alpha question" in seen and "a1" in seen and "beta question" not in seen


async def test_each_sessions_usage_stays_its_own_when_switching(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("a", "b", "c"))
    async with make(tmp_path) as client:
        a = client.session
        await a.prompt("1")
        await a.prompt("2")
        b = client.sessions.new()
        await b.prompt("3")

        assert a.usage.requests == 2 and b.usage.requests == 1
        await a.prompt("4")
        assert client.usage.requests == 3, "client.usage is the current session's"


async def test_an_empty_session_that_was_never_written_can_be_switched_to_and_back(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("x"))
    async with make(tmp_path) as client:
        a = client.session
        b = client.sessions.new()
        c = client.sessions.new()
        await a.prompt("go")

        assert client.session.id == a.id
        await b.prompt("go")
        assert client.session.id == b.id and c.id not in {s.id for s in await client.sessions.list()}


async def test_a_handle_for_the_same_session_is_the_same_object(tmp_path):
    async with make(tmp_path) as client:
        assert client.session is client.session
        assert client.sessions.new() is client.session


async def test_session_handles_have_a_readable_repr(tmp_path):
    async with make(tmp_path) as client:
        assert client.session.id in repr(client.session)


# -- listing and opening --------------------------------------------------------------------------


async def test_listing_shows_written_sessions_most_recent_first_with_titles_and_times(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("a", "b"))
    async with make(tmp_path) as client:
        first = client.session
        await first.prompt("one")
        await first.rename("The first")
        second = client.sessions.new()
        await second.prompt("two")

        listed = await client.sessions.list()

    assert [s.id for s in listed] == [second.id, first.id]
    assert all(isinstance(s, SessionInfo) for s in listed)
    assert listed[1].title == "The first" and listed[0].title is None
    assert listed[0].updated_at >= listed[0].created_at


async def test_listing_respects_the_limit_and_refuses_a_bad_one(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("x"))
    async with make(tmp_path) as client:
        for _ in range(3):
            await client.sessions.new().prompt("hi")

        assert len(await client.sessions.list(limit=2)) == 2
        for bad in (0, -1, True, 1.5, "2", None):
            with pytest.raises(ValueError, match="limit"):
                await client.sessions.list(limit=bad)


async def test_an_empty_workspace_lists_nothing_and_has_no_latest(tmp_path):
    async with make(tmp_path) as client:
        assert await client.sessions.list() == [] and await client.sessions.latest() is None


async def test_a_stored_session_can_be_opened_by_a_new_client_and_continued_with_its_history(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("remembered"))
    async with make(tmp_path) as client:
        await client.prompt("the code word is plum")
        old = client.session.id

    model = wire(monkeypatch, ScriptedModel("plum"))
    async with make(tmp_path) as later:
        reopened = await later.sessions.open(old)
        result = await reopened.prompt("what was it")

    assert result.text == "plum" and "the code word is plum" in str(model.requests[0].messages)
    assert result.usage.requests == 1, "the run's usage is the run's, even on a resumed session"


async def test_latest_continues_the_most_recent_session(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("a", "b"))
    async with make(tmp_path) as client:
        await client.sessions.new().prompt("old")
        newest = client.sessions.new()
        await newest.prompt("new")

    async with make(tmp_path) as later:
        assert (await later.sessions.latest()).id == newest.id and later.session.id == newest.id


async def test_a_client_can_be_made_straight_onto_a_stored_session(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one"))
    async with make(tmp_path) as client:
        await client.prompt("hello")
        stored = client.session.id

    async with zc.Client(config=config_for(tmp_path), resume=stored) as again:
        assert again.session.id == stored and len(await again.session.history()) == 2


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "nope",
        "../../etc/passwd",
        "a/b",
        "..",
        ".",
        "\x00",
        "x" * 5000,
        "01a14ec9-0000-0000-0000-000000000000",
    ],
)
async def test_opening_a_session_that_does_not_exist_or_cannot_be_one_is_a_not_found_error(tmp_path, bad):
    async with make(tmp_path) as client:
        before = client.session.id

        with pytest.raises(SessionNotFoundError):
            await client.sessions.open(bad)

        assert client.session.id == before, "a failed open changes nothing"


@pytest.mark.parametrize("bad", [None, 5, b"id", ["id"]])
async def test_opening_with_something_that_is_not_an_id_is_a_not_found_error_not_a_crash(tmp_path, bad):
    async with make(tmp_path) as client:
        with pytest.raises(SessionNotFoundError):
            await client.sessions.open(bad)


async def test_resuming_a_session_that_does_not_exist_fails_the_construction_cleanly(tmp_path):
    import os

    before = os.getcwd()

    with pytest.raises(SessionNotFoundError):
        zc.Client(config=config_for(tmp_path), resume="no-such-session")

    assert os.getcwd() == before


async def test_opening_while_a_run_is_in_progress_is_refused(tmp_path, monkeypatch):
    gate = asyncio.Event()

    async def hold(request):
        await gate.wait()
        return "x"

    wire(monkeypatch, ScriptedModel("seed", hold))
    async with make(tmp_path) as client:
        await client.prompt("seed")
        stored = client.session.id
        task = asyncio.create_task(client.run("slow"))
        await asyncio.sleep(0.05)

        with pytest.raises(SessionBusyError):
            await client.sessions.open(stored)
        gate.set()
        await task


async def test_a_session_continues_on_the_model_it_last_used(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("on b"))
    async with make(tmp_path, models=models("alpha", "beta")) as client:
        client.use_model("beta")
        await client.prompt("hello")
        stored = client.session.id

    async with make(tmp_path, models=models("alpha", "beta")) as later:
        assert later.model.name == "alpha"
        await later.sessions.open(stored)
        assert later.model.name == "beta"


# -- history --------------------------------------------------------------------------------------


async def test_history_is_what_was_said_in_order_with_tool_calls_and_results(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir(exist_ok=True)
    (tmp_path / "project" / "n.txt").write_text("contents")
    wire(monkeypatch, ScriptedModel(asks_for(call("read_file", {"path": "n.txt"}, call_id="r1")), "done reading"))
    async with make(tmp_path) as client:
        await client.prompt("read n.txt")
        history = await client.session.history()

    assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[0].text == "read n.txt" and all(isinstance(m, Message) for m in history)
    assert history[1].tool_calls[0].name == "read_file" and history[1].tool_calls[0].arguments == {"path": "n.txt"}
    assert history[2].tool_call_id == "r1" and history[2].tool_name == "read_file" and history[2].ok
    assert "contents" in history[2].text and history[3].text == "done reading"


async def test_history_of_a_session_never_written_is_a_not_found_error(tmp_path):
    async with make(tmp_path) as client:
        with pytest.raises(SessionNotFoundError):
            await client.session.history()


async def test_history_reads_a_session_another_client_has_open(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("kept"))
    async with make(tmp_path) as owner:
        await owner.prompt("hello")
        async with zc.Client(config=config_for(tmp_path), resume=owner.session.id) as reader:
            assert [m.text for m in await reader.session.history()] == ["hello", "kept"]


async def test_history_does_not_include_side_questions(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("main answer", "side answer"))
    async with make(tmp_path) as client:
        await client.prompt("main question")
        assert await client.session.ask("what about the side") == "side answer"
        texts = [m.text for m in await client.session.history()]

    assert texts == ["main question", "main answer"]


async def test_a_prompt_with_a_resolved_mention_is_shown_in_history_as_it_was_typed(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("ok"))
    async with make(tmp_path) as client:
        await client.prompt("plain words")

        assert (await client.session.history())[0].text == "plain words"


async def test_images_in_history_are_counted_not_embedded(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("a dot"))
    async with make(tmp_path, models=models("eyes", multimodal=True)) as client:
        await client.prompt(["look ", zc.Image(b"\x89PNG" + b"1" * 20, "image/png")])
        user = (await client.session.history())[0]

    assert user.images == 1 and user.text.startswith("look")


# -- naming, forking, exporting -------------------------------------------------------------------


async def test_renaming_stores_the_trimmed_title_and_shows_it_on_the_handle(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("x"))
    async with make(tmp_path) as client:
        await client.prompt("hi")

        assert await client.session.rename("  Parser bug  ") == "Parser bug"
        assert client.session.title == "Parser bug"


@pytest.mark.parametrize("bad", ["", "   ", "x" * 5000])
async def test_a_blank_or_absurdly_long_title_is_refused(tmp_path, monkeypatch, bad):
    wire(monkeypatch, ScriptedModel("x"))
    async with make(tmp_path) as client:
        await client.prompt("hi")

        with pytest.raises(ValueError):
            await client.session.rename(bad)
        assert client.session.title is None


async def test_the_title_of_an_unnamed_session_is_none_and_never_raises(tmp_path):
    async with make(tmp_path) as client:
        assert client.session.title is None


async def test_the_model_can_be_asked_to_name_a_session_and_will_not_rename_one_that_has_a_title(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("Fix the parser", "Fix the parser", "A different title"))
    async with make(tmp_path) as client:
        await client.prompt("the parser crashes")

        assert await client.session.name_it() == "Fix the parser"
        assert await client.session.name_it() == "Fix the parser", "already named: the title stands"


async def test_a_fork_is_a_new_session_with_the_same_context_and_the_original_is_untouched(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("first answer", "fork answer"))
    async with make(tmp_path) as client:
        original = client.session
        await original.prompt("shared question")
        fork = await original.fork()

        assert fork.id != original.id
        await fork.prompt("only in the fork")

        assert "shared question" in str(model.requests[1].messages)
        assert [m.text for m in await original.history() if m.role == "user"] == ["shared question"]
        assert [m.text for m in await fork.history() if m.role == "user"] == ["shared question", "only in the fork"]


async def test_forking_a_session_with_nothing_in_it_is_a_clear_error(tmp_path):
    async with make(tmp_path) as client:
        with pytest.raises(SessionNotFoundError):
            await client.session.fork()


async def test_exporting_writes_a_page_to_the_path_given_and_returns_it(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("an answer"))
    async with make(tmp_path) as client:
        await client.prompt("a question")
        target = tmp_path / "out" / "page.html"
        target.parent.mkdir()

        written = await client.session.export(target)

    assert written == target and "a question" in target.read_text(encoding="utf-8")
    assert "an answer" in target.read_text(encoding="utf-8")


async def test_exporting_to_a_place_that_cannot_be_written_is_an_error_not_a_hang(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("x"))
    blocker = tmp_path / "a-file"
    blocker.write_text("not a folder")
    async with make(tmp_path) as client:
        await client.prompt("hi")

        with pytest.raises((OSError, ValueError)):
            await client.session.export(blocker / "page.html")


# -- side questions and steering ------------------------------------------------------------------


async def test_a_side_question_sees_the_conversation_and_adds_nothing_to_it(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("main", "the side reply", "next main"))
    async with make(tmp_path) as client:
        await client.prompt("the project is called Zeta")
        answer = await client.session.ask("what is the project called")
        await client.prompt("continue")

        assert answer == "the side reply"
        assert "Zeta" in str(model.requests[1].messages)
        assert "what is the project called" not in str(model.requests[2].messages)
        assert "the side reply" not in str(model.requests[2].messages)


@pytest.mark.parametrize("empty", ["", "  ", "\n"])
async def test_an_empty_side_question_is_refused(tmp_path, empty):
    async with make(tmp_path) as client:
        with pytest.raises(ValueError, match="empty"):
            await client.session.ask(empty)


async def test_a_side_question_is_not_a_conversation_and_does_not_leave_the_side_mode_on(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("a", "b", "c"))
    async with make(tmp_path) as client:
        await client.prompt("one")
        await client.session.ask("aside")
        await client.prompt("two")

        assert [m.text for m in await client.session.history() if m.role == "user"] == ["one", "two"]


async def test_steering_with_nothing_running_is_false_and_queues_nothing(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("x"))
    async with make(tmp_path) as client:
        assert client.session.steer("hurry") is False
        await client.prompt("go")
        assert client.session.steer("too late") is False


@pytest.mark.parametrize("bad", ["", "   ", None, 5, b"x"])
async def test_steering_with_a_blank_or_non_text_message_is_false(tmp_path, monkeypatch, bad):
    gate = asyncio.Event()

    async def hold(request):
        await gate.wait()
        return "done"

    wire(monkeypatch, ScriptedModel(hold))
    async with make(tmp_path) as client:
        task = asyncio.create_task(client.run("slow"))
        await asyncio.sleep(0.05)

        assert client.session.steer(bad) is False
        gate.set()
        await task


async def test_steering_a_running_request_is_accepted_and_reaches_the_model(tmp_path, monkeypatch):
    gate = asyncio.Event()

    async def first(request):
        await gate.wait()
        return asks_for(call("read_file", {"path": "x"}, call_id="r"))

    model = wire(monkeypatch, ScriptedModel(first, "adjusted"))
    async with make(tmp_path) as client:
        task = asyncio.create_task(client.run("start"))
        await asyncio.sleep(0.05)

        accepted = client.session.steer("actually do it differently")
        gate.set()
        result = await task

    assert accepted is True and result.text == "adjusted"
    assert "actually do it differently" in str(model.requests[1].messages)


async def test_steering_another_session_than_the_running_one_is_false(tmp_path, monkeypatch):
    gate = asyncio.Event()

    async def hold(request):
        await gate.wait()
        return "done"

    wire(monkeypatch, ScriptedModel(hold))
    async with make(tmp_path) as client:
        other = client.session
        task = asyncio.create_task(client.run("slow"))
        await asyncio.sleep(0.05)
        stranger = type(other)(client, "some-other-session")

        assert stranger.steer("hey") is False
        gate.set()
        await task


# -- resuming an interrupted request --------------------------------------------------------------


async def test_a_session_that_finished_has_nothing_to_resume(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("done"))
    async with make(tmp_path) as client:
        await client.prompt("go")

        assert await client.session.resumable() is None
        with pytest.raises(NothingToDoError):
            await client.session.resume()


async def test_a_run_cut_short_can_be_picked_up_where_it_stopped(tmp_path, monkeypatch):
    never = asyncio.Event()

    async def stuck(request):
        await never.wait()
        return "never"

    model = wire(monkeypatch, ScriptedModel(stuck, "picked up"))
    async with make(tmp_path) as client:
        with pytest.raises(RunTimeoutError):
            await client.prompt("a task that gets interrupted", timeout=0.2)

        point = await client.session.resumable()
        assert isinstance(point, ResumeInfo) and point.description
        result = await client.session.resume()

    assert result.text == "picked up" and "a task that gets interrupted" in str(model.requests[1].messages)


async def test_resuming_a_session_with_no_messages_is_nothing_to_do_and_says_why(tmp_path):
    async with make(tmp_path) as client:
        with pytest.raises(NothingToDoError) as caught:
            await client.session.resume()

    assert str(caught.value)


# -- context and compaction -----------------------------------------------------------------------


async def test_the_context_is_unknown_before_the_first_reply_and_measured_after(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("hello there"))
    async with make(tmp_path) as client:
        assert await client.session.context() is None
        await client.prompt("hi")
        report = await client.session.context()

    assert isinstance(report, ContextReport) and report.window > 0 and report.used > 0
    assert 0 < report.fraction < 1 and report.free == report.window - report.used
    assert {share.name for share in report.shares} >= {"User messages"}


async def test_the_context_of_a_resumed_session_is_measured_too(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one"))
    async with make(tmp_path) as client:
        await client.prompt("hi")
        stored = client.session.id

    async with zc.Client(config=config_for(tmp_path), resume=stored) as again:
        report = await again.session.context()

    assert report is not None and report.used > 0


async def test_compacting_replaces_the_older_messages_with_a_summary(tmp_path, monkeypatch):
    steps = []
    for number in range(6):
        steps.append(f"reply {number}")
    steps.append("SUMMARY of the work so far")
    steps.append("after")
    model = wire(monkeypatch, ScriptedModel(*steps))
    async with make(tmp_path) as client:
        for number in range(6):
            await client.prompt(f"question {number} " + "padding " * 30)

        compaction = await client.session.compact()

        assert isinstance(compaction, Compaction) and "SUMMARY" in compaction.summary
        assert compaction.compressed >= 1 and compaction.kept >= 0
        await client.prompt("what now")

    assert "SUMMARY of the work so far" in str(model.requests[-1].messages)


async def test_compacting_twice_in_a_row_says_it_is_already_compacted(tmp_path, monkeypatch):
    steps = [f"reply {n}" for n in range(6)] + ["a summary", "unused"]
    wire(monkeypatch, ScriptedModel(*steps))
    async with make(tmp_path) as client:
        for number in range(6):
            await client.prompt(f"question {number} " + "padding " * 30)
        await client.session.compact()

        with pytest.raises(NothingToDoError, match="Already compacted"):
            await client.session.compact()


async def test_compacting_a_session_with_almost_nothing_in_it_does_not_crash(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("only reply", "summary"))
    async with make(tmp_path) as client:
        await client.prompt("hi")

        result = await client.session.compact()

    assert result is None or isinstance(result, Compaction)


async def test_compacting_a_session_another_client_has_open_is_refused(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("x"))
    async with make(tmp_path) as owner:
        await owner.prompt("hi")
        async with zc.Client(config=config_for(tmp_path), resume=owner.session.id) as other:
            with pytest.raises(SessionLockedError):
                await other.session.compact()
            with pytest.raises(SessionLockedError):
                await other.session.rename("mine now")
            with pytest.raises(SessionLockedError):
                await other.prompt("write")
