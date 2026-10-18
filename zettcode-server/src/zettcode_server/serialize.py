"""The SDK's values as the HTTP API's own: one place that decides what crosses the wire.

A conversion lives here rather than in the endpoints so the format is written down once: an SDK field that is not
meant for a client is left out here, a field the API documents is produced here, and the event stream and the final
result are shaped by the same rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .schemas import (
    CompactionOut,
    ContextOut,
    ContextShareOut,
    CurrentSessionOut,
    MessageOut,
    ModelOut,
    ResultOut,
    SessionOut,
    ToolOut,
    UsageOut,
)

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.sdk.events import AnyEvent
    from zettcode.sdk.session import Session
    from zettcode.sdk.types import (
        Compaction,
        ContextReport,
        Message,
        ModelInfo,
        RunResult,
        SessionInfo,
        ToolRecord,
        Usage,
    )


def usage_out(usage: Usage) -> UsageOut:
    """Return the token counts of a session or a run."""
    return UsageOut(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        seconds=usage.seconds,
        requests=usage.requests,
        context_tokens=usage.context_tokens,
    )


def model_out(model: ModelInfo) -> ModelOut:
    """Return one configured model, without its token or its address."""
    return ModelOut(
        name=model.name,
        model=model.model,
        context_window=model.context_window,
        multimodal=model.multimodal,
        efforts=list(model.efforts),
        active=model.active,
    )


def session_out(info: SessionInfo, current: str | None = None) -> SessionOut:
    """Return one stored session: when it changed, and whether it is the one a prompt would continue."""
    return SessionOut(
        id=info.id,
        title=info.title,
        created_at=info.created_at,
        updated_at=info.updated_at,
        current=info.id == current,
    )


def current_session_out(session: Session) -> CurrentSessionOut:
    """Return the conversation the next prompt continues."""
    return CurrentSessionOut(
        id=session.id,
        title=session.title,
        locked=session.locked,
        usage=usage_out(session.usage),
    )


def tool_out(tool: ToolRecord) -> ToolOut:
    """Return one tool call and how it ended."""
    return ToolOut(
        call_id=tool.id,
        name=tool.name,
        arguments=dict(tool.arguments),
        output=tool.output,
        ok=tool.ok,
        skipped=tool.skipped,
    )


def message_out(message: Message) -> MessageOut:
    """Return one message of a stored conversation."""
    return MessageOut(
        role=message.role,
        text=message.text,
        tool_calls=[
            ToolOut(call_id=call.id, name=call.name, arguments=dict(call.arguments), output="", ok=True)
            for call in message.tool_calls
        ],
        tool_call_id=message.tool_call_id,
        tool_name=message.tool_name,
        ok=message.ok,
        images=message.images,
    )


def compaction_out(compaction: Compaction | None) -> CompactionOut:
    """Return what a compaction did, or that it applied nothing."""
    if compaction is None:
        return CompactionOut(applied=False)
    return CompactionOut(
        applied=True,
        summary=compaction.summary,
        compressed=compaction.compressed,
        kept=compaction.kept,
    )


def context_out(report: ContextReport) -> ContextOut:
    """Return how full the context window is and what is filling it."""
    return ContextOut(
        window=report.window,
        used=report.used,
        measured_by=report.measured_by,
        shares=[ContextShareOut(name=share.name, tokens=share.tokens, items=share.items) for share in report.shares],
        partial=report.partial,
        from_provider=report.from_provider,
    )


def result_out(result: RunResult) -> ResultOut:
    """Return what a run came to, with its tool calls but not its raw event log."""
    return ResultOut(
        text=result.text,
        session_id=result.session_id,
        usage=usage_out(result.usage),
        tools=[tool_out(tool) for tool in result.tools],
        stop=result.stop,
        stop_message=result.stop_message,
        questions=list(result.questions),
    )


def event_payload(event: AnyEvent) -> dict[str, Any]:
    """Return one event of a run as the JSON an SSE frame carries.

    Every payload has a ``type``; the rest of the fields depend on it, and are documented with the stream. An event
    this server does not know is sent as ``{"type": "event", "name": ...}`` rather than dropped, so a newer SDK
    cannot make a stream look as if nothing happened.
    """
    from zettcode.sdk import events

    match event:
        case events.TextDelta(text=text):
            return {"type": "text_delta", "text": text}
        case events.ReasoningDelta(text=text):
            return {"type": "reasoning_delta", "text": text}
        case events.ToolStarted(call_id=call_id, name=name, arguments=arguments):
            return {"type": "tool_started", "call_id": call_id, "name": name, "arguments": dict(arguments)}
        case events.ToolFinished(call_id=call_id, name=name, output=output, ok=ok, skipped=skipped):
            return {
                "type": "tool_finished",
                "call_id": call_id,
                "name": name,
                "output": output,
                "ok": ok,
                "skipped": skipped,
            }
        case events.ApprovalRequested(call_id=call_id, command=command):
            return {"type": "approval_requested", "call_id": call_id, "command": command, "approved": event.approved}
        case events.QuestionAsked(call_id=call_id, question=question, options=options, allow_multiple=allow_multiple):
            return {
                "type": "question_asked",
                "call_id": call_id,
                "question": question,
                "options": list(options),
                "allow_multiple": allow_multiple,
                "answered": event.answered,
            }
        case events.UsageUpdated(usage=usage):
            return {"type": "usage_updated", "usage": usage_out(usage).model_dump()}
        case events.CompactionStarted():
            return {"type": "compaction_started"}
        case events.CompactionFinished(applied=applied, compaction=compaction):
            return {
                "type": "compaction_finished",
                "applied": applied,
                "summary": compaction.summary if compaction is not None else "",
            }
        case events.ModelStopped(reason=reason, message=message):
            return {"type": "model_stopped", "reason": reason, "message": message}
        case events.Steered(text=text):
            return {"type": "steered", "text": text}
        case events.Notice(text=text):
            return {"type": "notice", "text": text}
        case events.Finished(text=text):
            return {"type": "finished", "text": text}
        case events.RawEvent():
            return {"type": "raw"}
        case _:
            return {"type": "event", "name": type(event).__name__}
