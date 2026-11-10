"""The panel ``/harness`` opens: every session's harness, with this session's row selected.

Up and Down move through the rows; Enter borrows the selected harness for the current session. The row for the current
session returns it to that session's own harness. The panel only reads the harness directories; ``/harness gen`` and
``/harness reset`` change the run.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from zettcode.tui import ListItem, ListPage

#: Rows the panel asks for when it is anchored to the bottom edge.
HARNESS_ROWS = 12


def _shown(directory: Path) -> str:
    """Return the folder as the subtitle shows it: the whole path, with the home directory collapsed to ``~``."""
    value = str(directory)
    home = str(Path.home())
    if value == home or value.startswith(home + "/"):
        return "~" + value[len(home) :]
    return value


class HarnessPage(ListPage):
    """Every session that has a harness, with the current one first and selected.

    Rows carry a session id as their value. Enter asks the command to borrow that session's harness; the panel itself
    writes nothing. Escape closes it.
    """

    def __init__(
        self,
        *,
        state: str,
        directory: Path,
        sessions: Sequence[tuple[str | None, str, str, bool]],
        on_switch: Callable[[str], None],
        on_close: Callable[[], None],
    ) -> None:
        """Build the rows from ``(session id, label, detail, disabled)``, current session first."""
        items = [
            ListItem(session_id, label, detail, disabled=disabled) for session_id, label, detail, disabled in sessions
        ]
        super().__init__(
            items,
            title="Harnesses",
            subtitle=_shown(directory),
            footer=f"harness is {state} \u00b7 enter borrow \u00b7 esc close",
            on_select=lambda item: on_switch(str(item.value)),
            on_cancel=on_close,
        )
