"""The read-only panel `/harness` opens: the switch's state, the folder, and this session's repositories."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from zettcode.tui import ListItem, ListPage

from .. import labels

#: Rows the panel asks for when it is anchored to the bottom edge.
HARNESS_ROWS = 12


class HarnessPage(ListPage):
    """What the harness is doing now: on or off, where its files are, and what the model has written.

    The page writes nothing: the switch lives on the `/plugins` page, which is where a reader turns the harness on or
    off for the next start. Each repository is one row; selecting any row (or Escape) closes the page.
    """

    def __init__(
        self,
        *,
        state: str,
        directory: Path,
        repositories: Sequence[tuple[str, str]],
        on_close: Callable[[], None],
    ) -> None:
        items = [ListItem(name, name, detail) for name, detail in repositories]
        if not items:
            items = [
                ListItem(
                    "none",
                    "No repositories yet",
                    "the model makes one with repo_create when the harness is on",
                )
            ]
        super().__init__(
            items,
            title=f"Harness is {state}",
            subtitle=labels.compact_path(directory, limit=None),
            footer="/plugins switches it \u00b7 esc close",
            on_select=lambda _value: on_close(),
            on_cancel=on_close,
        )
