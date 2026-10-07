"""Project agent events into transcript entries."""

from __future__ import annotations

import json
from collections.abc import Callable

from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.events import AgentEvent
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_EVENT_NAME
from zett_agent.messages import ToolMessage

from .ask import AskUserQuestion, question_from
from .entries import EntryStatus
from .transcript import Transcript
from .usage import USAGE_EVENT_NAME


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


def steering_text(event: AgentEvent) -> str:
    """Return the text of a steering event, or an empty string when it has none."""
    message = event.steering_message
    return message.text if message is not None else ""


class TranscriptProjector(AgentEventDispatcher):
    """Turn AgentClient callbacks into transcript blocks.

    Every callback returns immediately. The approval callback in particular must
    not await the user: the agent is already suspended waiting for the response
    that the UI will emit later.
    """

    def __init__(
        self,
        transcript: Transcript,
        *,
        on_approval: Callable[[AgentEvent], None] | None = None,
        on_ask: Callable[[AskUserQuestion], None] | None = None,
        on_usage: Callable[[AgentEvent], None] | None = None,
        on_steering_started: Callable[[str], None] | None = None,
        on_steering_interrupted: Callable[[str], None] | None = None,
    ) -> None:
        """Send projected events to ``transcript``; approvals go to ``on_approval``.

        Args:
            transcript: Model that receives the projected entries.
            on_approval: Called synchronously for a shell approval request; the
                callback must not await, because the agent is suspended until the
                UI emits its response later.
            on_ask: Called synchronously with a parsed ``ask_user`` question; the
                callback must not await, for the same reason.
            on_usage: Called synchronously with each cumulative usage update, so
                the shell can refresh the status line without polling the store.
            on_steering_started: Called with the text of a queued steering
                message the agent just adopted, so the shell can drop it from
                the pending queue before the row is echoed.
            on_steering_interrupted: Called with the text of a steering message
                a newer one superseded, so the shell can drop it too.
        """
        self.transcript = transcript
        self.on_approval = on_approval
        self.on_ask = on_ask
        self.on_usage = on_usage
        self.on_steering_started = on_steering_started
        self.on_steering_interrupted = on_steering_interrupted

    def begin_turn(self, prompt: str, *, side: bool = False) -> None:
        """Echo the prompt into the transcript before the run starts.

        Args:
            prompt: What the reader asked.
            side: The question is a side one, which the transcript shows as such.
        """
        self.transcript.begin_turn(prompt, side=side)

    async def on_compaction_started_event(self, event: AgentEvent) -> None:
        """Open the compaction row; the summary streams into it as it arrives."""
        self.transcript.start_compaction()

    async def on_compaction_text_delta_event(self, event: AgentEvent) -> None:
        """Append one summary fragment to the row the started event opened."""
        self.transcript.append_compaction(event.delta or "")

    async def on_compaction_completed_event(self, event: AgentEvent) -> None:
        """Report whether the agent applied or skipped the compaction."""
        self.transcript.complete_compaction()
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

    async def on_steering_started_event(self, event: AgentEvent) -> None:
        """Echo an urgent user message the agent adopted as its new input."""
        text = steering_text(event)
        if self.on_steering_started is not None:
            self.on_steering_started(text)
        self.transcript.begin_turn(text)

    async def on_steering_completed_event(self, event: AgentEvent) -> None:
        """Close the row a steered turn left open when its answer arrived."""
        self.transcript.complete_thinking()

    async def on_steering_interrupted_event(self, event: AgentEvent) -> None:
        """Drop a steering message a newer one superseded, and say so."""
        text = steering_text(event)
        if self.on_steering_interrupted is not None:
            self.on_steering_interrupted(text)
        self.transcript.complete_thinking()
        self.transcript.notice("steering superseded by a newer message")

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
        """Route extension events: questions and approvals to the shell, usage to the rows."""
        if event.name == SHELL_APPROVAL_EVENT_NAME and self.on_approval is not None:
            self.on_approval(event)
        elif event.name == USAGE_EVENT_NAME and self.on_usage is not None:
            self.on_usage(event)
        elif self.on_ask is not None:
            question = question_from(event)
            if question is not None:
                self.on_ask(question)
