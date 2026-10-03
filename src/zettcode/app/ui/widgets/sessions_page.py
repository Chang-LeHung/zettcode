"""The bottom-panel list of recent sessions opened by ``/sessions``."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from ....tui import ListItem, ListPage
from ....tui.render import display_width
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
          \u25b8 Fix the parser crash  3m ago \u00b7 1a2b3c4d
                                 2h ago \u00b7 9f8e7d6c   <- untitled: title column empty
        enter open \u00b7 esc back

    A session without a title keeps that column empty rather than inventing a
    placeholder, so the age is what identifies it; the short id still lets an
    untitled session be told apart from its neighbours. Rows commit the session
    id, which the shell turns into ``use_session``.

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
        """Map each session to a row, padding titles into one column."""
        titles = [session.title or "" for session in sessions]
        # Two extra columns keep a gap between the longest title and its age.
        column = max((display_width(title) for title in titles), default=0) + 2
        items = [
            ListItem(
                session.session_id,
                title + " " * max(0, column - display_width(title)),
                f"{format_ago(session.updated_at, now=now)} \u00b7 {session.session_id[:8]}",
            )
            for session, title in zip(sessions, titles, strict=True)
        ]
        super().__init__(
            items,
            title="Sessions",
            footer="enter open \u00b7 esc back",
            on_select=lambda item: on_select(str(item.value)),
            on_cancel=on_cancel,
        )
