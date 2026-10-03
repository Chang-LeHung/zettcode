"""Session titles: one small model call that names the first exchange.

A title is a nicety, not conversation data: it never enters the message history
and it is produced by a single provider request instead of another agent turn,
so no tools, hooks, or extra session records are involved.
"""

from __future__ import annotations

import re

from zett_agent import AgentModel, ModelEventType, ModelRequest, ReasoningEffort, SystemMessage, UserMessage

#: Most characters a stored title may use, matching the store's own guard.
MAX_TITLE_CHARS = 60
#: Most characters of each side of the exchange sent to the model.
MAX_EXCERPT_CHARS = 1200

INSTRUCTIONS = (
    "You name conversations. Reply with a single short title of at most six words for the "
    "exchange below, in the language the user wrote in. Reply with the title only: no quotes, "
    "no markdown, no trailing period."
)

#: Decoration a model wraps a title in: bullets, headings, or a list number.
_LEADING_MARKER = re.compile(r"^(?:[-*\u2022\u25aa>#]+\s*|\d+[.)]\s+)+")
#: Trailing punctuation that only marks the end of a sentence.
_TRAILING = ".:;,\u3002"


async def summarize_title(model: AgentModel, *, question: str, answer: str) -> str | None:
    """Return a short title for the first exchange, or ``None`` when there is none.

    Args:
        model: Model to ask; the request carries no tools, so the provider's own
            retry policy applies and no agent turn or session record is created.
        question: The user's first message.
        answer: The assistant's reply to it.
    """
    request = ModelRequest(
        messages=[
            SystemMessage(content=INSTRUCTIONS),
            UserMessage(content=f"User: {excerpt(question)}\n\nAssistant: {excerpt(answer)}"),
        ],
        reasoning_effort=ReasoningEffort.LOW,
    )
    reply = ""
    async for event in model.stream(request):
        if event.type is ModelEventType.TEXT_DELTA:
            reply += event.delta
    return clean_title(reply)


def excerpt(text: str) -> str:
    """Collapse one side of the exchange to a single bounded paragraph."""
    return " ".join(text.split())[:MAX_EXCERPT_CHARS]


def clean_title(reply: str) -> str | None:
    """Reduce a model reply to one title line, or ``None`` when nothing is left.

    Models answer with a bullet, a heading, backticks, or a quoted sentence even
    when told not to, so the first non-empty line is unwrapped before the length
    cap is applied. A reply that is only punctuation leaves no title at all.
    """
    for line in reply.splitlines():
        cleaned = _LEADING_MARKER.sub("", line.strip())
        cleaned = cleaned.strip("`*_# \t").strip("\"'").strip().rstrip(_TRAILING).strip()
        if cleaned:
            return cleaned[:MAX_TITLE_CHARS].strip() or None
    return None
