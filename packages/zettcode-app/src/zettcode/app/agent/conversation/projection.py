"""Project agent events into transcript entries.

The agent's events are translated once, by :func:`zettcode.sdk.translation.translate`, into the SDK's typed events,
and this module draws those. A program that drives the agent through the SDK reads the same events, so what the
terminal shows and what the SDK reports cannot drift apart.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from zett_agent.dispatcher import AgentEventDispatcher
from zett_agent.events import AgentEvent

from zettcode.engine.dialogue.ask import declined_answer
from zettcode.relay import Relayed
from zettcode.sdk.events import (
    AnyEvent,
    ApprovalRequested,
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
)
from zettcode.sdk.translation import Bridge, translate
from zettcode.sdk.types import Usage

from .entries import EntryStatus
from .stops import stop_text
from .transcript import Transcript


class _NobodyAnswers:
    """The bridge of a projector that was given nobody to answer for: an answer sent through it goes nowhere."""

    def approve(self, session_id: str, call_id: str, approve: bool, remember: bool) -> None:
        raise RuntimeError("This projector has no agent to carry an approval to")

    def answer(self, question: object, text: str | None) -> None:
        raise RuntimeError("This projector has no agent to carry an answer to")


logger = logging.getLogger("zettcode.terminal")


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
        bridge: Bridge | None = None,
        on_approval: Callable[[ApprovalRequested], None] | None = None,
        on_ask: Callable[[QuestionAsked], None] | None = None,
        on_usage: Callable[[Usage, str], None] | None = None,
        on_steering_started: Callable[[str], Relayed | str | None] | None = None,
        on_steering_interrupted: Callable[[str], None] | None = None,
        side_running: Callable[[], bool] | None = None,
    ) -> None:
        """Send projected events to ``transcript``; approvals go to ``on_approval``.

        Args:
            transcript: Model that receives the projected entries.
            bridge: How an answer to an approval or a question reaches the suspended agent
                (:class:`zettcode.sdk.translation.AgentBridge` over the shell's agent).
            on_approval: Called synchronously for a shell approval request; the
                callback must not await, because the agent is suspended until the
                UI answers it later.
            on_ask: Called synchronously with each question the model asks; the
                callback must not await, for the same reason.
            on_usage: Called synchronously with each cumulative usage update and the session it is for, so
                the shell can refresh the status line without polling the store.
            on_steering_started: Called with the text of a queued steering
                message the agent just adopted, so the shell can drop it from
                the pending queue before the row is echoed. What it returns, when
                it is a :class:`~zettcode.relay.Relayed`, is drawn as that session's
                message — what its sender wrote, not the line the model reads; a
                string is drawn as the row's text.
            on_steering_interrupted: Called with the text of a steering message
                a newer one superseded, so the shell can drop it too.
            side_running: Asked whether the run in flight is a side question — a question the model answers without
                the exchange joining the conversation. Such a run is drawn only when the shell began it, so a
                plugin that asks one for itself (a recap) is not also drawn as an answer of its own. ``None``
                treats every run as one the shell began. Two plain flags are enough here because the SDK runs one
                request at a time: a second run is refused while one is in flight, so a plugin's ask cannot
                overlap a turn the shell began and a stale answer cannot be drawn as a turn's.
        """
        self.transcript = transcript
        self.bridge: Bridge = bridge if bridge is not None else _NobodyAnswers()
        self.on_approval = on_approval
        self.on_ask = on_ask
        self.on_usage = on_usage
        self.on_steering_started = on_steering_started
        self.on_steering_interrupted = on_steering_interrupted
        #: What a hosted tool's input has streamed so far, by call. The translation fills it as fragments arrive
        #: and reads the query out of it when the call reports back.
        self._hosted: dict[str, str] = {}
        #: Whether the shell began the run in flight, and so draws it.
        self._begun = False
        #: Whether a run nobody began has been reported as left out, so dropping one is a line and not one per
        #: token; it is cleared when a turn is begun, so it reports the next run that way too.
        self._reported_side = False
        self._side_running = side_running

    def begin_turn(self, prompt: str, *, side: bool = False, relayed: Relayed | None = None) -> None:
        """Begin drawing one run into the transcript, echoing the prompt that asked for it.

        The shell begins a turn before every run it shows on screen, which is also how a side question it asked
        is told apart from one a plugin asked for itself: see ``side_running``.

        Args:
            prompt: What the reader asked, echoed as the turn's first row.
            side: The question is a side one, which the transcript shows as such.
            relayed: The turn answers a message another session sent, which the transcript shows as that.
        """
        # The row first, the flag second: an echo that raises leaves no run to draw, and a flag set before it would
        # stay set, drawing every later side question as an answer of its own.
        if relayed is None:
            self.transcript.begin_turn(prompt, side=side)
        else:
            self.transcript.begin_turn(prompt, side=side, relayed=relayed)
        self._begun = True
        self._reported_side = False

    def end_turn(self) -> None:
        """Stop drawing, once the run the shell began has ended.

        Nothing of whatever runs next is drawn until a turn is begun for it, which is what keeps a plugin's own
        side question out of the transcript between turns.
        """
        self._begun = False

    async def dispatch(self, event: AgentEvent) -> None:
        """Note that the agent spoke, then draw what the event stands for.

        Every event ends a silence, whichever it is: the waiting row counts how long it has been since the model
        last said anything, and has to be told each time it does.

        A side question the shell did not begin is left out: its answer would land under the last turn's line as a
        reply nobody asked for, and whoever asked for it — a plugin's recap — draws the part it wants itself. The
        drop is logged, a line rather than one per token, so an answer that is missing from the transcript can be
        explained from the log.
        """
        self.transcript.heard()
        if not self._begun and self._side_running is not None and self._side_running():
            if not self._reported_side:
                self._reported_side = True
                logger.debug("projector.side_not_drawn", extra={"session": event.session_id})
            return
        for translated in translate(event, self.bridge, self._hosted):
            self.project(translated, event)

    def project(self, event: AnyEvent, source: AgentEvent | None = None) -> None:
        """Draw one SDK event.

        Args:
            event: The event, as the SDK reports it.
            source: The agent event it came from, for the few details the SDK's event leaves out.
        """
        transcript = self.transcript
        match event:
            case TextDelta(text=text):
                # Closes reasoning before the first answer token lands in the transcript.
                transcript.complete_thinking()
                transcript.append_answer(text)
            case ReasoningStarted():
                transcript.start_thinking()
            case ReasoningDelta(text=text):
                transcript.append_thinking(text)
            case ReasoningFinished():
                transcript.complete_thinking()
            case ToolStarted(call_id=call_id, name=name, arguments=arguments):
                logger.debug("tool.start", extra={"tool": name, "call": call_id})
                transcript.start_tool(call_id, name, arguments)
            case ToolFinished(call_id=call_id, name=name, output=output, ok=ok, skipped=skipped):
                logger.debug("tool.finish", extra={"tool": name, "call": call_id, "ok": ok, "skipped": skipped})
                self._tool_finished(call_id, name, output, ok, skipped)
            case ServerToolStarted(call_id=call_id, name=name, arguments=arguments):
                transcript.start_tool(call_id, name, arguments)
            case ServerToolFinished(call_id=call_id, arguments=arguments, output=output, ok=ok):
                if arguments:
                    # The row opened before its input had streamed in; now it knows what was searched for.
                    transcript.restate_tool(call_id, arguments)
                status = EntryStatus.COMPLETED if ok else EntryStatus.FAILED
                transcript.complete_tool(call_id, output or "Completed", status=status)
            case CompactionStarted():
                transcript.start_compaction()
            case CompactionDelta(text=text):
                transcript.append_compaction(text)
            case CompactionFinished(applied=applied):
                transcript.complete_compaction()
                transcript.notice(f"Context compaction {'applied' if applied else 'skipped'}")
            case ModelStopped():
                # The event follows the step's completion and is sent only for an abnormal ending, so the reply
                # above it is whatever the model managed to write, and this line is what stands between it and
                # being taken for an answer.
                transcript.complete_thinking()
                stop = source.stop if source is not None else None
                if stop is not None and not stop.ok:
                    transcript.error(stop_text(stop))
            case Steered(text=text):
                adopted = self.on_steering_started(text) if self.on_steering_started is not None else None
                if isinstance(adopted, Relayed):
                    transcript.begin_turn(adopted.text, relayed=adopted)
                else:
                    transcript.begin_turn(adopted or text)
            case SteeringFinished():
                transcript.complete_thinking()
            case SteeringInterrupted(text=text):
                if self.on_steering_interrupted is not None:
                    self.on_steering_interrupted(text)
                transcript.complete_thinking()
                transcript.notice("steering superseded by a newer message")
            case Finished():
                transcript.complete_thinking()
            case ApprovalRequested() if self.on_approval is not None:
                self.on_approval(event)
            case QuestionAsked() if self.on_ask is not None:
                self.on_ask(event)
            case UsageUpdated(session_id=session_id, usage=usage) if self.on_usage is not None:
                self.on_usage(usage, session_id)
            case Notice(text=text):
                # News about an MCP server or its configuration. It is a remark in the conversation,
                # not an error: the request goes on without whatever could not be reached.
                transcript.notice(text)
            case _:
                pass

    def _tool_finished(self, call_id: str, name: str, output: str, ok: bool, skipped: bool) -> None:
        """Attach a tool's ending to its row: skipped, failed, or done.

        A question the reader cancelled comes back as a result, not a failure: the model reads that it was declined
        and carries on. The row is marked skipped so it does not look like a question that was answered.
        """
        if skipped:
            self.transcript.complete_tool(call_id, output or "Skipped", status=EntryStatus.SKIPPED)
        elif not ok:
            self.transcript.complete_tool(call_id, output or "Tool failed", status=EntryStatus.FAILED)
        else:
            declined = name == "ask_user" and declined_answer(output)
            self.transcript.complete_tool(
                call_id, output or "Completed", status=EntryStatus.SKIPPED if declined else EntryStatus.COMPLETED
            )
