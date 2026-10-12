"""Say why a request failed, in words a row can show.

Kept out of the runtime and out of the extensions on purpose: the runtime composes the
extensions, an extension reports its failures with this, and a function both of them need
cannot live in either without the one importing the other.
"""

from __future__ import annotations

from ..._compat import BaseExceptionGroup


def describe_error(error: BaseException) -> str:
    """Return the reasons an exception carries, not the group that wraps them.

    A failure inside a task group arrives as an ``ExceptionGroup`` whose own
    text says nothing — "unhandled errors in a TaskGroup (1 sub-exception)" —
    and a server refusing a connection is reported exactly that way. The reasons
    are the leaves, so that is what a row shows, each one once, however deeply
    the groups nest.

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
        text = str(current).strip() or type(current).__name__
        if text not in reasons:
            reasons.append(text)
    return "; ".join(reasons)
