"""Messages queued to steer the request that is already running.

Steering is urgent input: the agent adopts it at the next model or tool
boundary and drops the rest of the current task, so a reader needs to see that
their message was taken rather than ignored. The queue empties as the agent
adopts each message, ending with the widget contributing no rows at all.
"""

from __future__ import annotations

from collections.abc import Sequence

from ....tui import STEERING, Canvas, Constraints, Size, Style, Widget
from ....tui.render import display_width, truncate
from ...agent.rows import CONTENT_INDENT

#: Right-aligned badge that says a row is a steering message.
STEER_BADGE = "steer"
#: Shown under the rows: when the agent will actually adopt the message.
STEER_WHEN = "sent when the running tool call or assistant message ends"
#: Left margin, shared with the transcript and the composer prompt, so the
#: markers line up in one column.
INDENT = CONTENT_INDENT
#: Columns the marker and the space after it take.
MARKER_COLUMNS = 2
#: Cells kept between the message and the badge so they never touch.
BADGE_GAP = 2


class SteeringQueue(Widget):
    """Show the messages waiting to steer the running request, one row each.

    Shape::

          \u21b3 stop editing and explain                      steer
          \u21b3 then run the tests                             steer
          sent when the running tool call or assistant message ends
        ^ U+21B3 marker, body text    right-aligned badge, then the timing

    Rows sit on their own raised fill, one step quieter than the composer band
    below, so the queue reads as pending rather than as part of the input. An
    empty queue asks for no rows, so the body slot collapses and the composer
    keeps its place when nothing is pending.
    """

    def __init__(self) -> None:
        """Start with nothing queued."""
        super().__init__()
        self.messages: tuple[str, ...] = ()

    @property
    def visible(self) -> bool:
        """Return whether any messages are waiting."""
        return bool(self.messages)

    def set_messages(self, messages: Sequence[str]) -> bool:
        """Replace the queue and report whether it actually changed."""
        updated = tuple(messages)
        if updated == self.messages:
            return False
        self.messages = updated
        self.invalidate()
        return True

    def preferred_height(self) -> int:
        """Return one row per queued message plus the timing note, or none."""
        return len(self.messages) + 1 if self.messages else 0

    def measure(self, constraints: Constraints) -> Size:
        """Ask for the widest row, the timing note included."""
        widest = max((display_width(message) for message in self.messages), default=0)
        row = INDENT + MARKER_COLUMNS + widest + BADGE_GAP + display_width(STEER_BADGE)
        note = INDENT + display_width(STEER_WHEN)
        return constraints.constrain(Size(max(row, note), self.preferred_height()))

    def render(self, canvas: Canvas) -> None:
        """Paint the queued rows and the timing note over the input surface."""
        if not self.messages or self.rect.empty:
            return
        theme = self.theme
        canvas.fill(
            self.rect.x,
            self.rect.y,
            self.rect.width,
            self.rect.height,
            Style(background=theme.surface),
            " ",
        )
        width = self.rect.width
        badge = display_width(STEER_BADGE)
        left = INDENT + MARKER_COLUMNS
        reserved = left + badge + BADGE_GAP
        # A row too narrow for both drops the badge rather than the message.
        show_badge = width >= reserved + 4
        text_width = max(0, width - (reserved if show_badge else left))
        for row, message in enumerate(self.messages):
            y = self.rect.y + row
            if y >= self.rect.y + self.rect.height:
                return
            canvas.draw_text(self.rect.x + INDENT, y, STEERING, Style(foreground=theme.accent))
            canvas.draw_text(
                self.rect.x + left,
                y,
                truncate(message, text_width),
                Style(foreground=theme.text),
                max_width=text_width,
            )
            if show_badge:
                canvas.draw_text(self.rect.x + width - badge, y, STEER_BADGE, Style(foreground=theme.muted))
        note_y = self.rect.y + len(self.messages)
        if note_y < self.rect.y + self.rect.height:
            note_width = max(0, width - INDENT)
            canvas.draw_text(
                self.rect.x + INDENT,
                note_y,
                truncate(STEER_WHEN, note_width),
                Style(foreground=theme.muted),
                max_width=note_width,
            )
