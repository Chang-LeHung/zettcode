"""The drawings behind ``/context``: how full the window is, and where the tokens in it went.

Like :mod:`~zettcode.app.ui.widgets.usage_charts`, everything here turns a report into *lines of
roles* and never into colours, so the page decides what a role looks like in the active theme and a
test can read the result as plain strings.

The page answers four questions, each with a different ratio, and draws each in its own way so that
none is mistaken for another:

* **How full is the window?** ``used / window``: one gauge across the page, coloured by how close the
  request is to being compacted, with a mark where that happens.
* **How much room is left?** Three numbers, each with its share of the window: what is used, what
  remains before compaction, and what remains before the window is full.
* **Where did the tokens go?** ``source / counted``: a single bar divided between the sources, and a
  row for each with the same bar on its own scale — the first shows the whole at a glance, the
  second lets a small source be read.
* **Whose number is it?** The provider reports the total and only a local tokenizer can divide it,
  and the two disagree about what a token is. So the tokenizer supplies *proportions* only: each
  source is shown as its share of the provider's total, and the rows add up to it.
"""

from __future__ import annotations

import textwrap
from collections.abc import Sequence

from zettcode.engine.extensions.context import CHARS_PER_TOKEN, SOURCES, ContextReport
from zettcode.tui import BAR_FULL
from zettcode.tui.render.text import display_width

from .usage_charts import Line, fit, meter

#: The widest the gauge and the stacked bar are drawn: past this a bar stops being read as a
#: shape, and the page would be a long strip on a wide terminal.
BAR_MAX = 72

#: The mark under the gauge where the request is summarized, and the swatch before a source.
MARK = "\u25b2"
SWATCH = "\u25a0"

#: Columns of a source's name, a token count, a share, and an item count in the rows.
NAME = 18
TOKENS = 9
SHARE = 6
ITEMS = 5

#: Where the gauge turns from calm to warm: this fraction of the way to the compaction point.
WARM = 0.75

#: A source's role, one colour for each, in the order the request is assembled.
SOURCE_ROLES = {name: f"source{index}" for index, name in enumerate(SOURCES)}

#: The sources only an assembled request carries (see ``ContextReport.partial``).
FROM_THE_REQUEST = ("Environment notes", "Tool schemas")


def percent(tokens: int, whole: int) -> str:
    """Return ``tokens`` as a share of ``whole`` with one decimal, or a dash for an empty whole."""
    return "\u2014" if whole <= 0 else f"{tokens / whole * 100:.1f}%"


def gauge_role(used: int, limit: int) -> str:
    """Return how alarming ``used`` is against ``limit``: calm, warm from three quarters, hot at it."""
    if used >= limit:
        return "gauge_hot"
    return "gauge_warm" if used >= limit * WARM else "gauge_calm"


def allocate(values: Sequence[int], cells: int) -> list[int]:
    """Divide ``cells`` between ``values`` in proportion, so the parts add up to exactly ``cells``.

    Rounding each part alone leaves the bar a cell short or long. This gives every part its whole
    cells, hands the remainder to the parts that lost most to rounding, and lets a part that is
    above zero keep one cell however small it is: a source that is there should be seen. Those
    cells are paid for by the largest parts.
    """
    total = sum(values)
    if cells <= 0 or total <= 0:
        return [0] * len(values)
    exact = [value * cells / total for value in values]
    given = [max(1, int(share)) if value > 0 else 0 for share, value in zip(exact, values, strict=True)]
    while sum(given) < cells:
        given[max(range(len(values)), key=lambda index: exact[index] - given[index])] += 1
    while sum(given) > cells:
        payers = [index for index, count in enumerate(given) if count > (1 if values[index] > 0 else 0)]
        if not payers:
            break
        given[max(payers, key=lambda index: given[index] - exact[index])] -= 1
    return given


def _fitted(width: int, candidates: Sequence[Line]) -> Line:
    """Return the first of ``candidates`` that fits ``width`` columns, else the last, which is the shortest."""
    for line in candidates:
        if display_width("".join(text for text, _ in line)) <= width:
            return line
    return candidates[-1]


def window_lines(report: ContextReport, trigger: int | None, width: int) -> list[Line]:
    """Return the gauge, the mark where compaction starts, and the three numbers under it.

    Args:
        report: What the request carries.
        trigger: Tokens at which a request is compacted, or ``None`` when it never is; the gauge
            is coloured by how near that is, and the window itself when there is no such point.
        width: Columns the page has.
    """
    cells = max(1, min(width, BAR_MAX))
    used = report.used
    limit = min(trigger, report.window) if trigger else report.window
    role = gauge_role(used, limit)
    lines: list[Line] = [
        _fitted(
            width,
            [
                [
                    ("Window", "heading"),
                    (f"   {used:,} / {report.window:,} tokens", "text"),
                    (f"   {percent(used, report.window)} full", role),
                ],
                [
                    ("Window", "heading"),
                    (f"   {used:,} / {report.window:,}", "text"),
                    (f"   {percent(used, report.window)}", role),
                ],
                [(f"{used:,} / {report.window:,}", "text"), (f"  {percent(used, report.window)}", role)],
            ],
        ),
        meter(used, report.window, cells, role),
    ]
    if trigger:
        position = min(cells - 1, max(0, round(limit / report.window * cells) - 1))
        share = percent(limit, report.window)
        for label in (f"compacts at {limit:,} tokens ({share})", f"compacts at {limit:,}", share):
            reach = display_width(label)
            if position + 2 + reach <= cells:
                lines.append([(" " * position + MARK + " ", "muted"), (label, "muted")])
                break
            if reach + 2 <= position + 1:
                lines.append([(" " * (position + 1 - reach - 2), "muted"), (label + " ", "muted"), (MARK, "muted")])
                break
        else:
            lines.append([(" " * position + MARK, "muted")])
    lines.append([])
    numbers = [("Used", used, role)]
    if trigger:
        numbers.append(("Until compaction", max(0, limit - used), "text"))
    numbers.append(("Free in window", max(0, report.window - used), "text"))
    digits = len(f"{report.window:,}")
    names = max(4, min(17, width - digits - 2 - SHARE - 1))
    for label, tokens, colour in numbers:
        lines.append(
            [
                (fit(label, names) + " ", "muted"),
                (f"{tokens:>{digits},}", "text"),
                (f"  {percent(tokens, report.window):>{SHARE}}", colour if label == "Used" else "muted"),
            ]
        )
    return lines


def divides_the_total(report: ContextReport) -> bool:
    """Return whether the rows are shares of the provider's total, and so add up to it.

    That needs every source to be there. The provider's number is for the whole request, tool schemas
    and environment notes included; while those are unknown (``partial``) dividing it between the
    sources that are known would hand their tokens to rows that did not send them.
    """
    return report.from_provider and not report.partial and report.measured > 0


def tokens_by_source(report: ContextReport) -> dict[str, int]:
    """Return the tokens each source takes, in the units of the total the page reports.

    The local count is only good for proportions: it uses one tokenizer, and the model bills by
    its own. So when the provider reported the request's size, each source gets its share of
    *that* number, divided so the rows add up to it exactly; without one, or while a source is
    still unknown, the local counts are all there is and are shown as counted.
    """
    shares = report.shares
    if not divides_the_total(report):
        return {share.name: share.tokens for share in shares}
    parts = allocate([share.tokens for share in shares], report.used)
    return {share.name: count for share, count in zip(shares, parts, strict=True)}


def makeup_lines(report: ContextReport, width: int) -> list[Line]:
    """Return the bar divided between the sources, and a row for each source under it."""
    cells = max(1, min(width, BAR_MAX))
    measured = report.measured
    tokens = tokens_by_source(report)
    present = [share for share in report.shares if share.tokens > 0]
    total = report.used if divides_the_total(report) else report.measured
    lines: list[Line] = [
        _fitted(
            width,
            [
                [("Where it goes", "heading"), (f"   how the {total:,} tokens divide between sources", "muted")],
                [("Where it goes", "heading"), (f"   {total:,} tokens", "muted")],
                [("Where it goes", "heading")],
            ],
        ),
        [
            (BAR_FULL * count, SOURCE_ROLES[share.name])
            for share, count in zip(present, allocate([share.tokens for share in present], cells), strict=True)
            if count
        ]
        or [(" " * cells, "track")],
        [],
    ]
    items_shown = width >= 44
    others = 2 + 2 + TOKENS + 2 + SHARE + (2 + ITEMS if items_shown else 0)
    name_width = max(8, min(NAME, width - others))
    track = min(32, width - (others + name_width + 2 + 2))
    track = track if track >= 6 else 0
    head = " " * 2 + fit("Source", name_width) + "  "
    head += (" " * (track + 2)) if track else ""
    head += fit("Tokens", TOKENS, right=True) + "  " + fit("Share", SHARE, right=True)
    head += "  " + fit("Items", ITEMS, right=True) if items_shown else ""
    lines.append([(head, "muted")])
    counted = {share.name: share for share in report.shares}
    for name in SOURCES:
        share = counted.get(name)
        if share is None and not (report.partial and name in FROM_THE_REQUEST):
            continue
        role = SOURCE_ROLES[name]
        line: Line = [(SWATCH if share is not None else "\u00b7", role if share is not None else "muted")]
        line.append((" ", "text"))
        line.append((fit(name, name_width), "text" if share is not None else "muted"))
        line.append(("  ", "text"))
        if share is None:
            if track:
                line.append((" " * (track + 2), "text"))
            line.append((fit("pending", TOKENS, right=True), "muted"))
            line.append(("  " + fit("\u2014", SHARE, right=True), "muted"))
        else:
            if track:
                line.extend(meter(share.tokens, measured, track, role))
                line.append(("  ", "text"))
            line.append((f"{tokens[name]:>{TOKENS},}", "text"))
            line.append((f"  {percent(share.tokens, measured):>{SHARE}}", "muted"))
            if items_shown:
                line.append((f"  {share.items:>{ITEMS}}", "muted"))
        lines.append(line)
    return lines


def note_lines(report: ContextReport, width: int = BAR_MAX) -> list[Line]:
    """Return what the numbers are and are not: whose total this is, and whether the split is an estimate.

    The counter's name is not said: a reader cannot act on it. What they can use is whose total this
    is and that the division of it between sources is worked out locally, which is why it is a
    proportion and not a bill; and, when the counts are a rule of thumb, that they are.
    """
    if report.from_provider and not report.partial:
        words = (
            "Total from the provider, which counts what it bills. "
            "Each source gets its share of that total, worked out from a local count."
        )
    elif report.from_provider:
        words = (
            "Total from the provider, which counts what it bills. The rows are counted here and do not "
            "add up to it: the environment notes and tool schemas are in the total but cannot be seen "
            "until a request has been sent."
        )
    elif report.partial:
        words = (
            "Counted here; the provider has not reported this request yet. The environment notes and "
            "tool schemas are not counted until a request has been sent."
        )
    else:
        words = "Counted here; the provider has not reported this request yet."
    if report.estimated:
        words += f" Counts are estimates, about {CHARS_PER_TOKEN} characters to a token."
    return [[(row, "muted")] for row in textwrap.wrap(words, max(10, width))]


def context_lines(report: ContextReport, trigger: int | None, width: int) -> list[Line]:
    """Return the whole page body: the window, where the tokens went, and what to make of them."""
    lines = window_lines(report, trigger, width)
    lines.extend(([], *makeup_lines(report, width), [], *note_lines(report, width)))
    return lines
