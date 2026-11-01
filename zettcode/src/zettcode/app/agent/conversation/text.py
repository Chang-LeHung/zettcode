"""The words and bounds of a transcript row: its margin, its labels, how long output is allowed to be.

What a row says and how much of it is kept live here rather than with the conversation model: the left margin,
the bounding of tool output, the text of an elapsed time, the wording of the waiting row's remarks, and the
path the header shortens. The model imports these to build entries and the renderer imports them to paint, and
this module imports neither — which is what keeps the two apart. How a row *moves* is :mod:`.pulse`, and the
two animations of the effort setting are :mod:`.effort_gauge` and :mod:`.shimmer`.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from zettcode.sdk.types import Usage
from zettcode.statusline import compact_tokens
from zettcode.tui import ELLIPSIS
from zettcode.tui.glyphs import ARROW_DOWN, ARROW_UP, SEPARATOR
from zettcode.tui.render import count_wrapped_rows, display_width, truncate, wrap_columns

#: Left margin of every transcript row: the width of the composer's ``\u203a ``
#: prompt, so text lines up under what the user types and never starts left of
#: the caret in an empty composer.
CONTENT_INDENT = 2

#: Label of the row that shows a reasoning span while it streams.
THINKING_LABEL = "Thinking"

#: Label of the row that shows the summarizer working: the same kind of row, so
#: it carries the same marker and timer as reasoning does.
COMPACTING_LABEL = "Compacting"

MAX_TOOL_OUTPUT = 64_000
TOOL_PREVIEW_ROWS = 5
TOOL_EXPANDED_ROWS = 40

#: Label of a row shown while the model is working and has not answered yet.
#: One request can show it more than once: every tool batch is followed by
#: another model call, and until that call produces something there is nothing
#: else on screen to say work is still going on.
PROCESSING = "Processing"

#: What the reader can press to stop the request, shown beside its clock. The
#: status row builds its own hint from this, so the two cannot drift apart, and
#: both keys are named because both work: Escape stops a turn while one is in
#: flight, and a reader should not have to remember which of the two the shell
#: reserved for it.
STOP_HINT = "^C/Esc to interrupt"

#: What the row of a question the reader cancelled says under its title.
DECLINED_NOTE = "You declined; the model was told and carries on."

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
    if cleaned.replace("\n", "").isprintable():
        # Nothing to replace, which is the usual output: say so in one pass instead
        # of looking at every character of what may be tens of kilobytes.
        return cleaned
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
    hidden = 0
    for source in terminal_safe(value).splitlines() or [""]:
        if len(rows) < limit:
            rows.extend(wrap_columns(source, width))
        else:
            # Past the rows that are shown only the count is wanted, and counting
            # a line's rows does not need the rows: a 900-line test log is wrapped
            # for five of them.
            hidden += count_wrapped_rows(source, width)
    omitted = max(0, len(rows) - limit) + hidden
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


#: Seconds the model may say nothing before the waiting row says so. A first token after ten seconds is a
#: slow model and after twenty is something a reader is already wondering about; a reasoning model that
#: streams nothing for longer is also why this only *says* it and never gives up on the request.
QUIET_SECONDS = 20.0


#: Seconds a request has to run before a tip is put under its waiting row: one that is answered at once is not
#: worth a line, and a tip that flashes by is not read.
#: Whole seconds, like :data:`TIP_EVERY`: the waiting row's clock counts whole seconds and the picture the loop compares
#: holds that count, so a tip appears and changes on a second the loop already draws.
TIP_AFTER = 5.0

#: Seconds each tip stays before the next takes its place, long enough to read and not so long that a request of
#: several minutes shows one.
TIP_EVERY = 15.0


def tip_text(tips: tuple[str, ...], seconds: float | None) -> str | None:
    """Return the tip a request that has run for ``seconds`` shows, or ``None`` while it is too soon or there are none."""
    if not tips or seconds is None or seconds < TIP_AFTER:
        return None
    return tips[int((seconds - TIP_AFTER) // TIP_EVERY) % len(tips)]


def quiet_text(seconds: float) -> str | None:
    """Return what the waiting row says about a silence of ``seconds``, or ``None`` while it is too short to mention."""
    if seconds < QUIET_SECONDS:
        return None
    return f"nothing from the model for {elapsed_text(seconds)}"


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


def pack_segments(segments: list[str], room: int) -> list[str]:
    """Join segments with `` · `` into rows no wider than ``room``, breaking between segments and never inside one.

    A single segment wider than the room gets a row of its own and is cut to fit, so no row is ever too wide.
    """
    joint = f" {SEPARATOR} "
    rows: list[str] = []
    current = ""
    for segment in segments:
        if current and display_width(current) + display_width(joint) + display_width(segment) <= room:
            current += joint + segment
            continue
        if current:
            rows.append(current)
        current = segment
    if current:
        rows.append(current)
    return [row if display_width(row) <= room else truncate(row, room, ellipsis=ELLIPSIS) for row in rows]


def tokens_text(usage: Usage) -> str | None:
    """Say the tokens a request sent and received, or nothing before the model has answered."""
    if not usage.requests:
        return None
    return f"{ARROW_UP}{compact_tokens(usage.input_tokens)} {ARROW_DOWN}{compact_tokens(usage.output_tokens)}"


def cache_text(usage: Usage) -> str | None:
    """Say the share of the input the provider served from its cache, or nothing when it served none."""
    if usage.requests and usage.cache_read_tokens > 0 and usage.input_tokens > 0:
        return f"{usage.cache_read_tokens / usage.input_tokens * 100:.1f}% cached"
    return None


def calls_text(usage: Usage) -> str | None:
    """Say how many times the model was asked, when it was asked more than once."""
    return f"{usage.requests} model calls" if usage.requests > 1 else None


def speed_text(usage: Usage) -> str | None:
    """Say how fast the model generated, when it can be told and is at least one token a second.

    Reads :attr:`Usage.output_rate`, which leaves the opening chunk's tokens out of the numerator, so this line and the
    status line a reader sees above it never disagree.
    """
    rate = usage.output_rate
    if usage.requests and rate is not None and rate >= 1:
        return f"{rate:.1f} tok/s" if rate < 10 else f"{rate:.0f} tok/s"
    return None


def tools_text(tools: int, failed_tools: int = 0) -> str | None:
    """Say how many tool calls a request made and how many failed; the failures stay in the same segment."""
    if not tools:
        return None
    said = f"{tools} tool call{'' if tools == 1 else 's'}"
    return f"{said}, {failed_tools} failed" if failed_tools else said


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
    return ELLIPSIS + tail
