"""Say why a request failed, in words a row can show.

Kept out of the runtime and out of the extensions on purpose: the runtime composes the
extensions, an extension reports its failures with this, and a function both of them need
cannot live in either without the one importing the other.
"""

from __future__ import annotations

import re

from ..._compat import BaseExceptionGroup

#: The most characters of what a server said that an error carries: enough for a sentence, not a page of HTML.
MAX_DETAIL = 200

#: What to try, by the status a server answered with. Only the ones where the fix is the reader's own to make.
HINTS = {
    401: "check the token with /config",
    403: "check the token and what it may use, with /config",
    404: "check the model id and the address with /config",
}

#: Something that looks like a credential in text a server sent back, which must not reach the screen:
#: ``sk-proj-****abcd`` is how a provider says which key it refused, and the end of a key is still part of it.
_SECRET = re.compile(r"\b(?:sk|pk|rk|key|tok|ghp|xox[a-z])[-_][A-Za-z0-9_*.\-]{4,}|Bearer\s+\S+", re.IGNORECASE)
_TAGS = re.compile(r"<[^>]+>")


def describe_error(error: BaseException) -> str:
    """Return the reasons an exception carries, not the group that wraps them, and what the server said.

    A failure inside a task group arrives as an ``ExceptionGroup`` whose own
    text says nothing — "unhandled errors in a TaskGroup (1 sub-exception)" —
    and a server refusing a connection is reported exactly that way. The reasons
    are the leaves, so that is what a row shows, each one once, however deeply
    the groups nest.

    A provider's own errors say what failed and not why: ``Provider stream request failed`` is the whole of
    a 404 for a model that does not exist, a 429 for an account out of quota, and a 502 from a proxy. The why
    is on the exception that caused it, so each leaf is followed down its causes to the HTTP status and what
    the server said, and that is added in brackets — with what to try, where the fix is the reader's.

    Args:
        error: The exception a request failed with.

    Returns:
        The leaf reasons joined by ``"; "``, or the class name when a reason has
        no text of its own.
    """
    reasons: list[str] = []
    pending: list[BaseException] = [error]
    while pending:
        current = pending.pop(0)
        if isinstance(current, BaseExceptionGroup):
            pending[:0] = list(current.exceptions)
            continue
        text = _leaf_text(current)
        if text not in reasons:
            reasons.append(text)
    return "; ".join(reasons)


def _leaf_text(error: BaseException) -> str:
    """Return one exception's text with the cause that explains it, when it has one."""
    own = _server_said(error)
    if own is not None:
        return own  # an SDK error raised as it is: its own text is a dict printed after "Error code: 404 -"
    text = str(error).strip() or type(error).__name__
    detail = _cause_detail(error)
    if not detail or detail.lower() in text.lower():
        return text
    if text.lower() in detail.lower():
        return detail  # the wrapper already said the first half of what the cause says in full
    return f"{text} ({detail})"


def _cause_detail(error: BaseException) -> str | None:
    """Return what the nearest cause says: what a server answered, or what the connection did."""
    seen = {id(error)}
    cause = error.__cause__
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        said = _server_said(cause)
        if said is not None:
            return said
        if isinstance(cause, (OSError, TimeoutError)) or type(cause).__module__.startswith("httpx"):
            reason = str(cause).strip()
            return f"{type(cause).__name__}: {reason}" if reason else type(cause).__name__
        cause = cause.__cause__
    return None


def _server_said(error: BaseException) -> str | None:
    """Return ``HTTP 404: the model does not exist — check ...`` for an error that carries a status, else ``None``."""
    status = getattr(error, "status_code", None)
    if isinstance(status, bool) or not isinstance(status, int):
        return None
    message = _message_of(error)
    said = f"HTTP {status}: {message}" if message else f"HTTP {status}"
    hint = HINTS.get(status)
    return f"{said} \u2014 {hint}" if hint else said


def _message_of(error: BaseException) -> str:
    """Return the sentence a server gave for a failure, whatever shape its error body had, cleaned for one line."""
    body = getattr(error, "body", None)
    message = ""
    if isinstance(body, dict):
        inner = body.get("error")
        source = inner if isinstance(inner, dict) else body
        found = source.get("message") if isinstance(source, dict) else None
        message = found if isinstance(found, str) else ""
    elif isinstance(body, str):
        message = body
    if not message:
        text = str(getattr(error, "message", "") or "")
        message = re.sub(r"^Error code: \d+\s*-?\s*", "", text)
        if message.lstrip().startswith(("{", "[")):
            message = ""  # the dict printed back: nothing in it that was not already tried above
    message = _TAGS.sub(" ", message)
    message = _SECRET.sub("\u2026", " ".join(message.split()))
    if len(message) > MAX_DETAIL:
        message = message[: MAX_DETAIL - 1].rstrip() + "\u2026"
    return message
