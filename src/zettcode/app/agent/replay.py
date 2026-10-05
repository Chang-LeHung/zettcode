"""Rebuild a transcript from a stored branch, the way ``/resume`` restores one.

One walk over the branch serves both readers: the shell installs the entries it
produces, and the exporter renders them into a file. Keeping the walk here means
the two cannot drift apart in how they read a stored turn, a tool result, or the
reasoning that came with an answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from zett_agent.messages import AnyMessage, AssistantMessage, SystemMessage, ToolMessage, UserMessage

from .blocks import DEFAULT_PROCESSORS, EntryProcessors
from .entries import EntryStatus
from .rendering import DEFAULT_RENDERERS, Renderers
from .storage import Session
from .transcript import Transcript
from .usage import UsageSnapshot


@dataclass(frozen=True, slots=True)
class Replayed:
    """What one stored branch replays into.

    Attributes:
        transcript: Entries in file order, ready to render or install.
        usage: Totals accumulated from the usage each stored reply recorded.
        history: The messages a request would carry, oldest first: everything on
            the branch that is not an instruction.
    """

    transcript: Transcript
    usage: UsageSnapshot
    history: tuple[AnyMessage, ...]


def replay(
    session: Session,
    *,
    renderers: Renderers = DEFAULT_RENDERERS,
    processors: EntryProcessors = DEFAULT_PROCESSORS,
    frame: int = 0,
) -> Replayed:
    """Rebuild a session's active branch into entries, totals, and messages."""
    transcript = Transcript(renderers=renderers, processors=processors)
    transcript.frame = frame
    usage = UsageSnapshot()
    history: list[AnyMessage] = []
    for line in session.branch():
        if line.usage is not None:
            # Assistant lines are the ones that consumed a model response; their
            # duration is the generation time the rate divides by.
            usage = usage.with_usage(line.usage, line.timing.duration_ns / 1_000_000_000)
        message = line.message[0]
        if message.include_in_messages and not isinstance(message, SystemMessage):
            history.append(message)
        match message:
            case UserMessage():
                transcript.user_message(message.text)
            case AssistantMessage():
                if message.reasoning:
                    transcript.restore_thinking(message.reasoning, line.timing.reasoning_duration_ns)
                if message.content:
                    transcript.append_answer(message.content)
                for call in message.tool_calls:
                    transcript.start_tool(call.id, call.name, call.arguments)
            case ToolMessage():
                status = EntryStatus.COMPLETED if message.success else EntryStatus.FAILED
                transcript.complete_tool(message.tool_call_id, message.text, status=status, wait=False)
            case _:
                continue
    transcript.finish_restored_tools()
    return Replayed(transcript=transcript, usage=usage, history=tuple(history))
