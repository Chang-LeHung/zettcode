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

from zettcode.statusline import TURN_PARTS, Row
from zettcode.tui import ARROW_DOWN, ARROW_UP, ELLIPSIS, HEADER, STATUS
from zettcode.tui.render import display_width

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


def header_left(workspace: Path, name: str = "", handle: str = "") -> Row:
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
    row = Row(lead="  ")
    row.add("app", "The mark and name of the program at the start of the header", f"{HEADER} zettcode").gap()
    row.add("session", "The session's title; New session until it has one", _fit(name, TITLE_COLUMNS) if name else "")
    row.add(
        "handle", "The @name other sessions reach this one by, when messaging is on", f"@{handle}" if handle else ""
    )
    row.add("workspace", "The directory the session works in", compact_path(workspace))
    return row


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


def header_right(model: str, effort: str) -> Row:
    """Show the model and the reasoning effort the next request will use."""
    row = Row(trail="  ")
    row.add("model", "The model the next request goes to", model)
    row.add("effort", "How much the model reasons on the next request", effort)
    return row


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
    from zettcode._compat import tomllib

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


def hidden_parts(config_file: Path) -> tuple[str, ...]:
    """Return the header and status-line parts the config file switches off, read from the file alone.

    Like :func:`model_name` this is for the frame drawn before the settings are imported, so it reads the one
    table and trusts nothing: anything unreadable, a name that is no part, or a value that is not ``false``
    answers "nothing hidden" for that entry, and the application reports the mistake when it arrives.
    """
    from zettcode._compat import tomllib
    from zettcode.statusline import NAMES

    try:
        table = tomllib.loads(config_file.read_text(encoding="utf-8")).get("statusline")
    except (OSError, ValueError):
        return ()
    if not isinstance(table, dict):
        return ()
    return tuple(name for name in NAMES if table.get(name) is False)


def status_left(
    label: str,
    *,
    icon: str = STATUS,
    permission: str = "ask",
    self_compact: bool = False,
    tokens: str = "",
    cache: str = "",
    speed: str = "",
    ctx: str = "",
) -> Row:
    """Show what is happening, the mode it runs in, and what the session has cost so far.

    The session is named in the header. Before the first reply the counters are empty and take no room.

    Args:
        label: The status word, or the one-off note that stands in for it.
        icon: The activity glyph; the still dot unless a request is running.
        permission: The shell permission; ``ask`` is the default and is not shown.
        self_compact: Whether the model may compact its own context in this session.
        tokens: Tokens sent and received, as the figures read.
        cache: The cache share, as it reads.
        speed: The generation speed, as it reads.
        ctx: How full the context window is, as it reads.
    """
    row = Row(lead="  ")
    row.add("state", "The activity icon and what is happening: ready, thinking, a tool running", f"{icon} {label}")
    row.add(
        "mode",
        "How much of the shell may run unasked; shown unless it is ask",
        "" if permission == "ask" else permission,
    )
    row.add(
        "self-compact",
        "Marks a session where the model may compact its own context",
        "self-compact" if self_compact else "",
    )
    row.gap()
    row.add("tokens", "Tokens sent and received in this session", tokens)
    row.add("cache", "The share of input the provider served from its cache", cache)
    row.add("speed", "How fast the model generates, in tokens per second", speed)
    row.add("ctx", "How much of the model's context window the last request filled", ctx)
    return row


def turn_line() -> Row:
    """Show the line a request ends on as the panel previews it: the program's own items on a plausible request."""
    samples = {
        "turn-time": "Processed for 12s",
        "turn-clock": "22:53",
        "turn-tokens": f"{ARROW_UP}12.3k {ARROW_DOWN}1.2k",
        "turn-cache": "87.0% cached",
        "turn-calls": "3 model calls",
        "turn-speed": "62 tok/s",
        "turn-tools": "5 tool calls, 1 failed",
    }
    row = Row(lead="  ")
    for name, summary in TURN_PARTS:
        row.add(name, summary, samples[name])
    return row


def status_right() -> Row:
    """List the keys worth remembering."""
    row = Row(lead="  ", trail="  ")
    row.add("keys", "The keys worth remembering: stop and exit", KEY_HINTS)
    return row
