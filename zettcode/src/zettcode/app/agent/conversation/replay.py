"""Rebuild a transcript from a stored branch, the way ``/resume`` restores one.

The walk lives here, apart from the shell, so that how a stored turn, a tool result,
or the reasoning that came with an answer becomes a row is written down once and is
the same whoever asks.

The transcript keeps only its newest ``max_entries`` entries, so a long branch is
not replayed from its beginning: the walk starts where the entries that will be kept
begin, and the rest of the branch contributes only what is recorded beside its
messages — the usage of each reply — which needs no message decoded at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from zett_agent.messages import AnyMessage, AssistantMessage, SystemMessage, ToolMessage, UserMessage

from zettcode.config import DEFAULT_TRANSCRIPT_MAX_ENTRIES
from zettcode.engine.relay import relay_of

from ..dialogue.ask import declined_answer
from ..dialogue.side import is_side_line
from ..extensions.usage import UsageSnapshot
from ..storage import MessageLine, Session
from .entries import EntryStatus
from .presenters import DEFAULT_PRESENTERS, Presenters
from .rendering import DEFAULT_RENDERERS, Renderers
from .server_tools import ServerToolRun, answer_after_tools, describe_output, runs_in_blocks
from .stops import stop_text
from .transcript import Transcript

#: Entries of margin past the ones a window has to hold. Counting what a message will
#: add is an upper bound — consecutive replies with no row between them share one
#: answer, and a result whose call is before the window adds nothing — so the window
#: starts a little earlier than the count says it needs to.
WINDOW_SLACK = 64


@dataclass(frozen=True, slots=True)
class Replayed:
    """What one stored branch replays into.

    Attributes:
        transcript: The newest entries of the branch, ready to render or install.
        usage: Totals accumulated from the usage every stored reply recorded, the
            ones before the transcript's window included.
        lines: The whole active branch, oldest first.
    """

    transcript: Transcript
    usage: UsageSnapshot
    lines: Sequence[MessageLine]

    @property
    def history(self) -> tuple[AnyMessage, ...]:
        """Return the messages a request would carry, oldest first.

        Everything on the branch that is not an instruction or a side question. It is
        worked out when asked for, because it needs every message on the branch
        decoded, which restoring a session into the shell never wants.
        """
        return tuple(
            line.message[0]
            for line in self.lines
            if not is_side_line(line)
            and line.message[0].include_in_messages
            and not isinstance(line.message[0], SystemMessage)
        )


def entries_added_by(message: AnyMessage) -> int:
    """Return the most rows replaying one message adds to the transcript."""
    match message:
        case UserMessage():
            return 1
        case AssistantMessage():
            stopped = message.stop is not None and not message.stop.ok
            return (
                bool(message.reasoning)
                + bool(message.content)
                + len(message.tool_calls)
                + len(runs_in_blocks(message.replay_blocks))
                + stopped
            )
        case _:
            return 0


def window_start(lines: Sequence[MessageLine], entries: int) -> int:
    """Return the index of the line to start replaying from to end with ``entries`` rows.

    The branch is walked from its newest line, so the only messages looked inside are
    the ones the window will replay anyway; a short branch returns 0 and is replayed
    whole.

    Args:
        lines: The active branch, oldest first.
        entries: Rows the window has to hold.
    """
    wanted = entries + WINDOW_SLACK
    seen = 0
    for index in range(len(lines) - 1, -1, -1):
        seen += entries_added_by(lines[index].message[0])
        if seen >= wanted:
            return index
    return 0


def replay(
    session: Session,
    *,
    renderers: Renderers = DEFAULT_RENDERERS,
    presenters: Presenters = DEFAULT_PRESENTERS,
    frame: int = 0,
    max_entries: int = DEFAULT_TRANSCRIPT_MAX_ENTRIES,
) -> Replayed:
    """Rebuild a session's active branch into entries, totals, and messages.

    Args:
        session: The parsed session.
        renderers: Chain that phrases tool rows.
        presenters: How each kind of entry is drawn.
        frame: The animation step the rebuilt rows start at.
        max_entries: How many entries the transcript keeps. Only the lines that
            produce them are decoded and walked; the older ones add their usage to
            the totals and nothing else.
    """
    lines = session.branch()
    start = window_start(lines, max_entries)
    transcript = Transcript(renderers=renderers, presenters=presenters, max_entries=max_entries)
    transcript.frame = frame
    usage = UsageSnapshot()
    for line in lines[:start]:
        if line.usage is not None:
            usage = usage.with_usage(line.usage, line.timing.duration_ns / 1_000_000_000)
    for line in lines[start:]:
        # A side question is shown again — the reader saw it, so restoring the
        # session restores the transcript they were looking at — while staying
        # out of ``history``, which is what the next request would carry.
        side = is_side_line(line)
        if line.usage is not None:
            # Assistant lines are the ones that consumed a model response; their
            # duration is the generation time the rate divides by.
            usage = usage.with_usage(line.usage, line.timing.duration_ns / 1_000_000_000)
        message = line.message[0]
        match message:
            case UserMessage():
                # A message whose ``@`` references expanded carries the text the
                # reader typed as an attribute; the row restores that, while
                # ``history`` keeps the text the model was given.
                original = message.attributes.get("prompt")
                shown = original if isinstance(original, str) and original else message.text
                relayed = relay_of(message.attributes, shown)
                if relayed is not None and not side:
                    transcript.relayed_message(relayed)
                else:
                    transcript.user_message(shown, side=side)
            case AssistantMessage():
                if message.reasoning:
                    transcript.restore_thinking(message.reasoning, line.timing.reasoning_duration_ns)
                runs = runs_in_blocks(message.replay_blocks)

                def hosted(rows: Sequence[ServerToolRun] = runs) -> None:
                    """Add the rows of the tools the endpoint ran, each closed by its own result."""
                    for run in rows:
                        transcript.start_tool(run.call_id, run.name, run.arguments)
                        transcript.complete_tool(
                            run.call_id,
                            describe_output(run),
                            status=EntryStatus.FAILED if run.error else EntryStatus.COMPLETED,
                            wait=False,
                        )

                # A hosted tool has no message of its own: its call and result are both in the answer's blocks, kept
                # because the provider needs them back. Where the answer's text sits in those blocks is where the row
                # goes relative to it, so a reopened session reads in the order the run did.
                if not answer_after_tools(message.replay_blocks) and message.content:
                    transcript.append_answer(message.content)
                hosted()
                if answer_after_tools(message.replay_blocks) and message.content:
                    transcript.append_answer(message.content)
                for call in message.tool_calls:
                    transcript.start_tool(call.id, call.name, call.arguments)
                if message.stop is not None and not message.stop.ok:
                    transcript.error(stop_text(message.stop))
            case ToolMessage():
                status = EntryStatus.COMPLETED if message.success else EntryStatus.FAILED
                if message.name == "ask_user" and declined_answer(message.text):
                    # A cancelled question is an answer of its own, not a failure.
                    status = EntryStatus.SKIPPED
                transcript.complete_tool(message.tool_call_id, message.text, status=status, wait=False)
            case _:
                continue
    transcript.finish_restored_tools()
    return Replayed(transcript=transcript, usage=usage, lines=lines)
