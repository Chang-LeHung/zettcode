"""The panel ``/harness`` opens: the switch's state, the folder, and this session's repositories.

The two words beside the panel change **this run** — ``gen`` turns the switch on, which every session in the window
sees, and has a tool built; ``reset`` turns it off again so later requests use the framework's own harness, and keeps
what this session wrote — while ``/plugins`` is what a run starts with. The panel itself writes nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from zettcode.tui import ListItem, ListPage

#: Rows the panel asks for when it is anchored to the bottom edge.
HARNESS_ROWS = 12


def _shown(directory: Path) -> str:
    """Return the folder as the subtitle shows it: the whole path, with the home directory collapsed to ``~``.

    The panel has the width of the screen, so unlike the header it does not shorten the tail; the one substitution is
    the home directory, which is longer than it says.
    """
    value = str(directory)
    home = str(Path.home())
    if value == home or value.startswith(home + "/"):
        return "~" + value[len(home) :]
    return value


class HarnessPage(ListPage):
    """What the harness is doing now: on or off, where its files are, and what the model has written.

    The page writes nothing: `/harness gen` and `/harness reset` are what turn it on and hand it back, and
    `/plugins` is where the harness is switched for the next start. Each repository is one row; selecting any row (or
    Escape) closes the page.
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
            subtitle=_shown(directory),
            footer="/harness gen|reset \u00b7 /plugins: next start \u00b7 esc close",
            on_select=lambda _value: on_close(),
            on_cancel=on_close,
        )
