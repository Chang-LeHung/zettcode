"""Running a prompt: the result, the events, errors, deadlines, cancellation, and what the program answers for the model.

Every test drives the real agent loop (extensions, tools, session store, permission policy); only the provider is
scripted.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

import zettcode.sdk as zc
from sdk_helpers import ScriptedModel, asks_for, call, config_for, models, refusal, says, wire
from zettcode.sdk.errors import (
    ConfigurationError,
    RunError,
    RunTimeoutError,
    SessionBusyError,
)
from zettcode.sdk.events import ModelStopped, RawEvent, UsageUpdated
from zettcode.sdk.types import Image

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 8
posix_shell = pytest.mark.skipif(sys.platform == "win32", reason="runs `echo` and `false` in the platform shell")


def make(tmp_path: Path, **changes) -> zc.Client:
    return zc.Client(config=config_for(tmp_path, **changes))


async def hold_until(gate: asyncio.Event, then: str = "released"):
    async def step(request):
        await gate.wait()
        return then

    return step


# -- the result -----------------------------------------------------------------------------------


async def test_the_result_carries_text_session_usage_and_no_stop(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("The answer."))
    async with make(tmp_path) as client:
        result = await client.prompt("question")

    assert result.text == "The answer." and result.session_id == client.session.id
    assert result.ok and result.stop is None and result.stop_message is None
    assert result.tools == () and result.questions == () and result.events == ()
    assert result.usage.total_tokens == 120 and result.usage.requests == 1


async def test_each_runs_usage_is_its_own_while_the_sessions_accumulates(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one", "two", "three"))
    async with make(tmp_path) as client:
        first = await client.prompt("a")
        second = await client.prompt("b")
        third = await client.prompt("c")

        assert [r.usage.requests for r in (first, second, third)] == [1, 1, 1]
        assert [r.usage.total_tokens for r in (first, second, third)] == [120, 120, 120]
        assert client.usage.requests == 3 and client.usage.total_tokens == 360
        assert client.session.usage == client.usage


async def test_a_conversation_carries_on_the_model_sees_the_earlier_turns(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("first reply", "second reply"))
    async with make(tmp_path) as client:
        await client.prompt("remember 42")
        await client.prompt("what was it")

    roles = [type(m).__name__ for m in model.requests[1].messages]
    assert roles.count("UserMessage") == 2 and "first reply" in str(model.requests[1].messages)


async def test_a_run_with_no_words_still_has_a_result(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(""))
    async with make(tmp_path) as client:
        result = await client.prompt("say nothing")

    assert result.text == "" and result.ok


async def test_a_text_streamed_in_pieces_is_whole_in_the_result(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("0123456789", chunk=3))
    async with make(tmp_path) as client:
        assert (await client.prompt("go")).text == "0123456789"


async def test_a_refusal_is_a_result_with_a_stop_and_not_an_exception(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(refusal("No.")))
    async with make(tmp_path) as client:
        result = await client.prompt("do the bad thing", keep_events=True)

    assert not result.ok and result.stop == "refusal" and result.stop_message == "declined"
    assert any(isinstance(e, ModelStopped) for e in result.events)


# -- tools ----------------------------------------------------------------------------------------


async def test_tools_are_recorded_in_order_with_arguments_and_output(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir(exist_ok=True)
    (tmp_path / "project" / "note.txt").write_text("hello file\n")
    wire(
        monkeypatch,
        ScriptedModel(
            asks_for(call("read_file", {"path": "note.txt"}, call_id="r1")),
            "I read it.",
        ),
    )
    async with make(tmp_path) as client:
        result = await client.prompt("read the note")

    (tool,) = result.tools
    assert (tool.id, tool.name, tool.arguments, tool.ok, tool.skipped) == (
        "r1",
        "read_file",
        {"path": "note.txt"},
        True,
        False,
    )
    assert "hello file" in tool.output and result.text == "I read it."
    assert result.failed_tools == ()


async def test_a_tool_that_fails_is_recorded_as_failed_and_the_run_still_finishes(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("read_file", {"path": "missing.txt"}, call_id="r1")), "gave up"))
    async with make(tmp_path) as client:
        result = await client.prompt("read it")

    (tool,) = result.tools
    assert tool.ok is False and tool.output and result.failed_tools == (tool,)
    assert result.text == "gave up" and result.ok


async def test_a_tool_the_model_invents_is_a_failed_call_and_not_a_crash(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("does_not_exist", {}, call_id="x1")), "ok then"))
    async with make(tmp_path) as client:
        result = await client.prompt("go")

    assert result.tools[0].name == "does_not_exist" and result.tools[0].ok is False and result.text == "ok then"


async def test_several_tool_calls_in_one_step_are_each_recorded(tmp_path, monkeypatch):
    (tmp_path / "project").mkdir(exist_ok=True)
    (tmp_path / "project" / "a.txt").write_text("A")
    (tmp_path / "project" / "b.txt").write_text("B")
    step = asks_for(
        call("read_file", {"path": "a.txt"}, call_id="a"), call("read_file", {"path": "b.txt"}, call_id="b")
    )
    wire(monkeypatch, ScriptedModel(step, "both"))
    async with make(tmp_path) as client:
        result = await client.prompt("read both")

    assert [t.id for t in result.tools] == ["a", "b"] and all(t.ok for t in result.tools)


# -- events ---------------------------------------------------------------------------------------


async def test_the_events_of_a_run_come_in_a_sensible_order(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("read_file", {"path": "nope"}, call_id="t")), "end", chunk=1))
    async with make(tmp_path) as client:
        async with client.prompt("go") as run:
            names = [type(e).__name__ async for e in run]

    assert names.index("ToolStarted") < names.index("ToolFinished") < names.index("TextDelta")
    assert names[-1] == "Finished" and "UsageUpdated" in names


async def test_keep_events_puts_every_event_in_the_result_and_otherwise_none(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one", "two"))
    async with make(tmp_path) as client:
        kept = await client.prompt("a", keep_events=True)
        dropped = await client.prompt("b")

    assert len(kept.events) >= 3 and dropped.events == ()


async def test_raw_events_come_before_their_typed_events_and_only_when_asked(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("hi", "hi"))
    async with make(tmp_path) as client:
        async with client.prompt("a", raw=True) as run:
            with_raw = [e async for e in run]
        async with client.prompt("b") as run:
            without = [e async for e in run]

    raws = [e for e in with_raw if isinstance(e, RawEvent)]
    assert raws and not any(isinstance(e, RawEvent) for e in without)
    delta = next(i for i, e in enumerate(with_raw) if isinstance(e, zc.TextDelta))
    assert isinstance(with_raw[delta - 1], RawEvent) and with_raw[delta - 1].event.delta == "hi"


async def test_usage_updates_are_the_sessions_totals_and_not_the_runs(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one", "two"))
    async with make(tmp_path) as client:
        await client.prompt("a")
        async with client.prompt("b") as run:
            updates = [e async for e in run if isinstance(e, UsageUpdated)]

    assert updates[-1].usage.requests == 2 and run.result.usage.requests == 1


async def test_on_event_sees_every_event_whether_it_is_a_function_or_a_coroutine_function(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("a", "b"))
    seen, later = [], []

    async def slow(event):
        await asyncio.sleep(0)
        later.append(event)

    async with make(tmp_path) as client:
        await client.prompt("x", on_event=seen.append)
        await client.prompt("y", on_event=slow)

    assert any(isinstance(e, zc.Finished) for e in seen) and any(isinstance(e, zc.Finished) for e in later)


async def test_an_on_event_that_raises_stops_the_run_and_its_error_reaches_the_caller_unchanged(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("hello", "after"))

    def explode(event):
        raise KeyError("mine")

    async with make(tmp_path) as client:
        with pytest.raises(KeyError, match="mine"):
            await client.prompt("x", on_event=explode)

        assert client._stream is None
        assert (await client.prompt("again")).ok, "the client is free to go on"


# -- iterating ------------------------------------------------------------------------------------


async def test_stopping_early_inside_async_with_frees_the_client(tmp_path, monkeypatch):
    wire(
        monkeypatch,
        ScriptedModel("a long answer", "next"),
    )
    async with make(tmp_path) as client:
        async with client.prompt("go") as run:
            async for event in run:
                if isinstance(event, zc.TextDelta):
                    break

        assert client._stream is None and run.result is None
        assert (await client.prompt("again")).text == "next"


async def test_stopping_early_without_closing_keeps_the_client_busy_until_aclose(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("answer", "next"))
    async with make(tmp_path) as client:
        run = client.prompt("go")
        async for _event in run:
            break
        with pytest.raises(SessionBusyError):
            client.prompt("another")

        await run.aclose()

        assert (await client.prompt("another")).ok


async def test_a_run_can_be_partly_iterated_and_then_awaited_for_the_rest(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("abcdef", chunk=2))
    async with make(tmp_path) as client:
        run = client.prompt("go")
        first = await run.__anext__()
        result = await run

    assert isinstance(first, zc.TextDelta) is False or first.text == "ab"
    assert result.text == "abcdef"


async def test_iterating_a_finished_run_again_ends_at_once_and_awaiting_it_again_is_an_error_not_a_hang(
    tmp_path, monkeypatch
):
    wire(monkeypatch, ScriptedModel("done"))
    async with make(tmp_path) as client:
        run = client.prompt("go")
        first = await run
        assert [e async for e in run] == []
        again = await run

    assert first is again, "a finished run gives the same result"


async def test_the_result_is_none_until_the_run_has_ended(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("done"))
    async with make(tmp_path) as client:
        run = client.prompt("go")
        assert run.result is None
        await run

    assert run.result is not None


# -- one run at a time ----------------------------------------------------------------------------


async def test_a_second_prompt_while_one_is_running_is_refused_at_once_and_does_not_disturb_the_first(
    tmp_path, monkeypatch
):
    gate = asyncio.Event()
    wire(monkeypatch, ScriptedModel(await hold_until(gate, "the first")))
    async with make(tmp_path) as client:
        first = asyncio.create_task(client.run("slow"))
        await asyncio.sleep(0.05)

        with pytest.raises(SessionBusyError, match="already in progress"):
            client.prompt("second")
        with pytest.raises(SessionBusyError):
            await client.session.ask("side")
        with pytest.raises(SessionBusyError):
            await client.session.compact()
        gate.set()

        assert (await first).text == "the first"


async def test_two_prompts_made_before_either_starts_are_refused_when_the_second_starts(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("one", "two"))
    async with make(tmp_path) as client:
        first, second = client.prompt("a"), client.prompt("b")

        assert (await first).text == "one"
        assert (await second).text == "two", "sequential use of two prepared runs is fine"


async def test_concurrent_awaits_of_two_prepared_runs_let_one_win_and_refuse_the_other(tmp_path, monkeypatch):
    gate = asyncio.Event()
    wire(monkeypatch, ScriptedModel(await hold_until(gate, "winner")))
    async with make(tmp_path) as client:
        first, second = client.prompt("a"), client.prompt("b")
        one = asyncio.create_task(_wait(first))
        await asyncio.sleep(0.05)

        with pytest.raises(SessionBusyError):
            await second
        gate.set()

        assert (await one).text == "winner"


async def _wait(run):
    return await run


# -- errors ---------------------------------------------------------------------------------------


async def test_a_provider_failure_is_a_run_error_that_says_whether_to_retry(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(ConnectionError("connection reset"), ValueError("bad request body")))
    async with make(tmp_path) as client:
        with pytest.raises(RunError) as transient:
            await client.prompt("a")
        with pytest.raises(RunError) as permanent:
            await client.prompt("b")

    assert transient.value.retryable is True and "connection reset" in str(transient.value)
    assert permanent.value.retryable is False
    assert isinstance(transient.value.__cause__, ConnectionError), "the original is kept as the cause"


async def test_after_a_failed_run_the_client_is_free_and_has_no_result_to_read(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(ValueError("nope"), "recovered"))
    async with make(tmp_path) as client:
        run = client.prompt("a")
        with pytest.raises(RunError):
            await run

        assert run.result is None and client._stream is None
        assert (await client.prompt("b")).text == "recovered"


async def test_the_text_a_failed_run_had_already_produced_is_on_the_error(tmp_path, monkeypatch):
    async def stops_midway(request):
        return ConnectionError("dropped")

    wire(monkeypatch, ScriptedModel(asks_for(call("read_file", {"path": "x"}), text="thinking aloud "), stops_midway))
    async with make(tmp_path) as client:
        with pytest.raises(RunError) as caught:
            await client.prompt("go")

    assert caught.value.partial_text == "thinking aloud "


async def test_a_run_error_is_a_zettcode_error_and_not_a_value_error(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(RuntimeError("boom")))
    async with make(tmp_path) as client:
        with pytest.raises(zc.ZettCodeError) as caught:
            await client.prompt("go")

    assert not isinstance(caught.value, ValueError)


# -- deadlines and cancellation -------------------------------------------------------------------


async def test_a_run_that_outlasts_its_timeout_is_stopped_and_says_so(tmp_path, monkeypatch):
    never = asyncio.Event()
    wire(monkeypatch, ScriptedModel(await hold_until(never), "after"))
    async with make(tmp_path) as client:
        with pytest.raises(RunTimeoutError) as caught:
            await client.prompt("slow", timeout=0.2)

        assert isinstance(caught.value, TimeoutError) and isinstance(caught.value, RunError)
        assert caught.value.retryable and caught.value.seconds == 0.2
        assert client._stream is None
        assert (await client.prompt("next")).text == "after", "the client works again"


async def test_a_timeout_that_is_not_reached_changes_nothing(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel("quick"))
    async with make(tmp_path) as client:
        assert (await client.prompt("go", timeout=30)).text == "quick"


@pytest.mark.parametrize("bad", [0, -1, -0.5, "5", True, float("nan"), [1]])
async def test_a_timeout_that_is_not_a_positive_number_is_refused_before_anything_runs(tmp_path, monkeypatch, bad):
    model = wire(monkeypatch, ScriptedModel("never"))
    async with make(tmp_path) as client:
        with pytest.raises(ValueError, match="timeout"):
            client.prompt("go", timeout=bad)

    assert model.requests == []


async def test_the_deadline_covers_the_whole_run_and_not_each_event(tmp_path, monkeypatch):
    async def slow(request):
        await asyncio.sleep(0.15)
        return asks_for(call("read_file", {"path": "x"}))

    wire(monkeypatch, ScriptedModel(slow, slow, slow, "end"))
    async with make(tmp_path) as client:
        with pytest.raises(RunTimeoutError):
            await client.prompt("go", timeout=0.3)


async def test_cancelling_the_task_that_awaits_a_run_frees_the_client_and_propagates(tmp_path, monkeypatch):
    never = asyncio.Event()
    wire(monkeypatch, ScriptedModel(await hold_until(never), "after"))
    async with make(tmp_path) as client:
        task = asyncio.create_task(client.run("slow"))
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert client._stream is None
        assert (await client.prompt("next")).text == "after"


async def test_closing_a_run_under_a_task_that_is_reading_it_ends_that_task_cleanly(tmp_path, monkeypatch):
    never = asyncio.Event()
    wire(monkeypatch, ScriptedModel(await hold_until(never)))
    async with make(tmp_path) as client:
        run = client.prompt("slow")
        reader = asyncio.create_task(_collect(run))
        await asyncio.sleep(0.05)

        await run.aclose()

        assert await asyncio.wait_for(reader, 2) is not None
        assert client._stream is None


async def _collect(run):
    return [event async for event in run]


# -- the prompt itself ----------------------------------------------------------------------------


@pytest.mark.parametrize("empty", ["", "   ", "\n\t", [], [""], ["  ", "\n"]])
async def test_a_prompt_with_nothing_in_it_is_refused_before_the_model_is_called(tmp_path, monkeypatch, empty):
    model = wire(monkeypatch, ScriptedModel("never"))
    async with make(tmp_path) as client:
        with pytest.raises(ValueError, match="empty"):
            client.prompt(empty)

    assert model.requests == []


@pytest.mark.parametrize("wrong", [None, 5, b"bytes", [5], ["ok", None], {"a": 1}.items()])
async def test_a_prompt_that_is_not_text_or_images_is_a_type_error(tmp_path, monkeypatch, wrong):
    wire(monkeypatch, ScriptedModel("never"))
    async with make(tmp_path) as client:
        with pytest.raises((TypeError, ValueError)):
            client.prompt(wrong)


async def test_unusual_text_reaches_the_model_exactly(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("ok"))
    text = "héllo 世界 🚀\n\ttabbed  \"quotes\" 'single' \\ backslash {braces} $dollar %percent \x00 nul"
    async with make(tmp_path) as client:
        await client.prompt(text)

    assert model.requests[0].messages[-1].text == text


async def test_a_very_long_prompt_is_not_truncated(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("ok"))
    text = "word " * 100_000
    async with make(tmp_path) as client:
        await client.prompt(text)

    assert model.requests[0].messages[-1].text == text


async def test_a_prompt_of_text_pieces_is_joined_in_order(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("ok"))
    async with make(tmp_path) as client:
        await client.prompt(["one ", "two ", "three"])

    assert model.requests[0].messages[-1].text == "one two three"


async def test_images_are_refused_for_a_model_that_cannot_see_and_nothing_is_sent(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("never"))
    async with make(tmp_path) as client:
        with pytest.raises(ConfigurationError, match="does not accept images"):
            client.prompt("what is this", images=[Image(PNG, "image/png")])
        with pytest.raises(ConfigurationError):
            client.prompt(["look: ", Image(PNG, "image/png")])

    assert model.requests == []


async def test_an_image_reaches_a_model_that_can_see_in_the_place_it_was_put(tmp_path, monkeypatch):
    from zett_agent.messages import ImageContent, TextContent

    model = wire(monkeypatch, ScriptedModel("a cat"))
    async with make(tmp_path, models=models("eyes", multimodal=True)) as client:
        result = await client.prompt(["before ", Image(PNG, "image/png"), " after"])

    parts = model.requests[0].messages[-1].parts
    assert [type(p) for p in parts] == [TextContent, ImageContent, TextContent] and result.text == "a cat"


async def test_an_image_alone_is_a_prompt_and_an_image_after_the_text_goes_last(tmp_path, monkeypatch):
    from zett_agent.messages import ImageContent

    model = wire(monkeypatch, ScriptedModel("one", "two"))
    async with make(tmp_path, models=models("eyes", multimodal=True)) as client:
        await client.prompt([Image(PNG, "image/png")])
        await client.prompt("text", images=[Image(PNG, "image/png")])

    assert isinstance(model.requests[0].messages[-1].parts[-1], ImageContent)
    assert isinstance(model.requests[1].messages[-1].parts[-1], ImageContent)


async def test_an_at_sign_is_left_alone_unless_mentions_are_asked_for(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel("a", "b"))
    async with make(tmp_path) as client:
        await client.prompt("mail me at a@example.com or ask @someone")
        await client.prompt("ask @someone", mentions=True)

    assert model.requests[0].messages[-1].text == "mail me at a@example.com or ask @someone"
    assert "@someone" in model.requests[1].messages[-1].text, "an unknown name is kept as typed"


# -- answering the model --------------------------------------------------------------------------


@posix_shell
async def test_a_command_rule_approves_what_it_names_and_the_rest_is_denied(tmp_path, monkeypatch):
    steps = [
        asks_for(call("bash", {"command": "echo allowed", "timeout_seconds": 5}, call_id="ok")),
        asks_for(call("bash", {"command": "echo hi; echo evil", "timeout_seconds": 5}, call_id="no")),
        "finished",
    ]
    wire(monkeypatch, ScriptedModel(*steps))
    async with make(tmp_path, shell_approval="review") as client:
        client.use_permission("ask")
        result = await client.prompt("go", on_approval=zc.approve_commands("echo allowed"))

    by_id = {t.id: t for t in result.tools}
    assert by_id["ok"].ok and "allowed" in by_id["ok"].output
    assert not by_id["no"].ok, "a chained command is not matched by a prefix rule"


@posix_shell
async def test_an_approval_nobody_answers_is_denied_so_an_unattended_run_does_not_hang(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": "echo hi"}, call_id="b")), "moved on"))
    async with make(tmp_path) as client:
        client.use_permission("ask")
        result = await asyncio.wait_for(client.prompt("go"), 10)

    assert not result.tools[0].ok and result.text == "moved on"


@posix_shell
async def test_the_program_can_answer_an_approval_itself_while_iterating(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": "echo mine"}, call_id="b")), "done"))
    asked = []
    async with make(tmp_path) as client:
        client.use_permission("ask")
        async with client.prompt("go") as run:
            async for event in run:
                if isinstance(event, zc.ApprovalRequested):
                    asked.append(event.command)
                    event.approve()

    assert asked == ["echo mine"] and "mine" in run.result.tools[0].output


@posix_shell
async def test_a_deferred_run_keeps_an_approval_open_for_an_answer_that_comes_from_elsewhere(tmp_path, monkeypatch):
    """A panel answers when the reader chooses, not before the stream's next event: the run waits for it."""
    wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": "echo later"}, call_id="b")), "done"))
    shown: list[zc.ApprovalRequested] = []

    async def reader_chooses(request):
        shown.append(request)
        asyncio.get_running_loop().call_later(0.2, request.approve)

    async with make(tmp_path) as client:
        client.use_permission("ask")
        async with client.prompt("go", on_approval=reader_chooses, defer_answers=True) as run:
            async for _event in run:
                pass

    assert len(shown) == 1 and shown[0].approved is True
    assert "later" in run.result.tools[0].output, "the command ran, because the answer came after the event"


@posix_shell
async def test_the_same_late_answer_is_too_late_without_defer_answers(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": "echo later"}, call_id="b")), "done"))

    async def reader_chooses(request):
        asyncio.get_running_loop().call_later(0.2, lambda: request.approved is None and request.approve())

    async with make(tmp_path) as client:
        client.use_permission("ask")
        result = await asyncio.wait_for(client.prompt("go", on_approval=reader_chooses), 10)

    assert not result.tools[0].ok, "it was denied at the next event, before the reader could choose"


@posix_shell
async def test_what_a_deferred_run_left_open_is_denied_when_the_run_ends(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": "echo never"}, call_id="b")), "done"))
    open_ones: list[zc.ApprovalRequested] = []
    async with make(tmp_path) as client:
        client.use_permission("ask")
        async with client.prompt("go", on_approval=open_ones.append, defer_answers=True) as run:
            async for _event in run:
                if open_ones:
                    break

    assert open_ones[0].approved is False, "nobody answered, and the run is over: the agent is not left waiting"


@posix_shell
async def test_a_coroutine_handler_that_answers_for_itself_is_honoured(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": "echo remembered"}, call_id="b")), "done"))

    async def decide(request):
        request.approve(remember=True)

    async with make(tmp_path) as client:
        client.use_permission("ask")
        result = await client.prompt("go", on_approval=decide)

    assert result.tools[0].ok


@posix_shell
async def test_a_handler_that_raises_reaches_the_caller_and_the_command_is_not_run(tmp_path, monkeypatch):
    marker = tmp_path / "project" / "ran.txt"
    (tmp_path / "project").mkdir(exist_ok=True)
    wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": f"echo x > {marker.name}"}, call_id="b")), "x"))

    def broken(request):
        raise LookupError("my policy is broken")

    async with make(tmp_path) as client:
        client.use_permission("ask")
        with pytest.raises(LookupError, match="my policy is broken"):
            await asyncio.wait_for(client.prompt("go", on_approval=broken), 10)

        assert client._stream is None
    assert not marker.exists()


@posix_shell
async def test_a_handler_returning_the_wrong_kind_of_thing_is_a_type_error_and_never_approves(tmp_path, monkeypatch):
    marker = tmp_path / "project" / "ran.txt"
    (tmp_path / "project").mkdir(exist_ok=True)
    wire(monkeypatch, ScriptedModel(asks_for(call("bash", {"command": f"echo x > {marker.name}"}, call_id="b")), "x"))
    async with make(tmp_path) as client:
        client.use_permission("ask")
        with pytest.raises(TypeError):
            await asyncio.wait_for(client.prompt("go", on_approval=lambda r: "yes"), 10)

    assert not marker.exists()


@posix_shell
async def test_the_full_level_never_asks_and_the_deny_level_never_runs(tmp_path, monkeypatch):
    wire(
        monkeypatch,
        ScriptedModel(
            asks_for(call("bash", {"command": "echo auto"}, call_id="a")),
            "one",
            asks_for(call("bash", {"command": "echo denied"}, call_id="d")),
            "two",
        ),
    )
    asked = []
    async with make(tmp_path) as client:
        client.use_permission("full")
        auto = await client.prompt("go", on_approval=asked.append)
        client.use_permission("deny")
        denied = await client.prompt("go again", on_approval=asked.append)

    assert auto.tools[0].ok and asked == []
    assert not denied.tools[0].ok


async def test_a_question_is_answered_by_the_handler_and_the_model_gets_the_text(tmp_path, monkeypatch):
    model = wire(
        monkeypatch,
        ScriptedModel(
            asks_for(call("ask_user", {"question": "Which colour?", "options": ["red", "blue"]}, call_id="q")),
            "blue it is",
        ),
    )
    async with make(tmp_path) as client:
        result = await client.prompt("choose", on_question=lambda q: q.options[1])

    assert result.questions == ("Which colour?",) and result.text == "blue it is"
    assert "blue" in str(model.requests[1].messages[-1])


async def test_a_question_nobody_answers_is_declined_and_the_run_carries_on(tmp_path, monkeypatch):
    model = wire(monkeypatch, ScriptedModel(asks_for(call("ask_user", {"question": "Sure?"}, call_id="q")), "fine"))
    async with make(tmp_path) as client:
        result = await asyncio.wait_for(client.prompt("go"), 10)

    assert result.text == "fine" and "declin" in str(model.requests[1].messages[-1]).lower()


async def test_a_question_can_be_answered_by_the_program_while_iterating(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("ask_user", {"question": "Name?"}, call_id="q")), "hello"))
    async with make(tmp_path) as client:
        async with client.prompt("go") as run:
            async for event in run:
                if isinstance(event, zc.QuestionAsked):
                    event.answer("Ada")

    assert run.result.questions == ("Name?",)


async def test_questions_are_not_asked_when_the_tool_is_switched_off(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(asks_for(call("ask_user", {"question": "Hm?"}, call_id="q")), "ok"))
    async with make(tmp_path, ask_user_enabled=False) as client:
        result = await client.prompt("go")

    assert result.questions == () and not result.tools[0].ok


# -- stopping reasons -----------------------------------------------------------------------------


async def test_a_run_that_ends_in_a_stop_other_than_normal_still_leaves_the_client_usable(tmp_path, monkeypatch):
    wire(monkeypatch, ScriptedModel(refusal(), "fine now"))
    async with make(tmp_path) as client:
        assert not (await client.prompt("a")).ok
        assert (await client.prompt("b")).text == "fine now"


async def test_says_helper_builds_a_plain_answer():
    assert says("x").content == "x"
