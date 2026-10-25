"""What the shell hands the SDK to run a turn, and how it words a turn that failed.

The composer's draft is a list of parts (text, pictures, and ``@`` references as chips); the SDK takes text and
pictures and resolves the references itself, with the registry the composer completed them from. A failed run reaches
the shell as an SDK error whose message is already worded, so the only thing left to add is whether trying again may
help.
"""

from __future__ import annotations

from collections.abc import Sequence

from zettcode.error_text import CONTINUE_HINT, failure_text
from zettcode.prompt import MentionPart, PromptPart
from zettcode.sdk.errors import RunError
from zettcode.sdk.types import Image, TaskInfo

__all__ = ["failure_line", "plan_rows", "prompt_pieces"]


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
