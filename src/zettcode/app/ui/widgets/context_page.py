"""The panel ``/context`` opens: what the next request spends its window on."""

from __future__ import annotations

from ....tui import ListItem, ListPage
from ...agent.context import ContextReport


class ContextPage(ListPage):
    """One row per source, with its share of the context and a count.

    Shape::

        Context  25,926 / 128,000 tokens
          Source               Share    Count
          System prompt        1.0%    ( 1)     <- this application's instructions
          Environment notes    2.9%    ( 2)     <- cwd, tool snippets, guidelines
          Tool schemas         5.9%    ( 9)     <- the tools offered
          User messages        0.1%    ( 3)     <- what was typed
          Assistant messages  12.0%    (12)     <- answers and reasoning
          Tool output         78.1%    (17)     <- command and file results
        tiktoken cl100k_base \u00b7 esc back

    The percentage is a share of the context in use, not of the window: rows
    answer where the tokens went, and the title carries the absolute total
    against the model's window. A disabled heading row names the columns, and
    because the list aligns it like any other row its words sit exactly over
    the numbers below them; the count column is as wide as the word, so the
    heading fits the column it names. The footer names the counter that
    produced the numbers: tiktoken when its encoding was available, a character
    estimate when it was not.
    """

    def __init__(self, report: ContextReport, *, on_cancel=None) -> None:
        """Map every source the request used to one row.

        Args:
            report: Breakdown to show, as produced by the context extension.
            on_cancel: Called when the user presses Escape.
        """
        title = f"Context  {report.used:,} / {report.window:,} tokens"
        counts = [f"({share.items})" for share in report.shares]
        width = max((len(count) for count in counts), default=0)
        width = max(width, len("Count"))
        head = ListItem(None, "Source", f"{'Share':>6}    {'Count':>{width}}", disabled=True)
        items = [
            ListItem(
                share.name,
                share.name,
                f"{report.share(share.tokens):>5.1f}%    {count:>{width}}",
            )
            for share, count in zip(report.shares, counts, strict=True)
        ]
        super().__init__(
            [head, *items],
            title=title,
            footer=" \u00b7 ".join(_footer(report)),
            on_cancel=on_cancel,
            selected=1,
            visible_rows=max(1, len(items) + 1),
        )


def _footer(report: ContextReport) -> tuple[str, ...]:
    """Return the footer's parts: the counter, any caveat, and the key hint."""
    parts = [report.measured_by]
    if report.partial:
        parts.append("notes and tools pending")
    parts.append("esc back")
    return tuple(parts)
