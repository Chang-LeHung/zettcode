"""Messages held to be sent once the running request is over.

A follow-up is the other kind of message a reader can send while the agent is working.
A steering message is handed to the agent, which adopts it at its next boundary and
drops the rest of the task; a follow-up waits here, in the reader's hands, and goes out
as a turn of its own when the request ends. Because it has not been handed to anyone it
can still be changed, so this container — unlike the steering one — has a highlight,
and the row under the list says which keys use it.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from ....tui import MARKER, SEPARATOR, Canvas, Constraints, Size, Style, Widget
from ....tui.render import ELLIPSIS, display_width, truncate
from ...agent.conversation.rows import CONTENT_INDENT

#: Right-aligned badge that says a row is a follow-up.
FOLLOW_UP_BADGE = "follow-up"
#: What stands before a waiting message: a bullet, because it is an item in a list.
BULLET = "\u2022"
#: What the modifier key is called on this machine's keyboard. The same physical key sends
#: the same bytes everywhere; only its name differs, and a hint that says "alt" to someone
#: looking at a key marked "option" is a hint they have to translate.
OPTION = "option" if sys.platform == "darwin" else "alt"
#: The row under the list when nothing is highlighted: what the container is, and the
#: key that reaches the rest.
HINT_IDLE = f"sent in order after a reply completes {SEPARATOR} {OPTION}+\u2191/\u2193 to select"
#: The same row when no request is running. The list is still there — a request that was
#: stopped leaves it alone — and "after this request" would be about nothing.
HINT_HELD = f"held until your next reply completes {SEPARATOR} {OPTION}+\u2191/\u2193 to select"
#: The row under the list while one message is highlighted: everything it can do. The arrows
#: move the highlight, and with the modifier they move the message.
HINT_SELECTED = (
    f"\u2191/\u2193 select {SEPARATOR} {OPTION}+\u2191/\u2193 reorder {SEPARATOR} enter edit "
    f"{SEPARATOR} del remove {SEPARATOR} esc done"
)
#: Left margin, shared with the transcript and the composer prompt.
INDENT = CONTENT_INDENT
#: Columns the marker and the space after it take.
MARKER_COLUMNS = 2
#: Cells kept between the message and the badge so they never touch.
BADGE_GAP = 2


def one_line(message: str) -> str:
    """Return the first line of a message, marked when there were more.

    A row is one line tall, and a message with a line break in it would otherwise draw a
    control character into the middle of the list. The ellipsis says the rest is there.
    """
    lines = message.strip().splitlines()
    head = lines[0].strip() if lines else ""
    return f"{head} {ELLIPSIS}" if len(lines) > 1 else head


class FollowUpQueue(Widget):
    """Show the messages waiting for the request to end, one row each, with a highlight.

    Shape::

          \u2022 then run the tests                              follow-up
        \u25b8 summarize what changed                            follow-up   <- highlighted
          \u2022 and open a pull request                         follow-up
          enter edit \u00b7 shift+\u2191/\u2193 reorder \u00b7 alt+\u2191/\u2193 move \u00b7 esc done
        ^ marker, body text           right-aligned badge, then the keys

    The rows are in the order they will be sent, the first at the top. The highlighted
    row is banded and bold, the way a picker marks its choice, and the row under the
    list changes with it: before anything is highlighted it names the one key that
    starts, after it lists the rest. An empty queue asks for no rows, so the body slot
    collapses and the composer keeps its place.
    """

    def __init__(self) -> None:
        """Start with nothing waiting and nothing highlighted."""
        super().__init__()
        self.messages: tuple[str, ...] = ()
        self.selected: int | None = None
        #: Whether nothing is running, so the list waits for the reader's next reply
        #: rather than for the one in flight.
        self.held = False

    @property
    def visible(self) -> bool:
        """Return whether any messages are waiting."""
        return bool(self.messages)

    def set_messages(self, messages: Sequence[str], selected: int | None = None, *, held: bool = False) -> bool:
        """Replace the list and the highlight, and report whether anything changed.

        Args:
            messages: What is waiting, in the order it will be sent.
            selected: Index of the highlighted row, or ``None``; one past the end is
                treated as none, because the shell asks for it when the list shrinks.
            held: Whether no request is running, which changes what the keys line says
                the list is waiting for.
        """
        updated = tuple(messages)
        chosen = selected if selected is not None and 0 <= selected < len(updated) else None
        if updated == self.messages and chosen == self.selected and held == self.held:
            return False
        self.messages = updated
        self.selected = chosen
        self.held = held
        self.invalidate()
        return True

    @property
    def hint(self) -> str:
        """Return the keys line for the current state."""
        if self.selected is not None:
            return HINT_SELECTED
        return HINT_HELD if self.held else HINT_IDLE

    def preferred_height(self) -> int:
        """Return one row per message plus the keys line, or none."""
        return len(self.messages) + 1 if self.messages else 0

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the widest row, the keys line included."""
        widest = max((display_width(one_line(message)) for message in self.messages), default=0)
        row = INDENT + MARKER_COLUMNS + widest + BADGE_GAP + display_width(FOLLOW_UP_BADGE)
        note = INDENT + max(display_width(HINT_SELECTED), display_width(HINT_HELD))
        return constraints.constrain(Size(max(row, note), self.preferred_height()))

    def render(self, canvas: Canvas) -> None:
        """Paint the rows, banding the highlighted one, and the keys line under them."""
        if not self.messages or self.rect.empty:
            return
        theme = self.theme
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=theme.surface), " ")
        width = self.rect.width
        badge = display_width(FOLLOW_UP_BADGE)
        left = INDENT + MARKER_COLUMNS
        reserved = left + badge + BADGE_GAP
        # A row too narrow for both drops the badge rather than the message.
        show_badge = width >= reserved + 4
        text_width = max(0, width - (reserved if show_badge else left))
        for row, message in enumerate(self.messages):
            y = self.rect.y + row
            if y >= self.rect.y + self.rect.height:
                return
            chosen = row == self.selected
            if chosen:
                band = Style(foreground=theme.text, background=theme.selection, bold=True)
                canvas.fill(self.rect.x, y, width, 1, band, " ")
                marker, body, badge_style = MARKER, band, Style(foreground=theme.muted, background=theme.selection)
            else:
                marker = BULLET
                body = Style(foreground=theme.text)
                badge_style = Style(foreground=theme.muted)
            canvas.draw_text(
                self.rect.x + INDENT, y, marker, Style(foreground=theme.accent, background=body.background, bold=chosen)
            )
            canvas.draw_text(self.rect.x + left, y, truncate(one_line(message), text_width), body, max_width=text_width)
            if show_badge:
                canvas.draw_text(self.rect.x + width - badge, y, FOLLOW_UP_BADGE, badge_style)
        note_y = self.rect.y + len(self.messages)
        if note_y < self.rect.y + self.rect.height:
            note_width = max(0, width - INDENT)
            canvas.draw_text(
                self.rect.x + INDENT,
                note_y,
                truncate(self.hint, note_width),
                Style(foreground=theme.muted),
                max_width=note_width,
            )
