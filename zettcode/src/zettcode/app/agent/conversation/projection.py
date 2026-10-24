"""Project agent events into transcript entries."""

from __future__ import annotations

import json
from collections.abc import Callable

from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.events import AgentEvent
from zett_agent.extensions.shell_approval import SHELL_APPROVAL_EVENT_NAME
from zett_agent.messages import ToolMessage

from zettcode.engine.dialogue.ask import AskUserQuestion, declined_answer, question_from
from zettcode.engine.extensions.mcp_notice import MCP_NOTICE_EVENT_NAME, notice_from
from zettcode.engine.extensions.usage import USAGE_EVENT_NAME
from zettcode.engine.relay import Relayed

from .entries import EntryStatus
from .server_tools import ServerToolRun, describe_output
from .stops import stop_text
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
        #: What a hosted tool was called with while it streams: a start may carry the whole input, or only its
        #: opening and then fragments. Kept per request and dropped when the call reports back.
        self._server_inputs: dict[str, dict[str, object]] = {}
        self._server_fragments: dict[str, str] = {}

    def begin_turn(self, prompt: str, *, side: bool = False, relayed: Relayed | None = None) -> None:
        """Echo the prompt into the transcript before the run starts.

        Args:
            prompt: What the reader asked.
            side: The question is a side one, which the transcript shows as such.
            relayed: The turn answers a message another session sent, which the transcript shows as that.
        """
        if relayed is None:
            self.transcript.begin_turn(prompt, side=side)
        else:
            self.transcript.begin_turn(prompt, side=side, relayed=relayed)

    async def dispatch(self, event: AgentEvent) -> None:
        """Note that the agent spoke, then hand the event to the callback that draws it.

        Every event ends a silence, whichever it is: the waiting row counts how long it has been since the model
        last said anything, and has to be told each time it does.
        """
        self.transcript.heard()
        await super().dispatch(event)

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

    async def on_model_stopped_event(self, event: AgentEvent) -> None:
        """Say that a model step ended without finishing: refused, cut off, interrupted or paused for good.

        The event follows the step's completion and is sent only for an abnormal ending, so the reply above it is
        whatever the model managed to write, and this line is what stands between it and being taken for an answer.
        """
        self.transcript.complete_thinking()
        if event.stop is not None and not event.stop.ok:
            self.transcript.error(stop_text(event.stop))

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
        """Attach the returned message to the row of the call it answers.

        A question the reader cancelled comes back as a result, not a failure: the model reads that it was declined
        and carries on. The row is marked skipped so it does not look like a question that was answered.
        """
        if isinstance(event.message, ToolMessage):
            output = tool_output(event.message)
            declined = event.message.name == "ask_user" and declined_answer(output)
            self.transcript.complete_tool(
                event.message.tool_call_id,
                output,
                status=EntryStatus.SKIPPED if declined else EntryStatus.COMPLETED,
            )

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
        """Open a row for a tool the server runs on the agent's behalf, with what it was asked."""
        call = event.server_tool_call
        if call is None:
            return
        arguments = dict(call.input or {})
        self._server_inputs[call.id] = arguments
        self._server_fragments.pop(call.id, None)
        self.transcript.start_tool(call.id, call.name, arguments)

    async def on_server_tool_input_delta_event(self, event: AgentEvent) -> None:
        """Keep the fragments of a hosted call's input; the query a search ran is in there."""
        delta = event.server_tool_input_delta
        if delta is not None:
            self._server_fragments[delta.call_id] = self._server_fragments.get(delta.call_id, "") + delta.delta

    def _server_arguments(self, call_id: str) -> dict[str, object]:
        """Return what a hosted call turned out to be called with: its opening input and its fragments."""
        arguments = dict(self._server_inputs.pop(call_id, {}))
        fragments = self._server_fragments.pop(call_id, "")
        if fragments:
            try:
                parsed = json.loads(fragments)
            except ValueError:
                parsed = None
            if isinstance(parsed, dict):
                arguments.update(parsed)
        return arguments

    async def on_server_tool_completed_event(self, event: AgentEvent) -> None:
        """Attach a hosted tool's result to its row: the pages it found, never the provider's payload."""
        result = event.server_tool_result
        if result is not None:
            arguments = self._server_arguments(result.call_id)
            if arguments:
                # The row opened before its input had streamed in; now it knows what was searched for.
                self.transcript.restate_tool(result.call_id, arguments)
            run = ServerToolRun(result.call_id, result.name, arguments, output=result.output, error=result.error_code)
            self.transcript.complete_tool(result.call_id, describe_output(run) or serialize(result.output))

    async def on_server_tool_failed_event(self, event: AgentEvent) -> None:
        """Attach a hosted tool's failure, preferring the error code over the payload."""
        result = event.server_tool_result
        if result is not None:
            arguments = self._server_arguments(result.call_id)
            if arguments:
                self.transcript.restate_tool(result.call_id, arguments)
            run = ServerToolRun(result.call_id, result.name, arguments, output=result.output, error=result.error_code)
            self.transcript.complete_tool(
                result.call_id,
                describe_output(run) or serialize(result.output),
                status=EntryStatus.FAILED,
            )

    async def on_run_completed_event(self, event: AgentEvent) -> None:
        """Close a reasoning row that the run never closed on its own."""
        self.transcript.complete_thinking()

    async def on_custom_event(self, event: AgentEvent) -> None:
        """Route extension events: questions and approvals to the shell, usage and MCP news to the rows."""
        if event.name == SHELL_APPROVAL_EVENT_NAME and self.on_approval is not None:
            self.on_approval(event)
        elif event.name == USAGE_EVENT_NAME and self.on_usage is not None:
            self.on_usage(event)
        elif event.name == MCP_NOTICE_EVENT_NAME:
            # News about an MCP server or its configuration. It is a remark in the conversation,
            # not an error: the request goes on without whatever could not be reached.
            line = notice_from(event)
            if line is not None:
                self.transcript.notice(line)
        elif self.on_ask is not None:
            question = question_from(event)
            if question is not None:
                self.on_ask(question)
