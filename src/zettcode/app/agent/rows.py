"""How one transcript row is measured, timed, and written.

The pieces a row is drawn from live here rather than with the conversation
model: the left margin, the bounding of tool output, the text of an elapsed
time, the running marker and its blink, and the sweep that walks a heading. The
model imports these to build entries and the renderer imports them to paint,
and this module imports neither — which is what keeps the two apart.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ...tui import ELLIPSIS, RUNNING
from ...tui.render import count_wrapped_rows, display_width, wrap_columns

#: Left margin of every transcript row: the width of the composer's ``\u203a ``
#: prompt, so text lines up under what the user types and never starts left of
#: the caret in an empty composer.
CONTENT_INDENT = 2

#: Label of the row that shows a reasoning span while it streams.
THINKING_LABEL = "Thinking"

#: Label of the row that shows the summarizer working: the same kind of row, so
#: it carries the same marker and timer as reasoning does.
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

#: What the reader can press to stop the request, shown beside its clock. The
#: status row builds its own hint from this, so the two cannot drift apart, and
#: both keys are named because both work: Escape stops a turn while one is in
#: flight, and a reader should not have to remember which of the two the shell
#: reserved for it.
STOP_HINT = "^C/Esc to interrupt"

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
#: the label after it never shifts as the row pulses.
RUNNING_GLYPHS = RUNNING

#: Seconds one pulse of the waiting row takes: it moves for a second and a half,
#: then rests for a second before it moves again. The marker and the highlight
#: share the period, so the row reads as one thing breathing instead of two
#: effects on clocks of their own.
MOVE_SECONDS = 1.5
REST_SECONDS = 1.0

#: Share of a pulse spent moving, and the frames one takes, counted in animation
#: steps: the pace is a period rather than a speed, so a long wait row is crossed
#: in the same time as a short one and the pulse does not depend on how often the
#: terminal happens to repaint. The share is what the demo's pace keys scale, so
#: changing the period keeps the two phases in proportion.
MOVE_SHARE = MOVE_SECONDS / (MOVE_SECONDS + REST_SECONDS)
PULSE_FRAMES = round((MOVE_SECONDS + REST_SECONDS) / ANIMATION_SECONDS)

#: Seconds one blink of the status bar's icon takes. The icon is a small thing on
#: a line of its own, so it turns over on a period of its own — no rest to sit
#: through, unlike the waiting row it reports on.
STATUS_BLINK_SECONDS = 1.5
STATUS_BLINK_FRAMES = round(STATUS_BLINK_SECONDS / ANIMATION_SECONDS)


#: How long the effort gauge plays after a switch. It is a function of time rather
#: than of a frame count, so it is as smooth as the loop that paints it and its
#: length is one number to tune: a switch at the top of the scale is worth a moment
#: of watching, and the gauge holds the corner for this one.
EFFORT_SECONDS = 3

#: Fraction of the second the fill takes to arrive; the rest is the glow leaving.
EFFORT_FILL_SHARE = 0.8

#: Half the width, in cells, of the glow that travels over the gauge and over the
#: word. Its brightness falls off as a cosine, so it has no edge.
EFFORT_GLOW_HALF_WIDTH = 3.5

#: Cells past either end the glow travels, so it enters and leaves rather than
#: appearing on the first cell.
EFFORT_GLOW_RUNWAY = 4

#: Fractions of the second the gauge takes to arrive and to leave. Both are short
#: and the leaving one is longer: a thing that appears should be there at once, and
#: one that goes should be allowed to go, or the header jumps back to plain text.
EFFORT_FADE_IN = 0.12
EFFORT_FADE_OUT = 0.25


@dataclass(frozen=True, slots=True)
class GaugeCell:
    """One cell of the effort gauge, described without a colour.

    Attributes:
        char: The glyph: a full rule, a half rule for the leading edge, or the
            faint rail that has not been reached.
        heat: Where on the scale this cell sits, ``0`` at the cheapest level and
            ``1`` at the dearest; the colour ramp reads it.
        glow: How much of the travelling highlight is on this cell, ``0`` to ``1``.
        lit: Whether the fill has reached it; an unlit cell is rail.
    """

    char: str
    heat: float
    glow: float
    lit: bool


@dataclass(frozen=True, slots=True)
class EffortFrame:
    """One instant of the effort gauge: its cells and the word beside them.

    ``presence`` is how much of the gauge is there: it rises from nothing, holds,
    and falls back to nothing, and the painter blends every colour toward the
    resting header by what is missing, so the gauge fades in and out instead of
    appearing and vanishing between one frame and the next.
    """

    cells: tuple[GaugeCell, ...]
    word: str
    word_heat: float
    word_glow: tuple[float, ...]
    presence: float


def _glow(position: float, centre: float) -> float:
    """Return the highlight's brightness at a position: a cosine, zero past its reach."""
    distance = abs(position - centre)
    if distance >= EFFORT_GLOW_HALF_WIDTH:
        return 0.0
    return 0.5 * (1 + math.cos(math.pi * distance / EFFORT_GLOW_HALF_WIDTH))


def effort_frame(previous: str, current: str, levels: Sequence[str], *, progress: float) -> EffortFrame | None:
    """Return the effort gauge ``progress`` of the way through a switch.

    The gauge is a hairline with one cell per level. The fill eases out from the
    level being left to the level chosen, so a jump of four rungs travels four
    times as far as a nudge and a step down wipes back. Its colour is a property
    of *where* a cell sits on the scale rather than of what is being switched to:
    the cheap end is the accent, the dear end is warm, and the word beside it takes
    the heat of the level it names — so the position of the fill and the colour of
    the word say the same thing twice, and `ultra` is the one that is red.

    A soft highlight travels over the gauge and then over the word, a cosine of its
    distance rather than a window with edges, which is what keeps it from looking
    like a progress bar.

    Args:
        previous: Level the switch came from; an unknown name starts from empty.
        current: Level being reached; an unknown name answers ``None``.
        levels: The configured levels, cheapest first.
        progress: ``0`` at the start through ``1`` at the end; outside that range
            there is nothing to draw and the answer is ``None``, which is the
            caller's cue to release the frame loop.

    Returns:
        The cells and the word, or ``None`` when there is nothing to animate.
    """
    if not 0.0 <= progress < 1.0 or not levels or current not in levels:
        return None
    count = len(levels)
    target = levels.index(current)
    source = levels.index(previous) if previous in levels else -1
    arrived = 1 - (1 - min(1.0, progress / EFFORT_FILL_SHARE)) ** 3
    reach = (source + 1) + (target - source) * arrived
    span = count + 2 * EFFORT_GLOW_RUNWAY + len(current) + 1
    sweep = -EFFORT_GLOW_RUNWAY + progress * span
    last = max(1, count - 1)
    cells = []
    for index in range(count):
        fill = max(0.0, min(1.0, reach - index))
        lit = fill > 0.45
        char = "\u2501" if fill >= 1.0 else "\u2578" if lit else "\u2500"
        cells.append(GaugeCell(char, index / last, _glow(index, sweep) if lit else 0.0, lit))
    word_glow = tuple(_glow(count + 1 + offset, sweep) for offset in range(len(current)))
    presence = min(1.0, progress / EFFORT_FADE_IN, (1.0 - progress) / EFFORT_FADE_OUT)
    return EffortFrame(tuple(cells), current, target / last, word_glow, max(0.0, presence))


def move_frames() -> int:
    """Return the frames of one pulse the waiting row spends moving."""
    return max(1, round(PULSE_FRAMES * MOVE_SHARE))


def moving(frame: int) -> bool:
    """Say whether the waiting row is in the moving part of its pulse."""
    return frame % PULSE_FRAMES < move_frames()


def sweep_column(frame: int, travel: int) -> int:
    """Return the column the highlight has reached at one animation frame.

    One pass takes the moving part of the pulse, so the highlight arrives at the
    end of the label as the row rests and sets off again when it moves.

    Args:
        frame: Monotonic frame counter shared by the whole application.
        travel: Columns one whole pass takes, ends included —
            :attr:`~zettcode.tui.render.sweep.SweepSpan.travel`.
    """
    return frame % PULSE_FRAMES * max(1, travel) // move_frames()


def activity_glyph(frame: int) -> str:
    """Return the marker the status bar shows while work is in progress.

    The marker keeps one column and holds each of its two states instead of
    cycling through different symbols, which is what makes it read as an icon
    rather than as a spinner. It alternates on a period of its own, with no rest
    between blinks, because a small icon can turn over faster than the row it
    reports on; both read the same frame counter, so neither depends on how often
    the terminal repaints.

    Args:
        frame: Monotonic frame counter shared by the whole application.
    """
    return RUNNING_GLYPHS[0 if frame % STATUS_BLINK_FRAMES < STATUS_BLINK_FRAMES // 2 else 1]


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
