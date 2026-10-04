"""The panel ``/context`` opens: what the next request spends its window on."""

from __future__ import annotations

from ....tui import ListItem, ListPage
from ...agent.context import ContextReport


def format_share(percent: float) -> str:
    """Format the heading's share, rounded to whole percent.

    A source that takes a fraction of a percent is still worth showing: it is
    the difference between "nothing here" and "a little", and the rows carry the
    decimal the heading rounds away.
    """
    return f"{percent:.0f}%" if percent >= 10 else f"{percent:.1f}%"


class ContextPage(ListPage):
    """One row per source, with its tokens and share of the budget.

    Shape::

        Context  25,926 / 128,000 tokens  (20%)
          System prompt       0.2%  ( 1)     <- this application's instructions
          Environment notes   0.6%  ( 2)     <- cwd, tool snippets, guidelines
          Tool schemas        1.2%  ( 9)     <- the tools offered
          User messages       0.0%  ( 3)     <- what was typed
          Assistant messages  2.4%  (12)     <- answers and reasoning
          Tool output        16.0%  (17)     <- command and file results
        tiktoken cl100k_base \u00b7 esc back

    Rows carry a share and a count rather than a token count: the share is what
    tells you where the budget goes, and the exact tokens change with every
    message. Both columns are padded so the numbers line up down the page, and
    the title carries the total so the rows read as a breakdown. The footer
    names the counter that produced the numbers: tiktoken when its encoding was
    available, a character estimate when it was not.
    """

    def __init__(self, report: ContextReport, *, on_cancel=None) -> None:
        """Map every source the request used to one row.

        Args:
            report: Breakdown to show, as produced by the context extension.
            on_cancel: Called when the user presses Escape.
        """
        title = f"Context  {report.used:,} / {report.window:,} tokens  ({format_share(report.percent(report.used))})"
        counts = [f"({share.items})" for share in report.shares]
        width = max((len(count) for count in counts), default=0)
        items = [
            ListItem(
                share.name,
                share.name,
                f"{report.percent(share.tokens):>5.1f}%  {count:>{width}}",
            )
            for share, count in zip(report.shares, counts, strict=True)
        ]
        super().__init__(
            items,
            title=title,
            footer=" \u00b7 ".join(_footer(report)),
            on_cancel=on_cancel,
            visible_rows=max(1, len(items)),
        )


def _footer(report: ContextReport) -> tuple[str, ...]:
    """Return the footer's parts: the counter, any caveat, and the key hint."""
    parts = [report.measured_by]
    if report.partial:
        parts.append("notes and tools pending")
    parts.append("esc back")
    return tuple(parts)
