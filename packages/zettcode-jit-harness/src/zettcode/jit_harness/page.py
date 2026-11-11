"""The full-screen harness browser: repositories, tools and Markdown files in three tabs.

`Tab` changes the view. The current session's rows are drawn in the accent colour; a banned tool is drawn in the error
colour. The picker only reads the harness tree; `gen` and `reset` are still the commands that change the run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from zettcode.tui import Canvas, KeyEvent, ListItem, ListPage, Rect, Style
from zettcode.tui.render import display_width

#: The gap between the table's columns.
COLUMN_GAP = 2


@dataclass(frozen=True, slots=True)
class HarnessTarget:
    """One harness the current session can borrow: its display label and the folder to use."""

    label: str
    directory: Path


@dataclass(frozen=True, slots=True)
class TableRow:
    """One row of a tab: four cells, plus how the row is painted.

    ``target`` is set only by the Harness tab; Tools and Files rows carry ``None`` so Enter cannot borrow or close.
    """

    target: HarnessTarget | None
    cells: tuple[str, str, str, str]
    current: bool = False
    danger: bool = False


@dataclass(frozen=True, slots=True)
class TableView:
    """One tab: its heading, four column labels, rows, and the legend for its footer."""

    title: str
    headers: tuple[str, str, str, str]
    rows: Sequence[TableRow]
    footer: str = "esc close"


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
    """A full-screen four-column table with tabs for harnesses, tools and Markdown files."""

    def __init__(
        self,
        *,
        state: str,
        directory: Path,
        views: Sequence[TableView],
        on_switch: Callable[[HarnessTarget], None],
        on_close: Callable[[], None],
    ) -> None:
        """Build the first view and keep the others for Tab."""
        if not views:
            raise ValueError("The harness page needs at least one view")
        self.views = tuple(views)
        self.index = 0
        self.state = state
        self.directory = directory
        self._widths = self._measure(self.views[0])
        super().__init__(
            self._items(self.views[0]),
            title=f"{self.views[0].title} · harness is {state}",
            subtitle=f"{_shown(directory)}  ·  {self._tabs()}",
            footer=self._footer(),
            on_select=lambda item: on_switch(cast(HarnessTarget, item.value)) if item.value is not None else None,
            on_cancel=on_close,
        )

    def _measure(self, view: TableView) -> tuple[int, int, int]:
        """Return the widths of the first three cells."""
        widths = [
            max([display_width(header), *(display_width(row.cells[index]) for row in view.rows)])
            for index, header in enumerate(view.headers[:3])
        ]
        return widths[0], widths[1], widths[2]

    def _label(self, row: TableRow) -> str:
        """Return the first three cells, padded into columns."""
        widths = self._widths
        return f"{_pad(row.cells[0], widths[0])}{' ' * COLUMN_GAP}{_pad(row.cells[1], widths[1])}{' ' * COLUMN_GAP}{_pad(row.cells[2], widths[2])}"

    def _items(self, view: TableView) -> list[ListItem]:
        """Return the rows of one view with its column widths."""
        return [
            ListItem(row.target, self._label(row), row.cells[3], current=row.current, danger=row.danger)
            for row in view.rows
        ]

    def _tabs(self) -> str:
        """Return the tab strip under the heading."""
        return "  ".join(
            f"[{view.title}]" if index == self.index else view.title for index, view in enumerate(self.views)
        )

    def _footer(self) -> str:
        """Return the legend the active tab declares."""
        return self.views[self.index].footer

    def _show(self, index: int) -> None:
        """Switch to a tab, replacing the list's rows and header widths."""
        index %= len(self.views)
        self.index = index
        view = self.views[index]
        self._widths = self._measure(view)
        self.title = f"{view.title} · harness is {self.state}"
        self.subtitle = f"{_shown(self.directory)}  ·  {self._tabs()}"
        self.footer = self._footer()
        self.list.set_items(self._items(view))
        self.invalidate()

    def capture_event(self, event, host) -> bool:
        """Let Tab and Shift-Tab change the view before the list sees the key."""
        if isinstance(event, KeyEvent) and event.key in {"tab", "backtab"}:
            self._show(self.index + (1 if event.key == "tab" else -1))
            return True
        return super().capture_event(event, host)

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
        view = self.views[self.index]
        over = 1 if self.subtitle is not None else 0
        style = Style(foreground=self.theme.muted, background=self.theme.surface_alt)
        y = self.rect.y + 3 + over
        widths = self._widths
        first = self.list.rect.x + self.list.MARKER_WIDTH
        second = first + widths[0] + COLUMN_GAP
        third = second + widths[1] + COLUMN_GAP
        fourth = first + sum(widths) + 2 * COLUMN_GAP + self.list.COLUMN_GAP
        for x, label in zip((first, second, third, fourth), view.headers[:4], strict=True):
            if x < self.rect.right:
                canvas.draw_text(x, y, label, style, max_width=max(0, self.rect.right - x))
