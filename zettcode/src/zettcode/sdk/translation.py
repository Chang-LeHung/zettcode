"""Turning ``zett-agent``'s events into the SDK's.

Kept apart from :mod:`zettcode.sdk.events` on purpose: the event classes are plain dataclasses a program imports to
match on, and importing them must not load the agent. This module reads ``AgentEvent`` and the application's own
custom events, so it imports both, and is itself imported only when a run starts.

It is also what a front end that drives the agent's own event stream (the terminal does) reads them through, so that
there is one translation: :func:`translate` for the events, :class:`AgentBridge` for the answers the events wait on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_EVENT_NAME
from zett_agent.messages import TextContent

from ..engine.dialogue.ask import question_from
from ..engine.extensions.mcp_notice import notice_from, notice_level_from
from ..engine.extensions.usage import USAGE_EVENT_NAME, UsageSnapshot
from ..engine.server_tools import ServerToolRun, describe_output
from ..engine.storage.ledger import Ledger, SessionStats, SessionUsage, Tally
from .events import (
    AnyEvent,
    ApprovalRequested,
    Bridge,
    CompactionDelta,
    CompactionFinished,
    CompactionStarted,
    Finished,
    ModelStopped,
    Notice,
    QuestionAsked,
    ReasoningDelta,
    ReasoningFinished,
    ReasoningStarted,
    ServerToolFinished,
    ServerToolStarted,
    Steered,
    SteeringFinished,
    SteeringInterrupted,
    TextDelta,
    ToolFinished,
    ToolStarted,
    UsageUpdated,
    _Reply,
)
from .types import (
    Compaction,
    DayTotals,
    ModelCheck,
    ModelTotals,
    SessionStatsInfo,
    SessionTotals,
    Totals,
    Usage,
    WorkspaceUsage,
)

__all__ = ["AgentBridge", "checks_from", "ledger_from", "stats_from", "translate", "usage_from"]


class AgentBridge:
    """Carry the program's answers to the suspended agent, through the application's own agent."""

    def __init__(self, agent: ZettCodeAgent) -> None:
        self._agent = agent

    def approve(self, session_id: str, call_id: str, approve: bool, remember: bool) -> None:
        self._agent.respond_approval(session_id, call_id, "execute" if approve else "abort", remember)

    def answer(self, question: AskUserQuestion, text: str | None) -> None:
        if text is None:
            self._agent.decline_ask(question)
        else:
            self._agent.answer_ask(question, text)


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


if TYPE_CHECKING:  # pragma: no cover - annotations only
    from ..doctor import Probe
    from ..engine.agent import ZettCodeAgent
    from ..engine.dialogue.ask import AskUserQuestion


def totals_from(tally: Tally) -> Totals:
    """Return one tally as the SDK's own counters."""
    return Totals(
        requests=tally.requests,
        input_tokens=tally.input_tokens,
        output_tokens=tally.output_tokens,
        cache_read_tokens=tally.cache_read_tokens,
        reasoning_tokens=tally.reasoning_tokens,
    )


def ledger_from(ledger: Ledger) -> WorkspaceUsage:
    """Return the workspace ledger as plain SDK values, ordered the way a page shows it."""
    sessions = sorted(ledger.sessions, key=lambda item: item.updated, reverse=True)
    models = sorted(ledger.models.items(), key=lambda pair: pair[1].total, reverse=True)
    return WorkspaceUsage(
        sessions=tuple(_session_totals(item) for item in sessions),
        models=tuple(ModelTotals(name, totals_from(tally)) for name, tally in models),
        days=tuple(DayTotals(day, totals_from(tally)) for day, tally in sorted(ledger.days.items())),
        total=totals_from(ledger.total),
    )


def _session_totals(usage: SessionUsage) -> SessionTotals:
    """Return one session's ledger row."""
    return SessionTotals(
        id=usage.session_id,
        title=usage.title,
        started=usage.started,
        updated=usage.updated,
        tokens=totals_from(usage.tally),
        models=usage.models,
        entries=usage.entries,
    )


def stats_from(stats: SessionStats) -> SessionStatsInfo:
    """Return one session's stored totals."""
    return SessionStatsInfo(
        id=stats.session_id,
        entries=stats.entries,
        requests=stats.requests,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        cache_read_tokens=stats.cache_read_tokens,
        reasoning_tokens=stats.reasoning_tokens,
    )


def checks_from(probes: Sequence[Probe]) -> tuple[ModelCheck, ...]:
    """Return the doctor probes as SDK values."""
    checks: list[ModelCheck] = []
    for probe in probes:
        tokens = probe.tokens
        checks.append(
            ModelCheck(
                model=probe.model.shown_name,
                model_id=probe.model.model,
                ok=probe.ok,
                seconds=probe.seconds,
                detail=probe.detail,
                input_tokens=tokens[0] if tokens else None,
                output_tokens=tokens[1] if tokens else None,
            )
        )
    return tuple(checks)


def translate(event: AgentEvent, bridge: Bridge, hosted: dict[str, str] | None = None) -> list[AnyEvent]:
    """Return the SDK events one ``zett-agent`` event stands for; usually one, sometimes none or several.

    Anything malformed is dropped rather than raised: this runs inside the stream of a live request, and a
    partly-formed custom event from an extension must not be able to fail it.

    Args:
        event: The event to translate.
        bridge: How an answer reaches the suspended agent.
        hosted: What a hosted tool's input has streamed so far, by call, for the caller that keeps it across the run.
            It is how a search that sends its query in fragments still shows the query; without it the start's own
            input is all there is.
    """
    session = event.session_id or ""
    kind = event.type
    if kind is AgentEventType.TEXT_DELTA:
        return [TextDelta(session, event.delta)] if event.delta else []
    if kind is AgentEventType.REASONING_DELTA:
        return [ReasoningDelta(session, event.delta)] if event.delta else []
    if kind is AgentEventType.REASONING_STARTED:
        return [ReasoningStarted(session)]
    if kind is AgentEventType.REASONING_COMPLETED:
        return [ReasoningFinished(session)]
    if kind is AgentEventType.TOOL_STARTED:
        return [ToolStarted(session, call.id, call.name, _arguments(call.arguments)) for call in event.tool_calls]
    if kind in (AgentEventType.TOOL_COMPLETED, AgentEventType.TOOL_FAILED, AgentEventType.TOOL_SKIPPED):
        return _tool_finished(event, session)
    if kind is AgentEventType.SERVER_TOOL_STARTED:
        return _server_tool_started(event, session, hosted)
    if kind is AgentEventType.SERVER_TOOL_INPUT_DELTA:
        delta = event.server_tool_input_delta
        if delta is not None and hosted is not None:
            hosted[delta.call_id] = hosted.get(delta.call_id, "") + delta.delta
        return []
    if kind in (AgentEventType.SERVER_TOOL_COMPLETED, AgentEventType.SERVER_TOOL_FAILED):
        return _server_tool_finished(event, session, hosted)
    if kind is AgentEventType.COMPACTION_STARTED:
        return [CompactionStarted(session)]
    if kind is AgentEventType.COMPACTION_TEXT_DELTA:
        return [CompactionDelta(session, event.delta)] if event.delta else []
    if kind is AgentEventType.COMPACTION_COMPLETED:
        return [_compaction_finished(event, session)]
    if kind is AgentEventType.MODEL_STOPPED:
        stop = event.stop
        reason = str(stop.reason.value) if stop is not None else "other"
        return [ModelStopped(session, reason, (stop.message or None) if stop is not None else None)]
    if kind is AgentEventType.STEERING_STARTED:
        text = _text_of(event.steering_message.content) if event.steering_message is not None else ""
        return [Steered(session, text)]
    if kind is AgentEventType.STEERING_COMPLETED:
        return [SteeringFinished(session)]
    if kind is AgentEventType.STEERING_INTERRUPTED:
        text = _text_of(event.steering_message.content) if event.steering_message is not None else ""
        return [SteeringInterrupted(session, text)]
    if kind is AgentEventType.RUN_COMPLETED:
        return [Finished(session, _text_of(getattr(event.message, "content", "")))]
    if kind is AgentEventType.CUSTOM:
        return _custom(event, session, bridge)
    return []


def _server_tool_started(event: AgentEvent, session: str, hosted: dict[str, str] | None) -> list[AnyEvent]:
    """Return the start of a hosted call: its name and whatever input the provider gave up front."""
    call = event.server_tool_call
    if call is None:
        return []
    if hosted is not None:
        hosted.setdefault(call.id, "")
    return [ServerToolStarted(session, call.id, call.name, dict(call.input or {}))]


def _server_tool_finished(event: AgentEvent, session: str, hosted: dict[str, str] | None) -> list[AnyEvent]:
    """Return the end of a hosted call: its query, gathered from the fragments, and a readable result."""
    import json

    result = event.server_tool_result
    if result is None:
        return []
    arguments: dict[str, object] = {}
    if hosted is not None:
        fragments = hosted.pop(result.call_id, "")
        if fragments:
            try:
                parsed = json.loads(fragments)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                arguments.update(parsed)
    ok = event.type is AgentEventType.SERVER_TOOL_COMPLETED
    run = ServerToolRun(result.call_id, result.name, arguments, output=result.output, error=result.error_code)
    return [ServerToolFinished(session, result.call_id, result.name, arguments, describe_output(run), ok)]


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
    return [Notice(session, line, notice_level_from(event))] if line is not None else []
