"""Turning ``zett-agent`` events into SDK events, and answering the ones that wait on the program.

These run against hand-built events, so every shape an extension could send, including malformed ones, is exercised
without a model.
"""

from __future__ import annotations

import dataclasses

import pytest
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.ask_user import ASK_USER_EVENT_NAME
from zett_agent.extensions.events import CompactionEvent
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_EVENT_NAME, ShellApprovalRequestedEvent
from zett_agent.messages import AssistantMessage, TextContent, ToolCall, ToolMessage, UserMessage
from zett_agent.stop import StopInfo, StopReason

from zettcode.app.agent.extensions.mcp_notice import MCP_NOTICE_EVENT_NAME, notice_payload
from zettcode.app.agent.extensions.usage import USAGE_EVENT_NAME
from zettcode.sdk import events as sdk
from zettcode.sdk._translate import translate
from zettcode.sdk.types import Usage


class Bridge:
    """Record what the program answered."""

    def __init__(self) -> None:
        self.approvals: list[tuple[str, str, bool, bool]] = []
        self.answers: list[tuple[str, str | None]] = []

    def approve(self, session_id, call_id, approve, remember):
        self.approvals.append((session_id, call_id, approve, remember))

    def answer(self, question, text):
        self.answers.append((question.call_id, text))


def event(kind: AgentEventType, **fields) -> AgentEvent:
    return AgentEvent(kind, "s1", **fields)


def custom(name: str, payload) -> AgentEvent:
    return AgentEvent(AgentEventType.CUSTOM, "s1", name=name, payload=payload)


def one(source: AgentEvent, bridge: Bridge | None = None):
    (result,) = translate(source, bridge or Bridge())
    return result


# -- the plain ones -------------------------------------------------------------------------------


def test_a_text_delta_becomes_text():
    assert one(event(AgentEventType.TEXT_DELTA, delta="hi")) == sdk.TextDelta("s1", "hi")


def test_a_reasoning_delta_becomes_reasoning():
    assert one(event(AgentEventType.REASONING_DELTA, delta="hmm")) == sdk.ReasoningDelta("s1", "hmm")


@pytest.mark.parametrize("kind", [AgentEventType.TEXT_DELTA, AgentEventType.REASONING_DELTA])
def test_an_empty_delta_says_nothing(kind):
    assert translate(event(kind, delta=""), Bridge()) == []


@pytest.mark.parametrize(
    "kind",
    [
        AgentEventType.MODEL_STARTED,
        AgentEventType.CONTENT_STARTED,
        AgentEventType.CONTENT_COMPLETED,
        AgentEventType.REASONING_STARTED,
        AgentEventType.MODEL_COMPLETED,
        AgentEventType.TOOL_CALL_DELTA,
        AgentEventType.SERVER_TOOL_STARTED,
        AgentEventType.COMPACTION_TEXT_DELTA,
        AgentEventType.INTERNAL_MESSAGE_STARTED,
        AgentEventType.STEERING_COMPLETED,
    ],
)
def test_the_events_that_are_bookkeeping_are_not_surfaced(kind):
    assert translate(event(kind), Bridge()) == []


def test_a_tool_starting_carries_its_arguments_as_a_plain_dict():
    call = ToolCall(id="c1", name="read_file", arguments={"path": "a.py", "start_line": 3})

    started = one(event(AgentEventType.TOOL_STARTED, tool_calls=[call]))

    assert started == sdk.ToolStarted("s1", "c1", "read_file", {"path": "a.py", "start_line": 3})
    assert type(started.arguments) is dict


def test_one_tool_event_with_several_calls_is_one_event_per_call():
    calls = [ToolCall("a", "x", {}), ToolCall("b", "y", {})]

    result = translate(event(AgentEventType.TOOL_STARTED, tool_calls=calls), Bridge())

    assert [e.call_id for e in result] == ["a", "b"]


def test_a_tool_event_with_no_calls_says_nothing():
    assert translate(event(AgentEventType.TOOL_STARTED, tool_calls=[]), Bridge()) == []


def test_a_finished_tool_carries_its_output_and_outcome():
    call = ToolCall("c1", "bash", {"command": "ls"})
    message = ToolMessage(tool_call_id="c1", name="bash", content="a\nb\n", success=True)

    done = one(event(AgentEventType.TOOL_COMPLETED, tool_calls=[call], message=message))

    assert done == sdk.ToolFinished("s1", "c1", "bash", "a\nb\n", True, False)


def test_a_tool_that_completed_but_reported_failure_is_not_ok():
    call = ToolCall("c1", "bash", {})
    message = ToolMessage(tool_call_id="c1", name="bash", content="exit 3", success=False)

    done = one(event(AgentEventType.TOOL_COMPLETED, tool_calls=[call], message=message))

    assert done.ok is False and done.output == "exit 3"


def test_a_failed_tool_without_a_message_reports_the_error_text():
    call = ToolCall("c1", "bash", {})

    done = one(event(AgentEventType.TOOL_FAILED, tool_calls=[call], error=RuntimeError("boom")))

    assert (done.ok, done.output, done.skipped) == (False, "boom", False)


def test_a_skipped_tool_is_neither_ok_nor_run():
    call = ToolCall("c1", "bash", {})
    message = ToolMessage(tool_call_id="c1", name="bash", content="skipped", success=False)

    done = one(event(AgentEventType.TOOL_SKIPPED, tool_calls=[call], message=message))

    assert (done.ok, done.skipped) == (False, True)


def test_a_tool_result_made_of_blocks_reads_as_its_text():
    call = ToolCall("c1", "view", {})
    message = ToolMessage(tool_call_id="c1", name="view", content=[TextContent("one"), TextContent("two")])

    done = one(event(AgentEventType.TOOL_COMPLETED, tool_calls=[call], message=message))

    assert done.output == "one\ntwo"


def test_the_final_answer_is_the_text_of_the_last_message():
    done = one(event(AgentEventType.RUN_COMPLETED, message=AssistantMessage(content="All done.")))

    assert done == sdk.Finished("s1", "All done.")


def test_a_run_that_ends_without_a_message_finishes_with_empty_text():
    assert one(event(AgentEventType.RUN_COMPLETED)) == sdk.Finished("s1", "")


def test_a_stopped_model_step_names_why():
    stop = StopInfo(StopReason.REFUSAL, message="declined for safety")

    stopped = one(event(AgentEventType.MODEL_STOPPED, stop=stop))

    assert stopped == sdk.ModelStopped("s1", "refusal", "declined for safety")


def test_a_stop_with_no_sentence_has_no_message_and_one_with_no_info_is_other():
    assert one(event(AgentEventType.MODEL_STOPPED, stop=StopInfo(StopReason.MAX_OUTPUT))).message is None
    assert one(event(AgentEventType.MODEL_STOPPED)) == sdk.ModelStopped("s1", "other", None)


def test_steering_arriving_is_reported_with_what_was_said():
    message = UserMessage(content="actually, stop")

    assert one(event(AgentEventType.STEERING_STARTED, steering_message=message)) == sdk.Steered("s1", "actually, stop")
    assert one(event(AgentEventType.STEERING_STARTED)) == sdk.Steered("s1", "")


def test_a_compaction_starting_and_ending():
    assert one(event(AgentEventType.COMPACTION_STARTED)) == sdk.CompactionStarted("s1")

    detail = CompactionEvent(compressed_from=1, compressed_to=6, kept_from=7, kept_to=9, summary="the gist")
    done = one(event(AgentEventType.COMPACTION_COMPLETED, compaction=detail, applied=True))

    assert done.applied and done.compaction.summary == "the gist"
    assert (done.compaction.compressed, done.compaction.kept) == (6, 3)


def test_a_compaction_that_did_not_apply_carries_no_detail():
    detail = CompactionEvent(compressed_from=1, compressed_to=1, kept_from=2, kept_to=2, summary="x")

    assert one(event(AgentEventType.COMPACTION_COMPLETED, compaction=detail, applied=False)) == sdk.CompactionFinished(
        "s1", applied=False
    )
    assert one(event(AgentEventType.COMPACTION_COMPLETED, applied=True)).compaction is None


# -- the approval request -------------------------------------------------------------------------


def approval(bridge: Bridge, **payload) -> sdk.ApprovalRequested:
    body = {
        "session_id": "s1",
        "tool_call_id": "call-9",
        "command": "git status",
        "timeout_seconds": 30,
        "remember_supported": True,
    }
    body.update(payload)
    return one(custom(SHELL_APPROVAL_EVENT_NAME, body), bridge)


def test_the_real_approval_event_becomes_a_request():
    bridge = Bridge()
    real = ShellApprovalRequestedEvent(
        "s1", ToolCall("call-1", "bash", {}), command="rm -r build", timeout_seconds=60, remember_supported=True
    )

    request = one(real, bridge)

    assert (request.call_id, request.command, request.timeout_seconds, request.remember_supported) == (
        "call-1",
        "rm -r build",
        60,
        True,
    )
    assert request.answered is False and request.approved is None


def test_approving_sends_execute_once_to_the_session_that_asked():
    bridge = Bridge()
    request = approval(bridge)

    request.approve()

    assert bridge.approvals == [("s1", "call-9", True, False)]
    assert request.answered and request.approved is True


def test_denying_sends_abort():
    bridge = Bridge()
    request = approval(bridge)

    request.deny()

    assert bridge.approvals == [("s1", "call-9", False, False)]
    assert request.approved is False


def test_remembering_is_passed_on_only_when_the_tool_supports_it():
    bridge = Bridge()
    approval(bridge).approve(remember=True)
    approval(bridge, remember_supported=False).approve(remember=True)

    assert [a[3] for a in bridge.approvals] == [True, False]


def test_answering_the_same_way_twice_sends_one_answer():
    bridge = Bridge()
    request = approval(bridge)

    request.approve()
    request.approve()

    assert len(bridge.approvals) == 1


def test_answering_the_opposite_way_after_an_answer_is_an_error_and_sends_nothing_more():
    """The agent has already acted on the first answer; a second, different one cannot be honoured."""
    bridge = Bridge()
    request = approval(bridge)
    request.approve()

    with pytest.raises(ValueError, match="Already answered"):
        request.deny()
    assert len(bridge.approvals) == 1 and request.approved is True


def test_a_request_built_by_hand_has_nothing_to_answer():
    request = sdk.ApprovalRequested("s", "c", "ls")

    with pytest.raises(RuntimeError, match="not created by a run"):
        request.approve()
    assert request.answered is False


def test_an_approval_payload_without_a_call_id_is_dropped_because_it_could_not_be_answered():
    for payload in ({"command": "ls"}, {"tool_call_id": "", "command": "ls"}, {"tool_call_id": 5}, "junk", None, []):
        assert translate(custom(SHELL_APPROVAL_EVENT_NAME, payload), Bridge()) == []


def test_odd_fields_in_an_approval_payload_fall_back_rather_than_fail():
    bridge = Bridge()
    request = approval(bridge, command=42, timeout_seconds="soon", remember_supported="yes", session_id=None)

    assert request.command == "" and request.timeout_seconds is None
    assert request.remember_supported is False
    assert request.session_id == "s1", "the event's own session stands in for a missing one"


def test_a_boolean_is_not_a_timeout():
    assert approval(Bridge(), timeout_seconds=True).timeout_seconds is None
    assert approval(Bridge(), timeout_seconds=12.9).timeout_seconds == 12


# -- the question ---------------------------------------------------------------------------------


def question(bridge: Bridge, **payload) -> sdk.QuestionAsked:
    body = {"session_id": "s1", "tool_call_id": "q1", "question": " Which one? ", "options": ["a", "b"]}
    body.update(payload)
    return one(custom(ASK_USER_EVENT_NAME, body), bridge)


def test_a_question_carries_its_choices():
    asked = question(Bridge(), allow_multiple=True)

    assert (asked.call_id, asked.question, asked.options, asked.allow_multiple) == (
        "q1",
        "Which one?",
        ("a", "b"),
        True,
    )


def test_answering_a_question_sends_the_text_as_given():
    bridge = Bridge()
    asked = question(bridge)

    asked.answer("  b, with spaces ")

    assert bridge.answers == [("q1", "  b, with spaces ")]
    assert asked.answered


def test_declining_a_question_sends_a_decline():
    bridge = Bridge()
    question(bridge).decline()

    assert bridge.answers == [("q1", None)]


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_a_blank_answer_is_refused_and_declining_is_the_way_to_say_no(text):
    bridge = Bridge()
    asked = question(bridge)

    with pytest.raises(ValueError, match="cannot be empty"):
        asked.answer(text)
    assert bridge.answers == [] and not asked.answered


def test_a_non_text_answer_is_refused():
    with pytest.raises(ValueError):
        question(Bridge()).answer(5)  # type: ignore[arg-type]


def test_a_question_answered_then_declined_is_a_conflict():
    asked = question(Bridge())
    asked.answer("a")

    with pytest.raises(ValueError, match="Already answered"):
        asked.decline()


def test_malformed_questions_are_dropped():
    for payload in (
        {"tool_call_id": "q", "question": ""},
        {"tool_call_id": "q"},
        {"tool_call_id": "", "question": "?"},
        {"question": "?"},
        {"tool_call_id": "q", "question": 5},
        "junk",
        None,
    ):
        assert translate(custom(ASK_USER_EVENT_NAME, payload), Bridge()) == []


def test_junk_in_the_options_is_ignored():
    asked = question(Bridge(), options=["ok", 5, "", "  ", None, "fine"])

    assert asked.options == ("ok", "fine")
    assert question(Bridge(), options="a,b").options == ()


# -- usage, notices, and everything else ----------------------------------------------------------


def test_a_usage_event_becomes_the_sessions_totals():
    payload = {"input_tokens": 120, "output_tokens": 30, "cache_read_tokens": 80, "requests": 2, "seconds": 1.5}

    updated = one(custom(USAGE_EVENT_NAME, payload))

    assert (
        updated.usage.total_tokens == 150 and updated.usage.requests == 2 and updated.usage.cache_hit_rate == 80 / 120
    )


def test_a_usage_event_with_junk_reads_as_zeros_rather_than_failing():
    assert one(custom(USAGE_EVENT_NAME, {"input_tokens": "lots", "seconds": None})).usage == Usage()
    assert one(custom(USAGE_EVENT_NAME, "junk")).usage == Usage()


def test_an_mcp_notice_is_a_notice():
    assert one(custom(MCP_NOTICE_EVENT_NAME, {"text": "  server docs is down  "})) == sdk.Notice(
        "s1", "server docs is down"
    )


def test_a_notice_says_how_serious_it_is_and_one_that_does_not_is_progress():
    warning = one(custom(MCP_NOTICE_EVENT_NAME, notice_payload("server docs is down", "warn")))
    progress = one(custom(MCP_NOTICE_EVENT_NAME, notice_payload("Starting MCP server 'docs' (process)…")))
    assert (warning.text, warning.level) == ("server docs is down", "warn")
    assert progress.level == "info"
    # An older payload with no level, and a level nobody defined, are both progress rather than an alarm.
    assert one(custom(MCP_NOTICE_EVENT_NAME, {"text": "x"})).level == "info"
    assert one(custom(MCP_NOTICE_EVENT_NAME, {"text": "x", "level": "catastrophe"})).level == "info"
    assert notice_payload("x", "catastrophe") == {"text": "x", "level": "info"}


def test_a_blank_or_malformed_notice_is_dropped():
    for payload in ({"text": ""}, {"text": "   "}, {"text": 5}, {}, "junk", None):
        assert translate(custom(MCP_NOTICE_EVENT_NAME, payload), Bridge()) == []


def test_a_custom_event_nobody_here_knows_is_dropped():
    assert translate(custom("something_else", {"a": 1}), Bridge()) == []


def test_an_event_without_a_session_id_is_given_an_empty_one_and_still_works():
    plain = AgentEvent(AgentEventType.TEXT_DELTA, "", delta="x")

    assert one(plain) == sdk.TextDelta("", "x")


def test_events_are_immutable_and_comparable_by_content():
    delta = sdk.TextDelta("s", "x")

    with pytest.raises(dataclasses.FrozenInstanceError):
        delta.text = "y"  # type: ignore[misc]
    assert delta == sdk.TextDelta("s", "x") and delta != sdk.TextDelta("s", "z")


def test_a_pattern_match_on_the_event_classes_reads_the_fields():
    seen = []
    for item in (sdk.TextDelta("s", "a"), sdk.ToolStarted("s", "1", "bash", {}), sdk.Finished("s", "z")):
        match item:
            case sdk.TextDelta(text=text):
                seen.append(text)
            case sdk.ToolStarted(name=name):
                seen.append(name)
            case sdk.Finished(text=text):
                seen.append(text)

    assert seen == ["a", "bash", "z"]
