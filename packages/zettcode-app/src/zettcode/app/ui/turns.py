"""What the shell hands the SDK to run a turn, and how it words a turn that failed.

The composer's draft is a list of parts (text, pictures, and ``@`` references as chips); the SDK takes text and
pictures and resolves the references itself, with the registry the composer completed them from. A failed run reaches
the shell as an SDK error whose message is already worded, so the only thing left to add is whether trying again may
help.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence

from zettcode.error_text import CONTINUE_HINT, failure_text
from zettcode.prompt import MentionPart, PromptPart
from zettcode.sdk.errors import RunError
from zettcode.sdk.events import AnyEvent, ToolFinished, ToolStarted
from zettcode.sdk.types import Image, TaskInfo, Usage

from ..plugins.state import TurnContext, TurnSegment

__all__ = ["TurnTally", "failure_line", "plan_rows", "prompt_pieces", "turn_parts"]


class TurnTally:
    """What one request spent, kept while it runs so the line it ends on can say.

    The tokens and model calls are the session's usage after the request less its usage before, so they are right
    for a request that failed or was stopped as well (the calls that finished are counted). The tool calls are counted
    from the events, because the session keeps no per-request tally of them. It holds numbers; the items of the
    line (``turn_parts``) say how they read.
    """

    def __init__(self, before: Usage) -> None:
        """Start counting from the session's usage as it is now."""
        self._before = before
        self.tools = 0
        self.failed = 0

    def see(self, event: AnyEvent) -> None:
        """Count a tool the model started, and one that failed (a question the reader cancelled is skipped, not failed)."""
        if isinstance(event, ToolStarted):
            self.tools += 1
        elif isinstance(event, ToolFinished) and not event.ok and not event.skipped:
            self.failed += 1

    def context(self, now: Usage, *, label: str, seconds: float, clock: str) -> TurnContext:
        """Return what the request came to, given the session's usage now, how it ended, how long it took and when."""
        return TurnContext(label, seconds, clock, now.since(self._before), self.tools, self.failed)


def turn_parts(segments: Sequence[TurnSegment], context: TurnContext, hidden: Collection[str]) -> tuple[str, ...]:
    """Return the items of the line a request ends on: each shown segment's text, in order.

    A segment the reader switched off is not asked. One that has nothing to say, or that raises, is left out: a
    plugin's mistake costs its own item and never the line.
    """
    parts: list[str] = []
    for segment in segments:
        if segment.name in hidden:
            continue
        try:
            text = segment.builder(context)
        except Exception:  # noqa: BLE001 - a plugin's item must not take the line down with it
            continue
        if text:
            parts.append(str(text))
    return tuple(parts)


def prompt_pieces(parts: Sequence[PromptPart]) -> list[str | Image]:
    """Return a draft's parts as the text and pictures the SDK takes, in the order they were written.

    A reference is its token again: the SDK splits the text at the tokens, as the composer did to make the chips.
    """
    pieces: list[str | Image] = []
    for part in parts:
        if isinstance(part, str):
            pieces.append(part)
        elif isinstance(part, MentionPart):
            pieces.append(part.token)
        else:
            data, media_type = part
            pieces.append(Image(data, media_type))
    return pieces


def failure_line(error: BaseException) -> str:
    """Return the line a failed turn is shown as: what failed, and ``/continue`` when trying again may work.

    An SDK run error already carries the sentence, and says whether the failure was the provider's or the network's;
    anything else is worded here, as it always was.
    """
    if isinstance(error, RunError):
        text = f"error: {error}"
        return f"{text.rstrip('.')}. {CONTINUE_HINT}" if error.retryable else text
    return failure_text(error)


def plan_rows(tasks: Sequence[TaskInfo]) -> tuple[tuple[str, str], ...]:
    """Return the model's plan as the (status, content) rows the task panel and the status line draw."""
    return tuple((task.status, task.content) for task in tasks)
