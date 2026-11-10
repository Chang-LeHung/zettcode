"""The panel ``/harness`` opens: every session's harness, with this session's row selected.

Up and Down move through the rows; Enter borrows the selected harness for the current session. The row for the current
session returns it to that session's own harness. The panel only reads the harness directories; ``/harness gen`` and
``/harness reset`` change the run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from zettcode.tui import ListItem, ListPage

#: Rows the panel asks for when it is anchored to the bottom edge.
HARNESS_ROWS = 12


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
    """Every session that has a harness, with the current one first and selected.

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
