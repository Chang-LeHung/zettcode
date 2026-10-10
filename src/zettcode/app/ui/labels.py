"""The text of the built-in header and status rows.

One implementation, two callers: the plugin that draws those rows for the
running shell, and the frame the command line paints before the application
exists. Sharing the text is what lets the boot frame put the same characters on
screen, so the swap fills rows in instead of rewriting them.

Nothing heavy may be imported here — the boot frame's whole purpose is to draw
before the application's imports happen.
"""

from __future__ import annotations

from pathlib import Path

from ...tui import ELLIPSIS, HEADER, SEPARATOR, STATUS
from ...tui.render import display_width
from ..agent.rows import STOP_HINT

#: The keys worth remembering, shown at the right of the status row.
KEY_HINTS = f"{STOP_HINT}  ^D exit"


def compact_path(path: Path, *, limit: int = 38) -> str:
    """Shorten a workspace path for the header.

    Args:
        path: Absolute path to display.
        limit: Most columns to keep; the home directory collapses to ``~``, and
            anything longer keeps a leading ellipsis plus its tail. The budget
            counts display columns, so a path with wide characters is measured
            the way the header draws it.
    """
    value = str(path)
    home = str(Path.home())
    if value == home or value.startswith(home + "/"):
        value = "~" + value[len(home) :]
    width = display_width(value)
    if width <= limit:
        return value
    # Count the tail from the end so a wide glyph is dropped whole rather than
    # overhanging the budget, which the ellipsis also has to fit inside.
    budget = limit - 1
    tail = ""
    for character in reversed(value):
        if display_width(character) > budget:
            break
        tail = character + tail
        budget -= display_width(character)
    return f"{ELLIPSIS}{tail}"


def header_left(workspace: Path) -> str:
    """Label the app and the workspace it runs in."""
    return f"  {HEADER} zettcode  {compact_path(workspace)}"


def header_right(model: str, effort: str) -> str:
    """Show the model and the reasoning effort the next request will use."""
    return f"{model} {SEPARATOR} {effort}  "


def status_left(label: str, name: str) -> str:
    """Show the activity glyph, its status word, and the session's name."""
    return f"  {STATUS} {label}  {name}"


def status_right() -> str:
    """List the keys worth remembering."""
    return f"  {KEY_HINTS}  "
