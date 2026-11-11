"""The panel ``/harness`` opens: every repository under the harness root, with this session's rows selected.

Up and Down move through the rows; Enter borrows the selected session's harness for the current session. The current
session's rows come first and choosing one returns to that session's own harness. The panel only reads the harness
directories; ``/harness gen`` and ``/harness reset`` change the run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from zettcode.tui import Canvas, ListItem, ListPage, Rect, Style
from zettcode.tui.render import display_width

#: Rows the panel asks for when it is anchored to the bottom edge.
HARNESS_ROWS = 12

#: The column labels above the rows.
HEADER_SESSION = "SESSION"
HEADER_REPOSITORY = "REPOSITORY — DESCRIPTION"


@dataclass(frozen=True, slots=True)
class HarnessTarget:
    """One harness the current session can borrow: its display label and the folder to use."""

    label: str
    directory: Path


def _shown(directory: Path) -> str:
    """Return the folder as the subtitle shows it: the whole path, with the home directory collapsed to ``~``."""
    value = str(directory)
    home = str(Path.home())
    if value == home or value.startswith(home + "/"):
        return "~" + value[len(home) :]
    return value


class HarnessPage(ListPage):
    """Every repository under the harness root, with the current session's rows first and selected.

    Rows carry a :class:`HarnessTarget`. Enter asks the command to borrow that directory; the panel itself writes
    nothing. Escape closes it.
    """

    def __init__(
        self,
        *,
        state: str,
        directory: Path,
        sessions: Sequence[tuple[HarnessTarget, str, str]],
        on_switch: Callable[[HarnessTarget], None],
        on_close: Callable[[], None],
    ) -> None:
        """Build the rows from ``(target, label, detail)``, current session first."""
        items = [ListItem(target, label, detail) for target, label, detail in sessions]
        super().__init__(
            items,
            title="Harnesses",
            subtitle=_shown(directory),
            footer=f"harness is {state} \u00b7 enter borrow \u00b7 esc close",
            on_select=lambda item: on_switch(cast(HarnessTarget, item.value)),
            on_cancel=on_close,
        )

    def layout(self, rect: Rect) -> None:
        """Leave one row under the title for the column header."""
        super().layout(rect)
        list_rect = self.list.rect
        self.list.layout(Rect(list_rect.x, list_rect.y + 1, list_rect.width, max(0, list_rect.height - 1)))

    def render(self, canvas: Canvas) -> None:
        """Draw the page and the column header above the rows."""
        super().render(canvas)
        if self.rect.empty:
            return
        over = 1 if self.subtitle is not None else 0
        style = Style(foreground=self.theme.muted, background=self.theme.surface_alt)
        y = self.rect.y + 3 + over
        column = max((display_width(item.label) for item in self.list.items), default=0)
        label_x = self.list.rect.x + self.list.MARKER_WIDTH
        description_x = label_x + column + self.list.COLUMN_GAP
        canvas.draw_text(label_x, y, HEADER_SESSION, style, max_width=max(0, self.rect.right - label_x))
        if description_x < self.rect.right:
            canvas.draw_text(
                description_x,
                y,
                HEADER_REPOSITORY,
                style,
                max_width=max(0, self.rect.right - description_x),
            )
