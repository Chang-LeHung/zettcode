"""The parts of a user turn: text, ``@`` references, and the images placed among them.

The composer splits a draft into these, so the shell resolves a reference without
re-parsing the text, and the turn that reaches the model keeps each picture where its
writer put it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from ..dialogue.mentions import MentionRegistry


@dataclass(frozen=True, slots=True)
class MentionPart:
    """One ``@`` reference in a turn, kept as typed.

    The composer splits a draft at these tokens, so the shell resolves them
    without re-parsing the text and the editor can style them where they sit.
    """

    token: str
    #: The words the model reads in the token's place, when it is not to see the token itself. ``None``
    #: leaves the token as typed; the typed text is what the transcript and the store keep either way.
    says: str | None = None


#: One piece of a user turn, in the order it was written: a run of text, or the
#: encoded bytes and media type of an image placed where that run ends.
PromptPart: TypeAlias = str | MentionPart | tuple[bytes, str]


def plain_text_part(part: PromptPart) -> str:
    """Return the text one part contributes; an image contributes nothing."""
    if isinstance(part, str):
        return part
    if isinstance(part, MentionPart):
        return part.token
    return ""


def model_text_part(part: PromptPart) -> str:
    """Return the text one part is to the model: a reference that was resolved reads as what it says."""
    if isinstance(part, MentionPart) and part.says is not None:
        return part.says
    return plain_text_part(part)


def mention_parts(parts: Sequence[PromptPart], mentions: MentionRegistry) -> tuple[PromptPart, ...]:
    """Return a turn with each reference that has words of its own carrying them.

    ``@work`` typed for a session that is running is not a word the model knows, so it is put in the
    model's reading as ``session "work"`` and :func:`mention_hint` explains it. Anything else — a skill, a
    file, a name nobody has — keeps the token as it was typed.
    """
    if not mentions.providers:
        return tuple(parts)
    resolved: list[PromptPart] = []
    for part in parts:
        says = mentions.rename_token(part.token) if isinstance(part, MentionPart) else None
        resolved.append(MentionPart(part.token, says) if says is not None and isinstance(part, MentionPart) else part)
    return tuple(resolved)


def plain_text(parts: Sequence[PromptPart]) -> str:
    """Return a turn as the reader typed it, with its ``@`` tokens back in place."""
    return "".join(plain_text_part(part) for part in parts)


def carries_image(parts: Sequence[PromptPart]) -> bool:
    """Return whether one turn holds an image beside its text."""
    return any(not isinstance(part, (str, MentionPart)) for part in parts)


def mention_hint(parts: Sequence[PromptPart], mentions: MentionRegistry) -> str | None:
    """Return the instructions a turn's ``@`` references contribute, if any.

    ``None`` means nothing is appended: no provider is registered, the draft has
    no reference, or every token is unknown — the model then reads exactly what
    was typed. Each reference that resolves contributes one block, in the order
    the tokens appear.
    """
    if not mentions.providers:
        return None
    hints = [
        hint
        for part in parts
        if isinstance(part, MentionPart)
        if (hint := mentions.expand_token(part.token)) is not None
    ]
    return "\n\n".join(hints) if hints else None
