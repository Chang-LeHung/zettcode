"""Turning ``zett-agent``'s events into the SDK's.

Kept apart from :mod:`zettcode.sdk.events` on purpose: the event classes are plain dataclasses a program imports to
match on, and importing them must not load the agent. This module reads ``AgentEvent`` and the application's own
custom events, so it imports both, and is itself imported only when a run starts.
"""

from __future__ import annotations

from collections.abc import Mapping

from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_EVENT_NAME
from zett_agent.messages import TextContent

from ..app.agent.dialogue.ask import question_from
from ..app.agent.extensions.mcp_notice import notice_from
from ..app.agent.extensions.usage import USAGE_EVENT_NAME, UsageSnapshot
from .events import (
    AnyEvent,
    ApprovalRequested,
    Bridge,
    CompactionFinished,
    CompactionStarted,
    Finished,
    ModelStopped,
    Notice,
    QuestionAsked,
    ReasoningDelta,
    Steered,
    TextDelta,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
    _Reply,
)
from .types import Compaction, Usage

__all__ = ["translate", "usage_from"]


def usage_from(snapshot: UsageSnapshot) -> Usage:
    """Return the SDK's copy of the application's usage counters."""
    return Usage(
        input_tokens=snapshot.input_tokens,
        output_tokens=snapshot.output_tokens,
        cache_read_tokens=snapshot.cache_read_tokens,
        cache_write_tokens=snapshot.cache_write_tokens,
        reasoning_tokens=snapshot.reasoning_tokens,
        seconds=snapshot.seconds,
        requests=snapshot.requests,
        context_tokens=snapshot.context_tokens,
    )


def _text_of(content: object) -> str:
    """Return the plain text of a message body, which is a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "\n".join(part.text for part in content if isinstance(part, TextContent))
    return ""


def _arguments(value: object) -> dict[str, object]:
    """Return a tool call's arguments as a plain dict, whatever mapping they arrived in."""
    return dict(value) if isinstance(value, Mapping) else {}


def _payload(event: AgentEvent) -> dict[str, object]:
    """Return a custom event's payload, or an empty one when it is missing or not a mapping."""
    return dict(event.payload) if isinstance(event.payload, Mapping) else {}


def _optional_int(value: object) -> int | None:
    """Return ``value`` as an int when it is a real number, else ``None`` (a bool is not a number here)."""
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def translate(event: AgentEvent, bridge: Bridge) -> list[AnyEvent]:
    """Return the SDK events one ``zett-agent`` event stands for; usually one, sometimes none or several.

    Anything malformed is dropped rather than raised: this runs inside the stream of a live request, and a
    partly-formed custom event from an extension must not be able to fail it.
    """
    session = event.session_id or ""
    kind = event.type
    if kind is AgentEventType.TEXT_DELTA:
        return [TextDelta(session, event.delta)] if event.delta else []
    if kind is AgentEventType.REASONING_DELTA:
        return [ReasoningDelta(session, event.delta)] if event.delta else []
    if kind is AgentEventType.TOOL_STARTED:
        return [ToolStarted(session, call.id, call.name, _arguments(call.arguments)) for call in event.tool_calls]
    if kind in (AgentEventType.TOOL_COMPLETED, AgentEventType.TOOL_FAILED, AgentEventType.TOOL_SKIPPED):
        return _tool_finished(event, session)
    if kind is AgentEventType.COMPACTION_STARTED:
        return [CompactionStarted(session)]
    if kind is AgentEventType.COMPACTION_COMPLETED:
        return [_compaction_finished(event, session)]
    if kind is AgentEventType.MODEL_STOPPED:
        stop = event.stop
        reason = str(stop.reason.value) if stop is not None else "other"
        return [ModelStopped(session, reason, (stop.message or None) if stop is not None else None)]
    if kind is AgentEventType.STEERING_STARTED:
        text = _text_of(event.steering_message.content) if event.steering_message is not None else ""
        return [Steered(session, text)]
    if kind is AgentEventType.RUN_COMPLETED:
        return [Finished(session, _text_of(getattr(event.message, "content", "")))]
    if kind is AgentEventType.CUSTOM:
        return _custom(event, session, bridge)
    return []


def _tool_finished(event: AgentEvent, session: str) -> list[AnyEvent]:
    """Return the finished events of a tool event: one per call, with the message's text or the error's."""
    skipped = event.type is AgentEventType.TOOL_SKIPPED
    ok = event.type is AgentEventType.TOOL_COMPLETED
    message = event.message
    output = _text_of(getattr(message, "content", ""))
    if not output and event.error is not None:
        output = str(event.error)
    if ok and message is not None and getattr(message, "success", True) is False:
        ok = False
    return [ToolFinished(session, call.id, call.name, output, ok, skipped) for call in event.tool_calls]


def _compaction_finished(event: AgentEvent, session: str) -> CompactionFinished:
    """Return the compaction's end, carrying what it did when it replaced the context."""
    detail = event.compaction
    applied = bool(event.applied)
    if not applied or detail is None:
        return CompactionFinished(session, applied=applied)
    compressed = max(0, detail.compressed_to - detail.compressed_from + 1)
    kept = max(0, detail.kept_to - detail.kept_from + 1)
    return CompactionFinished(session, True, Compaction(detail.summary, compressed, kept))


def _custom(event: AgentEvent, session: str, bridge: Bridge) -> list[AnyEvent]:
    """Return the events an extension's custom event stands for."""
    name = event.name
    if name == SHELL_APPROVAL_EVENT_NAME:
        payload = _payload(event)
        call_id = payload.get("tool_call_id")
        if not isinstance(call_id, str) or not call_id:
            return []
        owner = str(payload.get("session_id") or session)
        command = payload.get("command")
        reply = _Reply(lambda outcome: bridge.approve(owner, call_id, outcome[0] == "execute", outcome[1]))  # type: ignore[index]
        return [
            ApprovalRequested(
                owner,
                call_id,
                command if isinstance(command, str) else "",
                _optional_int(payload.get("timeout_seconds")),
                payload.get("remember_supported") is True,
                reply,
            )
        ]
    if name == USAGE_EVENT_NAME:
        return [UsageUpdated(session, usage_from(UsageSnapshot.from_payload(_payload(event))))]
    question = question_from(event)
    if question is not None:

        def send(outcome: object) -> None:
            text = outcome[1]  # type: ignore[index]
            bridge.answer(question, text)

        return [
            QuestionAsked(
                question.session_id or session,
                question.call_id,
                question.question,
                question.options,
                question.allow_multiple,
                _Reply(send),
            )
        ]
    line = notice_from(event)
    return [Notice(session, line)] if line is not None else []
