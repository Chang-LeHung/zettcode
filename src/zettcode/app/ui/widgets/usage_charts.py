"""The drawings behind ``/usage``: numbers, bars, and the calendar grid.

Everything here turns a :class:`~zettcode.app.agent.storage.ledger.Ledger` into *lines of
roles* — a line is a list of ``(text, role)`` pairs and a role is a name such as ``"input"``
or ``"heat3"`` — and never into colours. The page that owns a terminal decides what a role
looks like in the active theme, which keeps these functions testable as plain strings and
lets a light theme and a dark one share them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from zettcode.app.agent.storage.ledger import Ledger, SessionUsage, Tally
from zettcode.tui import BAR_EMPTY, ELLIPSIS
from zettcode.tui.render.text import display_width, truncate

#: One drawn line: text paired with the role that colours it.
Line = list[tuple[str, str]]

#: The units a count is written in above a thousand.
UNITS = "KMBT"

#: The eight steps of a block bar, from one eighth of a cell to a whole one.
EIGHTHS = " \u258f\u258e\u258d\u258c\u258b\u258a\u2589\u2588"

#: Month names, written out here so a locale cannot change the width of a label.
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

#: Columns a token count takes in the sessions list: ``1.46B`` with room for a thousands unit.
NUMBER = 7

#: Day names in the order the calendar's rows run: Sunday first, as GitHub draws it.
WEEKDAYS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

#: A day of the calendar: a square and the gap that follows it, two cells wide in all.
CELL = "\u25a0 "

#: Columns the weekday names take at the left of the calendar.
LABEL_COLUMNS = 4

#: Weeks the calendar shows at most, which is a year and a week as GitHub's does.
MAX_WEEKS = 53

#: How many shades a day can have: none, and four of increasing use.
LEVELS = 5


def compact(count: int) -> str:
    """Return a count in three significant digits with a unit: ``12.3K``, ``1.46B``.

    A count under a thousand is written whole, because ``412`` is exact and ``0.41K`` is not
    shorter.
    """
    if abs(count) < 1000:
        return str(count)
    value = count / 1000
    index = 0
    while abs(value) >= 999.5 and index < len(UNITS) - 1:
        value /= 1000
        index += 1
    digits = 2 if abs(value) < 9.995 else 1 if abs(value) < 99.95 else 0
    return f"{value:.{digits}f}{UNITS[index]}"


def bar(value: int, maximum: int, width: int, *, curve: float = 1.0) -> str:
    """Return the filled part of a bar ``width`` cells wide: whole blocks and one partial.

    A value that is above zero draws at least an eighth of a cell, so a small share is
    still seen next to a large one instead of vanishing into the track. ``curve`` raises the
    share to a power: ``0.5`` is a square-root scale, which keeps a list readable when one
    row is a thousand times the others.
    """
    if width <= 0 or maximum <= 0 or value <= 0:
        return ""
    share = min(1.0, value / maximum) ** curve
    eighths = max(1, min(width * 8, round(share * width * 8)))
    whole, part = divmod(eighths, 8)
    return EIGHTHS[8] * whole + (EIGHTHS[part] if part else "")


def meter(value: int, maximum: int, width: int, role: str, *, curve: float = 1.0) -> Line:
    """Return a bar and the empty track after it, so every bar is the same width."""
    filled = bar(value, maximum, width, curve=curve)
    track = max(0, width - display_width(filled))
    return [(filled, role), (BAR_EMPTY * track, "track")]


def fit(text: str, width: int, *, right: bool = False) -> str:
    """Return ``text`` cut or padded to exactly ``width`` columns."""
    text = truncate(text, width, ellipsis=ELLIPSIS) if display_width(text) > width else text
    padding = " " * max(0, width - display_width(text))
    return padding + text if right else text + padding


def percent(share: float | None) -> str:
    """Return a share as a percent to two decimals, or a dash when there was nothing to share."""
    return "\u2014" if share is None else f"{share * 100:.2f}%"


def summary(ledger: Ledger) -> Line:
    """Return the one line that totals the workspace."""
    total = ledger.total
    return [
        ("All models", "heading"),
        (f"   {compact(total.total)} tokens", "text"),
        (f"   in {compact(total.input_tokens)}", "input"),
        (f"   out {compact(total.output_tokens)}", "output"),
        (f"   cached {percent(total.cache_share)}", "muted"),
        (f"   {total.requests:,} requests \u00b7 {len(ledger.sessions)} sessions", "muted"),
    ]


def models_tab(ledger: Ledger, width: int) -> tuple[list[Line], list[Line]]:
    """Return the ``Models`` tab: a heading, and a pair of bars for each model.

    Input bars are scaled against the model that sent the most and output bars against
    the one that generated the most, separately, because a model is read for how its two
    numbers compare with the others' and not with each other: output is a small fraction of
    input for every model, and one shared scale would draw it as nothing.
    """
    head: list[Line] = [summary(ledger)]
    if not ledger.models:
        return head, [[("No model replies have been recorded in this workspace yet.", "muted")]]
    ranked = sorted(ledger.models.items(), key=lambda item: (-item[1].total, item[0]))
    most_in = max(tally.input_tokens for _, tally in ranked)
    most_out = max(tally.output_tokens for _, tally in ranked)
    track = max(8, min(48, width - 36))
    body: list[Line] = [
        [("Bars compare each model with the largest one, input and output on their own scales.", "muted")]
    ]
    for name, tally in ranked:
        body.append([])
        body.append(
            [
                (truncate(name, max(8, width - 32)), "heading"),
                (f"   {compact(tally.total)} tokens \u00b7 {tally.requests:,} requests", "muted"),
            ]
        )
        body.append(
            [("  input   ", "muted"), *meter(tally.input_tokens, most_in, track, "input")]
            + [
                (f"  {compact(tally.input_tokens):>6}", "text"),
                (f"  {percent(tally.cache_share)} cached", "muted"),
            ]
        )
        body.append(
            [("  output  ", "muted"), *meter(tally.output_tokens, most_out, track, "output")]
            + [
                (f"  {compact(tally.output_tokens):>6}", "text"),
                (f"  {compact(tally.reasoning_tokens)} reasoning", "muted"),
            ]
        )
    return head, body


def sessions_tab(ledger: Ledger, width: int) -> tuple[list[Line], list[Line]]:
    """Return the ``Sessions`` tab: one row for each session, last changed first.

    A row says when the session began and when it last changed, what it is called, its input
    and output as bars, and the share of that input the provider served from its cache. A
    terminal too narrow for both times keeps the last change, which is what the order is; one
    too narrow for bars gets the numbers alone, because a bar of three cells is not a chart.
    """
    head: list[Line] = [summary(ledger)]
    if not ledger.sessions:
        return head, [[("This workspace has no sessions yet.", "muted")]]
    most_in = max(row.tally.input_tokens for row in ledger.sessions)
    most_out = max(row.tally.output_tokens for row in ledger.sessions)
    track, title_room = session_columns(width)
    stamp, count = stamp_columns(width)
    column = track + 1 + NUMBER if track else NUMBER
    heading = (fit("Began", stamp) + "  " if count == 2 else "") + fit("Updated", stamp) + "  "
    heading += f"{fit('Title', title_room)}  "
    for name in ("Input", "Output"):
        heading += fit(name, column, right=not track) + "  "
    share = shows_share(width)
    if share:
        heading += fit("Cached", SHARE, right=not track) + "  "
    head.append([(heading.rstrip(), "muted")])
    if track:
        head.append([("Bars use a square-root scale against the busiest session, so small ones still show.", "muted")])
    body: list[Line] = []
    for row in ledger.sessions:
        body.append(_session_line(row, title_room, track, most_in, most_out, stamp, count, share))
    return head, body


#: Columns a timestamp takes when the month, day, hour and minute are all written.
STAMP = 12


def stamp_columns(width: int) -> tuple[int, int]:
    """Return how wide a timestamp is and how many the page has room for.

    Two times (began, last changed) in full need 28 columns; below that they lose the clock, and
    below 52 columns only the last change is kept — the order is by it, and a row is still a row.
    """
    if width >= 76:
        return STAMP, 2
    if width >= 52:
        return 8, 2
    return 8, 1


#: Columns a cache-hit share takes: ``100.00%``.
SHARE = 7


def shows_share(width: int) -> bool:
    """Return whether the cache column fits beside a readable title; below that the two counts stay."""
    stamp, count = stamp_columns(width)
    prefix = count * (stamp + 2)
    return width - (prefix + 2 + 2 * (NUMBER + 2) + SHARE + 2) >= 10


def session_columns(width: int) -> tuple[int, int]:
    """Return the width of a session's bars and of its title for a page ``width`` columns wide.

    The bars give way before the title does: a title under 18 columns is not a title, so the
    bars shrink and then go; then the cache column goes, and past that the title itself shrinks,
    so a row never runs past the page and takes the counts off its right edge.
    """
    stamp, count = stamp_columns(width)
    prefix = count * (stamp + 2)
    extra = SHARE + 2 if shows_share(width) else 0
    track = 0
    for track in (14, 10, 6, 0):
        column = track + 1 + NUMBER if track else NUMBER
        if width - (prefix + 2 + 2 * (column + 2) + extra) >= 18:
            break
    column = track + 1 + NUMBER if track else NUMBER
    return track, max(0, width - (prefix + 2 + 2 * (column + 2) + extra))


def _stamp(moment: datetime, width: int) -> str:
    """Return one time as ``Oct 14 09:12``, ``Oct 14``, or the date padded to the column."""
    label = f"{MONTHS[moment.month - 1]} {moment.day:>2}"
    if width > 8:
        label += f" {moment.hour:02}:{moment.minute:02}"
    return f"{label:<{width}}"


def _session_line(
    row: SessionUsage, title_room: int, track: int, most_in: int, most_out: int, stamp: int, count: int, share: bool
) -> Line:
    """Return one session's row for the ``Sessions`` tab."""
    began = row.started.astimezone()
    updated = row.updated.astimezone()
    title = row.title or "(untitled)"
    line: Line = []
    if count == 2:
        line.extend(((f"{_stamp(began, stamp)}", "muted"), ("  ", "text")))
    line.extend(((f"{_stamp(updated, stamp)}", "muted"), ("  ", "text")))
    line.extend(
        (
            (fit(title, title_room), "text" if row.title else "muted"),
            ("  ", "text"),
        )
    )
    for value, most, role in (
        (row.tally.input_tokens, most_in, "input"),
        (row.tally.output_tokens, most_out, "output"),
    ):
        if track:
            line.extend(meter(value, most, track, role, curve=0.5))
            line.append((" ", "text"))
        line.append((f"{compact(value):>{NUMBER}}", "text" if value else "muted"))
        line.append(("  ", "text"))
    share_value = row.tally.cache_share
    if share:
        line.append((f"{percent(share_value):>{SHARE}}", "text" if share_value is not None else "muted"))
        line.append(("  ", "text"))
    return line


def week_start(day: date) -> date:
    """Return the Sunday that opens the week ``day`` falls in."""
    return day - timedelta(days=(day.weekday() + 1) % 7)


def weeks_that_fit(width: int) -> int:
    """Return how many weekly columns a page ``width`` columns wide can draw."""
    return max(1, min(MAX_WEEKS, (width - LABEL_COLUMNS) // len(CELL)))


def first_day(today: date, weeks: int) -> date:
    """Return the first day the calendar draws when it ends on the week of ``today``."""
    return week_start(today) - timedelta(weeks=weeks - 1)


def levels(days: dict[date, Tally]) -> dict[date, int]:
    """Return a shade from 1 to 4 for each day something was spent.

    The cut points are the quartiles of the days that were used, as GitHub's are, so the
    palette is spread over a person's own range: someone who spends a million a day and
    someone who spends a thousand both get a graph with dark days and pale ones.
    """
    totals = sorted(tally.total for tally in days.values() if tally.total > 0)
    if not totals:
        return {}
    cuts = [totals[min(len(totals) - 1, (len(totals) * numerator) // 4)] for numerator in (1, 2, 3)]
    shades: dict[date, int] = {}
    for day, tally in days.items():
        if tally.total <= 0:
            continue
        shades[day] = 1 + sum(tally.total > cut for cut in cuts)
    return shades


def streaks(days: dict[date, Tally], today: date) -> tuple[int, int]:
    """Return the longest run of used days and the run that reaches today.

    A run still counts if today has not been used yet but yesterday was, so a streak is not
    reported as broken at midnight, before there has been a chance to continue it.
    """
    used = sorted(day for day, tally in days.items() if tally.total > 0)
    longest = run = 0
    previous: date | None = None
    for day in used:
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    current = 0
    cursor = today if today in days and days[today].total > 0 else today - timedelta(days=1)
    while cursor in days and days[cursor].total > 0:
        current += 1
        cursor -= timedelta(days=1)
    return longest, current


def month_labels(start: date, weeks: int) -> dict[int, str]:
    """Return which column carries which month's name.

    A month is named over the first column that holds its 1st, and the first column is named
    too, so a calendar that opens mid-month still says which month it is. A name is three
    letters and takes two columns, so a month that begins one column after another's is left
    unnamed rather than printed over it; when that other is the opening partial month, it is
    the opening one that gives way, as on GitHub's graph.
    """
    names: dict[int, str] = {}
    free = 0
    for column in range(weeks):
        sunday = start + timedelta(weeks=column)
        first = next((day for day in (sunday + timedelta(days=n) for n in range(7)) if day.day == 1), None)
        month = first.month if first is not None else sunday.month if column == 0 else None
        if month is not None and column >= free:
            names[column] = MONTHS[month - 1]
            free = column + 2
        elif month is not None and column == 1 and 0 in names:
            del names[0]
            names[column] = MONTHS[month - 1]
            free = column + 2
    return names


def calendar_tab(ledger: Ledger, width: int, today: date, selected: date) -> tuple[list[Line], list[Line], date, int]:
    """Return the ``Calendar`` tab, the first day it draws, and how many weeks it spans.

    Shape::

        Oct                   Nov
        Sun  ■ ■ ■ ■ ■ ■ ■ ■ ■ ■
        Mon  ■ ■ ■ ■ ■ ■ ■ ■ ■ ■     <- a week is a column, a day is a square
        ...
    """
    weeks = weeks_that_fit(width)
    start = first_day(today, weeks)
    shades = levels(ledger.days)
    labels = [" "] * (weeks * len(CELL))
    for column, name in month_labels(start, weeks).items():
        labels[column * len(CELL) : column * len(CELL) + len(name)] = name
    months: Line = [(" " * LABEL_COLUMNS, "text"), ("".join(labels), "muted")]
    body: list[Line] = [months]
    for row in range(7):
        name = WEEKDAYS[row] if row in (1, 3, 5) else ""
        line: Line = [(fit(name, LABEL_COLUMNS), "muted")]
        for column in range(weeks):
            day = start + timedelta(weeks=column, days=row)
            if day > today:
                line.append((" " * len(CELL), "text"))
            else:
                role = f"heat{shades.get(day, 0)}"
                line.append((CELL, f"{role}*" if day == selected else role))
        body.append(line)
    body.append([])
    body.append(_legend())
    body.append([])
    body.extend(_facts(ledger, today, selected))
    head: list[Line] = [summary(ledger)]
    return head, body, start, weeks


def _legend() -> Line:
    """Return the key to the five shades."""
    line: Line = [(" " * LABEL_COLUMNS + "Less ", "muted")]
    line.extend((CELL, f"heat{level}") for level in range(LEVELS))
    line.append(("More", "muted"))
    return line


def _facts(ledger: Ledger, today: date, selected: date) -> list[Line]:
    """Return the lines under the calendar: the chosen day, and the streaks."""
    tally = ledger.days.get(selected)
    name = f"{WEEKDAYS[(selected.weekday() + 1) % 7]} {selected.day} {MONTHS[selected.month - 1]} {selected.year}"
    if tally is None or tally.total == 0:
        chosen: Line = [(name, "heading"), ("   nothing spent", "muted")]
    else:
        chosen = [
            (name, "heading"),
            (f"   {compact(tally.total)} tokens", "text"),
            (f"   in {compact(tally.input_tokens)}", "input"),
            (f"   out {compact(tally.output_tokens)}", "output"),
            (f"   {tally.requests:,} requests", "muted"),
        ]
    lines: list[Line] = [chosen]
    if ledger.days:
        busiest = max(ledger.days.items(), key=lambda item: (item[1].total, item[0]))
        longest, current = streaks(ledger.days, today)
        active = sum(1 for tally in ledger.days.values() if tally.total > 0)
        lines.append(
            [
                (
                    f"{active} active days \u00b7 longest streak {longest} \u00b7 current streak {current}"
                    f" \u00b7 busiest {busiest[0].day} {MONTHS[busiest[0].month - 1]} {busiest[0].year}"
                    f" ({compact(busiest[1].total)})",
                    "muted",
                )
            ]
        )
    return lines


def line_width(line: Sequence[tuple[str, str]]) -> int:
    """Return the columns a line takes."""
    return sum(display_width(text) for text, _ in line)
