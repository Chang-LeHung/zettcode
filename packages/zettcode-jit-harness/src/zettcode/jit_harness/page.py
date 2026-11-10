"""The panel ``/harness`` opens: every session's harness, with this session's row selected.

Up and Down move through the rows; Enter switches to the selected session, whose harness then belongs to the current
conversation. The panel only reads the harness directories; ``/harness gen`` and ``/harness reset`` change the run.
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

    Rows carry a session id as their value. Enter asks the shell to switch to that session; the panel itself writes
    nothing. Escape closes it.
    """

    def __init__(
        self,
        *,
        state: str,
        directory: Path,
        sessions: Sequence[tuple[str, str, str]],
        on_switch: Callable[[str], None],
        on_close: Callable[[], None],
    ) -> None:
        """Build the rows from ``(session id, label, detail)``, current session first."""
        items = [ListItem(session_id, label, detail) for session_id, label, detail in sessions]
        if not items:
            items = [
                ListItem(
                    None,
                    "No harness yet",
                    "run /harness gen in a session; its tools live in that session's folder",
                    disabled=True,
                )
            ]
        super().__init__(
            items,
            title=f"Harness is {state}",
            subtitle=_shown(directory),
            footer="enter switch \u00b7 esc close",
            on_select=lambda item: on_switch(str(item.value)) if item.value is not None else on_close(),
            on_cancel=on_close,
        )
