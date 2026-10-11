"""The panel ``/context`` opens: what the next request spends its window on."""

from __future__ import annotations

from pathlib import Path

from ....tui import SEPARATOR, ListItem, ListPage
from ...agent.context import SOURCES, ContextReport
from ..labels import compact_path

#: The sources only an assembled request carries: the notes an extension appends
#: and the tool schemas the runtime offers. A report of a session rebuilt from the
#: store has neither until this process has sent one, so the page gives each a row
#: that says ``pending`` — in the list, where a narrow panel still shows it, rather
#: than in the footer, whose tail is the first thing a narrow panel loses.
FROM_THE_REQUEST = ("Environment notes", "Tool schemas")

#: What a row says when its source cannot be measured yet.
PENDING = "pending"

#: The share column of such a row: an em dash, held as a constant because Python
#: 3.10 has no escape sequences inside an f-string's expression.
UNKNOWN = "\u2014"


class ContextPage(ListPage):
    """One row per source, with its share of the context and a count.

    Shape::

        Context  25,926 / 128,000 tokens
        ~/.zettcode/sessions/-Users-me-projects-api/0192f0a1-…/conversation.jsonl
          Source               Share    Count
          Environment notes      —   pending    <- only a request has these
          System prompt        1.0%    ( 1)     <- this application's instructions
          Environment notes    2.9%    ( 2)     <- cwd, tool snippets, guidelines
          Tool schemas         5.9%    ( 9)     <- the tools offered
          User messages        0.1%    ( 3)     <- what was typed
          Assistant messages  12.0%    (12)     <- answers and reasoning
          Tool output         78.1%    (17)     <- command and file results
        tiktoken cl100k_base \u00b7 esc back

    The percentage is a share of the context in use, not of the window: rows
    answer where the tokens went, and the title carries the absolute total
    against the model's window. That total is the provider's own count of the
    request whenever it made one, because it counts what it bills; the shares
    under it are the tokenizer's, because no provider breaks a request down by
    source — so the footer names both. A session restored from the store has no
    provider count for the dialogue it was rebuilt from, and both are the
    tokenizer's until the next answer. Under the title sits the file this session is
    stored in — the conversation itself, on disk, under the store root — which
    is what a reader reaches for when the numbers ask for a closer look. A
    disabled heading row names the columns, and because the list aligns it like
    any other row its words sit exactly over the numbers below them; the count
    column is as wide as the word, so the heading fits the column it names. The
    footer names the counter that produced the numbers: tiktoken when its
    encoding was available, a character estimate when it was not.

    A report measured before this process has sent a request — a session resumed
    from the store — cannot know the two sources only a request carries, and the
    list says so in their place. The alternative, leaving the rows out and adding a
    caveat to the footer, hides the difference between a fresh report and an
    assembled one exactly where a narrow panel cuts the footer off.
    """

    def __init__(self, report: ContextReport, *, path: Path | None = None, on_cancel=None) -> None:
        """Map every source the request used to one row.

        Args:
            report: Breakdown to show, as produced by the context extension.
            path: File this session is stored in. The home directory collapses to
                ``~``; a line too long for the panel is cut by the page rather
                than shortened here, so a narrow terminal loses the end of the
                path and not which file it named.
            on_cancel: Called when the user presses Escape.
        """
        title = f"Context  {report.used:,} / {report.window:,} tokens"
        measured = {share.name: share for share in report.shares}
        widths = [len(f"({share.items})") for share in report.shares]
        width = max([*widths, len("Count"), len(PENDING)])
        head = ListItem(None, "Source", f"{'Share':>6}    {'Count':>{width}}", disabled=True)
        items: list[ListItem] = []
        for name in SOURCES:
            share = measured.get(name)
            if share is not None:
                count = f"({share.items})"
                items.append(ListItem(name, name, f"{report.share(share.tokens):>5.1f}%    {count:>{width}}"))
            elif report.partial and name in FROM_THE_REQUEST:
                items.append(ListItem(name, name, f"{UNKNOWN:>6}    {PENDING:>{width}}"))
        super().__init__(
            [head, *items],
            title=title,
            subtitle=compact_path(path, limit=None) if path is not None else None,
            footer=f" {SEPARATOR} ".join(_footer(report)),
            on_cancel=on_cancel,
            selected=1,
            visible_rows=max(1, len(items) + 1),
        )


def _footer(report: ContextReport) -> tuple[str, ...]:
    """Return the footer's parts: what measured what, and the key hint.

    What is still unknown is not here: those sources have a row of their own in
    the list, which is the one place a narrow panel does not cut off.
    """
    if report.from_provider:
        # Two sources in one panel: say which is which rather than let the reader
        # assume the total and the shares came from the same counter.
        parts = [f"{report.measured_by} shares", "provider total"]
    else:
        parts = [report.measured_by]
    parts.append("esc back")
    return tuple(parts)
