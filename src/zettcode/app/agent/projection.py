"""Project agent events into transcript entries."""

from __future__ import annotations

import json
from collections.abc import Callable

from zett_agent import (
    SHELL_APPROVAL_EVENT_NAME,
    AgentEvent,
    AgentEventDispatcher,
    ToolMessage,
)

from .entries import EntryStatus
from .transcript import Transcript


def tool_output(message: ToolMessage) -> str:
    """Return the printable text of a tool message, falling back for empty payloads."""
    if isinstance(message.content, str):
        return message.content or "Completed"
    return message.text or "Multimodal result"


def serialize(value: object) -> str:
    """Render a structured result as indented JSON, leaving plain text alone."""
    if value is None:
        return "Completed"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


class TranscriptProjector(AgentEventDispatcher):
    """Turn AgentClient callbacks into transcript blocks.

    Every callback returns immediately. The approval callback in particular must
    not await the user: the agent is already suspended waiting for the response
    that the UI will emit later.
    """

    def __init__(self, transcript: Transcript, *, on_approval: Callable[[AgentEvent], None] | None = None) -> None:
        """Send projected events to ``transcript``; approvals go to ``on_approval``.

        Args:
            transcript: Model that receives the projected entries.
            on_approval: Called synchronously for a shell approval request; the
                callback must not await, because the agent is suspended until the
                UI emits its response later.
        """
        self.transcript = transcript
        self.on_approval = on_approval

    def begin_turn(self, prompt: str) -> None:
        """Echo the prompt into the transcript before the run starts."""
        self.transcript.begin_turn(prompt)

    async def on_compaction_started_event(self, event: AgentEvent) -> None:
        """Announce compaction; the run keeps streaming underneath it."""
        self.transcript.notice("Compacting context\u2026")

    async def on_compaction_completed_event(self, event: AgentEvent) -> None:
        """Report whether the agent applied or skipped the compaction."""
        state = "applied" if event.applied else "skipped"
        self.transcript.notice(f"Context compaction {state}")

    async def on_reasoning_started_event(self, event: AgentEvent) -> None:
        """Open the thinking row for this reasoning span."""
        self.transcript.start_thinking()

    async def on_reasoning_delta_event(self, event: AgentEvent) -> None:
        """Append one reasoning delta to the running row."""
        self.transcript.append_thinking(event.delta)

    async def on_reasoning_completed_event(self, event: AgentEvent) -> None:
        """Close the thinking row and stamp its duration."""
        self.transcript.complete_thinking()

    async def on_text_delta_event(self, event: AgentEvent) -> None:
        """Close reasoning before the first answer token lands in the transcript."""
        self.transcript.complete_thinking()
        self.transcript.append_answer(event.delta)

    async def on_tool_started_event(self, event: AgentEvent) -> None:
        """Open one running row per tool call in the batch."""
        for call in event.tool_calls:
            self.transcript.start_tool(call.id, call.name, call.arguments)

    async def on_tool_completed_event(self, event: AgentEvent) -> None:
        """Attach the returned message to the row of the call it answers."""
        if isinstance(event.message, ToolMessage):
            self.transcript.complete_tool(event.message.tool_call_id, tool_output(event.message))

    async def on_tool_failed_event(self, event: AgentEvent) -> None:
        """Fail every call in the batch and record the error text."""
        for call in event.tool_calls:
            detail = str(event.error) if event.error is not None else "Tool failed"
            self.transcript.complete_tool(call.id, detail, status=EntryStatus.FAILED)

    async def on_tool_skipped_event(self, event: AgentEvent) -> None:
        """Mark the batch as skipped, keeping any message the tool still produced."""
        for call in event.tool_calls:
            output = tool_output(event.message) if isinstance(event.message, ToolMessage) else "Skipped"
            self.transcript.complete_tool(call.id, output, status=EntryStatus.SKIPPED)

    async def on_server_tool_started_event(self, event: AgentEvent) -> None:
        """Open a row for a tool the server runs on the agent's behalf."""
        if event.server_tool_call is not None:
            self.transcript.start_tool(event.server_tool_call.id, event.server_tool_call.name, {})

    async def on_server_tool_completed_event(self, event: AgentEvent) -> None:
        """Attach a server tool result to its row."""
        result = event.server_tool_result
        if result is not None:
            self.transcript.complete_tool(result.call_id, serialize(result.output))

    async def on_server_tool_failed_event(self, event: AgentEvent) -> None:
        """Attach a server tool failure, preferring the error code over the payload."""
        result = event.server_tool_result
        if result is not None:
            self.transcript.complete_tool(
                result.call_id,
                result.error_code or serialize(result.output),
                status=EntryStatus.FAILED,
            )

    async def on_run_completed_event(self, event: AgentEvent) -> None:
        """Close a reasoning row that the run never closed on its own."""
        self.transcript.complete_thinking()

    async def on_custom_event(self, event: AgentEvent) -> None:
        """Forward shell approval requests to the callback that renders the prompt."""
        if event.name == SHELL_APPROVAL_EVENT_NAME and self.on_approval is not None:
            self.on_approval(event)
