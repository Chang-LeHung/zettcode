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

#: The gaps between the table's four columns.
COLUMN_GAP = 2
HEADER_SESSION = "SESSION"
HEADER_TITLE = "TITLE"
HEADER_REPOSITORY = "REPOSITORY"
HEADER_DESCRIPTION = "DESCRIPTION"


@dataclass(frozen=True, slots=True)
class HarnessTarget:
    """One harness the current session can borrow: its display label and the folder to use."""

    label: str
    directory: Path


@dataclass(frozen=True, slots=True)
class HarnessRow:
    """One repository row: its source session, title, repository name and manifest description."""

    target: HarnessTarget
    session: str
    title: str
    repository: str
    description: str
    current: bool = False


def _shown(directory: Path) -> str:
    """Return the folder as the subtitle shows it: the whole path, with the home directory collapsed to ``~``."""
    value = str(directory)
    home = str(Path.home())
    if value == home or value.startswith(home + "/"):
        return "~" + value[len(home) :]
    return value


def _pad(value: str, width: int) -> str:
    """Pad a value with spaces to a display width, not a character count."""
    return value + " " * max(0, width - display_width(value))


class HarnessPage(ListPage):
    """A four-column table of repositories, with the current session's rows first and selected.

    Rows carry a :class:`HarnessTarget`. Enter asks the command to borrow that directory; the panel itself writes
    nothing. Escape closes it.
    """

    def __init__(
        self,
        *,
        state: str,
        directory: Path,
        sessions: Sequence[HarnessRow],
        on_switch: Callable[[HarnessTarget], None],
        on_close: Callable[[], None],
    ) -> None:
        """Build the table rows, current session first."""
        self.rows = tuple(sessions)
        self.session_width = max(
            [display_width(HEADER_SESSION), *(display_width(row.session) for row in self.rows)], default=0
        )
        self.title_width = max(
            [display_width(HEADER_TITLE), *(display_width(row.title) for row in self.rows)], default=0
        )
        self.repository_width = max(
            [display_width(HEADER_REPOSITORY), *(display_width(row.repository) for row in self.rows)], default=0
        )
        items = [
            ListItem(
                row.target,
                self._label(row),
                self._detail(row),
                current=row.current,
            )
            for row in self.rows
        ]
        super().__init__(
            items,
            title=f"Harnesses · harness is {state}",
            subtitle=_shown(directory),
            footer="accent = current session \u00b7 enter borrow \u00b7 esc close",
            on_select=lambda item: on_switch(cast(HarnessTarget, item.value)),
            on_cancel=on_close,
        )

    def _label(self, row: HarnessRow) -> str:
        """Return the session and title columns."""
        return f"{_pad(row.session, self.session_width)}{' ' * COLUMN_GAP}{_pad(row.title, self.title_width)}"

    def _detail(self, row: HarnessRow) -> str:
        """Return the repository and description columns."""
        return f"{_pad(row.repository, self.repository_width)}{' ' * COLUMN_GAP}{row.description}"

    def layout(self, rect: Rect) -> None:
        """Leave one row under the title for the column header."""
        super().layout(rect)
        list_rect = self.list.rect
        self.list.layout(Rect(list_rect.x, list_rect.y + 1, list_rect.width, max(0, list_rect.height - 1)))

    def render(self, canvas: Canvas) -> None:
        """Draw the page and the four column headers above the rows."""
        super().render(canvas)
        if self.rect.empty:
            return
        over = 1 if self.subtitle is not None else 0
        style = Style(foreground=self.theme.muted, background=self.theme.surface_alt)
        y = self.rect.y + 3 + over
        session_x = self.list.rect.x + self.list.MARKER_WIDTH
        title_x = session_x + self.session_width + COLUMN_GAP
        label_width = self.session_width + COLUMN_GAP + self.title_width
        repository_x = session_x + label_width + self.list.COLUMN_GAP
        description_x = repository_x + self.repository_width + COLUMN_GAP
        for x, label in (
            (session_x, HEADER_SESSION),
            (title_x, HEADER_TITLE),
            (repository_x, HEADER_REPOSITORY),
            (description_x, HEADER_DESCRIPTION),
        ):
            if x < self.rect.right:
                canvas.draw_text(x, y, label, style, max_width=max(0, self.rect.right - x))
