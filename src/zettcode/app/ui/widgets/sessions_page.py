"""The bottom-panel list of recent sessions opened by ``/resume``."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from ....tui import SEPARATOR, ListItem, ListPage
from ....tui.render import display_width
from ...agent.agent import UNTITLED_SESSION
from ...agent.storage import SessionInfo


def format_ago(moment: datetime, *, now: datetime | None = None) -> str:
    """Return how long ago ``moment`` was, in the coarsest unit that fits.

    Args:
        moment: When the session last changed; stored times are UTC.
        now: Current time, injected by tests; defaults to the real clock.
    """
    seconds = max(0, int(((now or datetime.now(UTC)) - moment).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86_400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86_400}d ago"


class SessionsPage(ListPage):
    """Recent sessions as a selectable :class:`ListPage`.

    Shape::

        Sessions
          \u25b8 1. Fix the parser crash  3m ago \u00b7 1a2b3c4d
            2. New session            17h ago \u00b7 9f8e7d6c   <- still unnamed
        enter open \u00b7 esc back

    Each row is numbered so a long list can be counted at a glance, and a
    session without a title reads as ``New session``, the same name the status
    line shows; the short id after the age is what tells two of them apart.
    Rows commit the session id, which the shell turns into ``use_session``. The
    title column is aligned by the list itself, and the ages are padded inside
    the description, because ``3h ago`` is a column narrower than ``17m ago``
    and the id after it would otherwise step in and out of line.

    Args:
        sessions: Metadata rows to show, newest first, as returned by the store.
        on_select: Receives the chosen session id.
        on_cancel: Called when the user presses Escape.
        now: Current time for the age column; tests inject it, everything else
            reads the clock so a long-open panel keeps counting.
    """

    def __init__(
        self,
        sessions: Sequence[SessionInfo],
        *,
        on_select: Callable[[str], None],
        on_cancel: Callable[[], None],
        now: datetime | None = None,
    ) -> None:
        """Map each session to a row, padding titles and right-aligning ages."""
        titles = [session.title or UNTITLED_SESSION for session in sessions]
        ages = [format_ago(session.updated_at, now=now) for session in sessions]
        age_column = max((display_width(age) for age in ages), default=0)
        digits = len(str(len(sessions))) if sessions else 1
        items = [
            ListItem(
                session.session_id,
                f"{index:>{digits}}. {title}",
                f"{' ' * max(0, age_column - display_width(age))}{age} {SEPARATOR} {session.session_id[:8]}",
            )
            for index, (session, title, age) in enumerate(zip(sessions, titles, ages, strict=True), start=1)
        ]
        super().__init__(
            items,
            title="Sessions",
            footer=f"enter open {SEPARATOR} esc back",
            on_select=lambda item: on_select(str(item.value)),
            on_cancel=on_cancel,
        )
