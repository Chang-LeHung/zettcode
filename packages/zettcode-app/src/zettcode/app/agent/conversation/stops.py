"""Say why a model stopped when it did not finish, in a sentence a reader can act on.

A model step ends in one of a few ways the library names (:class:`~zett_agent.stop.StopReason`), and only two are
normal: it finished, or it asked for tools. Every other ending leaves a reply that is missing, cut off, or not what the
model would have said, and a row that only says how long the request took would let that pass for an answer.

The same sentence is used live (an event arrives) and when a stored session is shown again (the message carries the
stop), so what was seen is what is seen again.
"""

from __future__ import annotations

from zett_agent.stop import StopInfo, StopReason

#: What to do about each ending the reader can do something about. A refusal has none: the same input is declined again.
_NEXT = {
    StopReason.MAX_OUTPUT: "/continue asks the model to carry on from there.",
    StopReason.INTERRUPTED: "/continue asks the model to start that reply again.",
    StopReason.PAUSED: "/continue picks the request up where the provider paused it.",
    StopReason.CONTEXT_FULL: "/compact summarizes the conversation to make room, or /new starts afresh.",
    StopReason.REFUSAL: "Rephrase the request, or choose another model with /model.",
}

#: Why it stopped, in the reader's terms, by reason.
_WHAT = {
    StopReason.MAX_OUTPUT: "The reply reached the model's output limit and is cut off.",
    StopReason.INTERRUPTED: "The reply was cut off before the model finished it.",
    StopReason.PAUSED: "The provider paused the reply before it was done.",
    StopReason.CONTEXT_FULL: "The context window filled up, so the reply stopped short.",
    StopReason.REFUSAL: "The model declined this request.",
    StopReason.OTHER: "The model stopped for a reason ZettCode does not know, so the reply may be incomplete.",
}


def stop_text(stop: StopInfo) -> str:
    """Return the line that says a model step ended abnormally, with what the provider said and what to try.

    Args:
        stop: How the step ended; one that ended normally has nothing to say and gives an empty string.
    """
    if stop.ok:
        return ""
    parts = [_WHAT.get(stop.reason, _WHAT[StopReason.OTHER])]
    said = stop.message or stop.category or (stop.raw if stop.raw not in (None, stop.reason.value) else None)
    if said:
        label = f"{stop.category}: " if stop.category and stop.message and stop.category != stop.message else ""
        parts.append(f"The provider said: {label}{said}")
    withheld = stop.detail.get("withheld_tool_calls")
    if isinstance(withheld, (list, tuple)) and withheld:
        names = ", ".join(sorted({str(name) for name in withheld}))
        parts.append(f"It had asked to run {names}; that was not done.")
    if stop.recommended_model:
        parts.append(f"The provider suggests {stop.recommended_model}.")
    advice = _NEXT.get(stop.reason)
    if advice:
        parts.append(advice)
    return " ".join(part if part.endswith((".", "!", "?")) else f"{part}." for part in parts)
