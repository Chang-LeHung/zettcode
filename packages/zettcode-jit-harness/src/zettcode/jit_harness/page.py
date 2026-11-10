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

#: Rows the panel asks for when it is anchored to the bottom edge.
HARNESS_ROWS = 12

#: The columns every row follows: session id and title, then the repository and its manifest description.
HEADER = "SESSION · REPOSITORY — DESCRIPTION"


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
        canvas.draw_text(
            self.rect.x + 2,
            self.rect.y + 3 + over,
            HEADER,
            style,
            max_width=max(0, self.rect.width - 4),
        )
