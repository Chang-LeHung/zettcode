"""How one transcript row is measured, timed, and written.

The pieces a row is drawn from live here rather than with the conversation
model: the left margin, the bounding of tool output, the text of an elapsed
time, the running marker and its blink, and the sweep that walks a heading. The
model imports these to build entries and the renderer imports them to paint,
and this module imports neither — which is what keeps the two apart.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ...tui import ELLIPSIS, RUNNING
from ...tui.render import display_width, wrap_columns

#: Left margin of every transcript row: the width of the composer's ``\u203a ``
#: prompt, so text lines up under what the user types and never starts left of
#: the caret in an empty composer.
CONTENT_INDENT = 2

#: Label of the row that shows a reasoning span while it streams.
THINKING_LABEL = "Thinking"

#: Label of the row that shows the summarizer working: the same kind of row, so
#: it blinks, sweeps, and times like reasoning does.
COMPACTING_LABEL = "Compacting"

#: Wall-clock length of one animation step. ``Transcript.frame`` counts these
#: steps rather than terminal ticks, so the pace of the sweep and the running
#: marker does not depend on how often the terminal happens to repaint.
ANIMATION_SECONDS = 0.1

MAX_TOOL_OUTPUT = 64_000
TOOL_PREVIEW_ROWS = 5
TOOL_EXPANDED_ROWS = 40

#: Label of a row shown while the model is working and has not answered yet.
#: One request can show it more than once: every tool batch is followed by
#: another model call, and until that call produces something there is nothing
#: else on screen to say work is still going on.
PROCESSING = "Processing"

# Matches both escape families a tool can smuggle into its output: CSI
# (``ESC [`` parameters and a final byte) and OSC (``ESC ]`` up to BEL or ST).
# Stripping them keeps a coloured compiler message from repainting the canvas.
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")


def terminal_safe(value: str) -> str:
    """Strip escape sequences and replace characters the canvas cannot paint.

    Args:
        value: Raw tool output; newlines survive, a tab advances to the next
            four-column stop, and anything else non-printable becomes the
            replacement character so a tool cannot smuggle control codes into
            the canvas.

    Line endings are normalised first. Output printed with CRLF — a tool that
    shells out to ``curl -i`` or to a Windows program — would otherwise leave a
    replacement glyph at the end of every line, because a carriage return stops
    being a line break the moment it is replaced.
    """
    cleaned = _ANSI.sub("", value).replace("\r\n", "\n").replace("\r", "\n").expandtabs(4)
    return "".join(
        character if character in "\n" else character if character.isprintable() else "\ufffd" for character in cleaned
    )


def bounded_rows(value: str, width: int, limit: int) -> tuple[list[str], int]:
    """Wrap tool output and return a bounded viewport plus omitted rows.

    Args:
        value: Raw tool output.
        width: Wrap width in cells.
        limit: Most rows to return; the remainder is reported as omitted.
    """
    rows: list[str] = []
    for source in terminal_safe(value).splitlines() or [""]:
        rows.extend(wrap_columns(source, width))
    omitted = max(0, len(rows) - limit)
    return rows[:limit], omitted


def limit_output(value: str) -> str:
    """Bound stored tool output while keeping both ends useful.

    Args:
        value: Raw tool output; anything past ``MAX_TOOL_OUTPUT`` keeps its head
            and tail with a marker in between, so a huge result cannot dominate
            memory while still showing how it started and ended.
    """
    if len(value) <= MAX_TOOL_OUTPUT:
        return value
    half = MAX_TOOL_OUTPUT // 2
    omitted = len(value) - half * 2
    return f"{value[:half]}\n{ELLIPSIS} {omitted:,} characters omitted {ELLIPSIS}\n{value[-half:]}"


def duration_text(seconds: float | None) -> str:
    """Format an elapsed time for a row header, in the unit a reader wants.

    Args:
        seconds: Elapsed time, or ``None`` for a row that has already finished
            without a recorded duration.

    Under a minute the time is shown to the tenth of a second, because that is
    what makes a live row look alive and milliseconds would change the column's
    width on every repaint. Past a minute the tenth is noise — ``134.5 s`` is a
    number a reader has to divide before it means anything — so the row switches
    to minutes and seconds, and to hours and minutes past an hour. That column
    changes width as the units change: it narrows at each boundary — ``1m 0s``
    is a column narrower than ``59.9 s``, ``1h 0m`` two narrower than
    ``59m 59s`` — and widens as the count climbs inside one, so a running tool
    row's title is truncated again whenever it does. A whole request's wall time
    is a different question, so it goes through :func:`elapsed_text` instead.
    """
    if seconds is None:
        return "done"
    total = max(0.0, seconds)
    if round(total, 1) < 60:
        return f"{total:.1f} s"
    minutes, remainder = divmod(round(total), 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def elapsed_text(seconds: float) -> str:
    """Show every nonzero time unit in a finished request's wall time.

    Args:
        seconds: Wall time of the request, negative values clamped to zero.
    """
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def clock_text(moment: datetime | None = None) -> str:
    """Format a wall-clock reading as local ``HH:MM``.

    Args:
        moment: Time to show; ``None`` reads the clock, and tests inject a value
            so a rendered footer stays deterministic.
    """
    return (moment or datetime.now()).strftime("%H:%M")


#: The running marker's two states: the sparkle, then a dot of the same width so
#: the label after it never shifts as the marker blinks.
RUNNING_GLYPHS = RUNNING

#: Steps per half-blink: 2.7 steps is the quarter second a marker holds each of
#: its two states, so a running row blinks about twice a second.
BLINK_FRAMES = 2.7

#: Steps the highlight spends on one column, where a step is
#: :data:`ANIMATION_SECONDS` of wall time: one step is the 100 ms a column stays
#: lit, ten columns a second. The step, not the terminal frame, is what sets the
#: pace, so a repaint at 60 fps and one at 10 look the same.
SWEEP_FRAMES = 1.0


def sweep_step(frame: int) -> int:
    """Return the column the highlight has reached at one animation frame.

    Args:
        frame: Monotonic frame counter shared by the whole application.
    """
    return int(frame / SWEEP_FRAMES)


def activity_glyph(frame: int) -> str:
    """Return the marker shared by every running row, which blinks in place.

    The marker keeps one column and alternates between its two states instead of
    cycling through different symbols: a row that blinks reads as "still
    working" the way a terminal spinner does, while a rotating glyph just looks
    like noise. Every running row is drawn with the same ``frame``, so the
    transcript and the status bar icon blink in step.

    Args:
        frame: Monotonic frame counter shared by the whole application.
    """
    return RUNNING_GLYPHS[0 if blinking(frame) else 1]


def blinking(frame: int) -> bool:
    """Say whether a running row is in the bright half of its blink."""
    return int(frame / BLINK_FRAMES) % 2 == 0


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
    return ELLIPSIS + tail
