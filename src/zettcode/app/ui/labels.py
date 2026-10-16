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
from ..agent.conversation.text import STOP_HINT

#: The keys worth remembering, shown at the right of the status row.
KEY_HINTS = f"{STOP_HINT}  ^D exit"

#: The reasoning effort a fresh launch shows until ``/effort`` changes it: the
#: shell's own default, spelled the way the header spells it. The test that
#: compares the two frames cell by cell fails if the two ever drift apart.
DEFAULT_EFFORT = "medium"


def compact_path(path: Path, *, limit: int | None = 38) -> str:
    """Shorten a workspace path for the header.

    Args:
        path: Absolute path to display.
        limit: Most columns to keep; the home directory collapses to ``~``, and
            anything longer keeps a leading ellipsis plus its tail. ``None``
            keeps the whole path and collapses only the home directory, for a
            line that has the room to show it.
    """
    value = str(path)
    home = str(Path.home())
    if value == home or value.startswith(home + "/"):
        value = "~" + value[len(home) :]
    if limit is None:
        return value
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


#: The most columns of a session's title the header keeps. A title can be a hundred and twenty characters, and the
#: header is cut from its right end when the row is full: unbounded, a long title would push the session's name
#: and the workspace off the screen.
TITLE_COLUMNS = 36


def header_left(workspace: Path, name: str = "", handle: str = "") -> str:
    """Label the app, the session, and the workspace it runs in.

    The session comes before the workspace because a row that is too narrow loses its right end first, and which
    session this is matters more than a directory that does not change while it is open.

    Args:
        workspace: Directory the session runs in.
        name: The session's title, or its placeholder before it has one. Left out, the row names no session, which
            is how a frame drawn before there is one looks.
        handle: The name other sessions address this one by (without the ``@``); empty when messaging is off or the
            session is not registered yet.
    """
    parts = [
        _fit(name, TITLE_COLUMNS) if name else "",
        f"@{handle}" if handle else "",
        compact_path(workspace),
    ]
    return f"  {HEADER} zettcode  " + f" {SEPARATOR} ".join(part for part in parts if part)


def _fit(text: str, columns: int) -> str:
    """Return ``text`` cut to ``columns`` with an ellipsis when it is longer; a wide glyph is dropped whole."""
    if display_width(text) <= columns:
        return text
    kept = ""
    for character in text:
        if display_width(kept) + display_width(character) > columns - 1:
            break
        kept += character
    return kept.rstrip() + ELLIPSIS


def header_right(model: str, effort: str) -> str:
    """Show the model and the reasoning effort the next request will use."""
    return f"{model} {SEPARATOR} {effort}  "


def model_name(config_file: Path) -> str | None:
    """Return the model the header will name, read from the config file alone.

    The frame the command line paints is drawn before the settings module is
    imported, and the name it will show is in that file: reading the one value
    costs a file read, where importing the settings to ask for it costs their
    whole import graph. The rule is the settings' own — the first ``[[models]]``
    entry's ``display_model``, falling back to its id — but only that rule, so
    anything unreadable answers ``None`` and leaves the header's right side for
    the shell to fill in when it arrives.

    Args:
        config_file: The file the settings will be read from, which is
            ``$ZETTCODE_CONFIG`` or the conventional path.
    """
    from ..._compat import tomllib

    try:
        settings = tomllib.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    models = settings.get("models")
    if not isinstance(models, list) or not models or not isinstance(models[0], dict):
        return None
    for key in ("display_model", "model"):
        value = models[0].get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def status_left(label: str) -> str:
    """Show the activity glyph and its status word; the session is named in the header."""
    return f"  {STATUS} {label}"


def status_right() -> str:
    """List the keys worth remembering."""
    return f"  {KEY_HINTS}  "
