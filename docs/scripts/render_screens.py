"""Render the screens the user guide shows, as SVG, from the real widgets.

Run from the repository root with ``uv run python docs/scripts/render_screens.py``.

Nothing is drawn by hand: each picture is the actual ``/usage`` or ``/context`` page, laid out and painted by the
code the program runs, on sample data, and written as the cells it painted. No model is started and no network is
used; every session file stays in a temporary directory.

The sample data hangs together on purpose, because the guide explains the numbers with it. The usage ledger is
built from a table of replies, one row for a day of one session, and every total on the page is a sum of those
rows: the models add up to the sessions, the sessions to the days, and all three to the line at the top. Times are
written without a time zone so the page shows the same clock on every machine.

The pictures are checked into ``docs/public/screens`` and a test fails when they no longer match the widgets.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath

from render_terminal import preview_plugins, svg

from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.extensions.context import ContextReport, ContextShare
from zettcode.app.agent.runtime import ZettCodeEngine
from zettcode.app.agent.storage.ledger import Ledger, SessionUsage, Tally
from zettcode.app.ui.app import ZettCodeApp
from zettcode.app.ui.shell import PAGE_SCREEN
from zettcode.app.ui.widgets import ContextPage, UsagePage
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.plugins.loader import load_plugins
from zettcode.tui import DARK, Canvas, Screen

#: The page the documentation shows is the dark palette on the same background the home page's picture uses.
THEME = replace(DARK, background="#232a2e")

#: The last day of the usage calendar, and the project the usage page says it is about.
TODAY = date(2026, 10, 17)
WORKSPACE = "~/projects/api"

OUTPUT = Path("docs/public/screens")


# -- the usage ledger --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Reply:
    """What one session spent on one day: the model it ran on, and the counters a provider reports.

    Attributes:
        day: The calendar day, as an offset in days before :data:`TODAY`.
        hour: The hour it happened, which is what the session list shows beside the date.
        session: Which session it belongs to.
        model: The model that answered.
        requests: Model calls that day.
        input: Tokens sent, cache reads included.
        output: Tokens generated, reasoning included.
        cached: The part of ``input`` the provider served from its cache.
        reasoning: The part of ``output`` that was reasoning.
    """

    day: int
    hour: int
    session: str
    model: str
    requests: int
    input: int
    output: int
    cached: int
    reasoning: int


TITLES = {
    "loader": "Refactor the config loader",
    "pages": "Pagination for /users",
    "parser": "Fix the parser crash",
}

REPLIES = (
    # A long session on one model, worked on over three weeks in short sittings.
    Reply(53, 10, "loader", "gpt-5-mini", 3, 150_000, 9_000, 52_000, 3_000),
    Reply(52, 14, "loader", "gpt-5-mini", 5, 310_000, 16_000, 190_000, 6_000),
    Reply(51, 11, "loader", "gpt-5-mini", 2, 120_000, 6_000, 84_000, 2_000),
    Reply(45, 15, "loader", "gpt-5-mini", 4, 260_000, 14_000, 164_000, 5_000),
    Reply(44, 9, "loader", "gpt-5-mini", 1, 70_000, 3_000, 51_000, 1_000),
    Reply(38, 16, "loader", "gpt-5-mini", 3, 210_000, 11_000, 126_000, 4_000),
    Reply(31, 13, "loader", "gpt-5-mini", 2, 140_000, 7_000, 98_000, 2_000),
    Reply(30, 10, "loader", "gpt-5-mini", 3, 190_000, 10_000, 120_000, 3_000),
    # A shorter one on a different model.
    Reply(11, 9, "pages", "claude-sonnet-4-5", 3, 260_000, 14_000, 118_000, 2_000),
    Reply(10, 11, "pages", "claude-sonnet-4-5", 2, 170_000, 9_000, 77_000, 1_000),
    Reply(9, 14, "pages", "claude-sonnet-4-5", 3, 190_000, 10_000, 85_000, 2_000),
    Reply(5, 10, "pages", "claude-sonnet-4-5", 1, 80_000, 7_000, 20_000, 1_000),
    # The session in progress: four days in a row, ending today.
    Reply(3, 16, "parser", "gpt-5-mini", 2, 150_000, 8_000, 110_000, 2_000),
    Reply(2, 9, "parser", "gpt-5-mini", 4, 280_000, 15_000, 205_000, 5_000),
    Reply(1, 13, "parser", "gpt-5-mini", 3, 240_000, 12_000, 190_000, 3_000),
    Reply(0, 11, "parser", "gpt-5-mini", 2, 160_000, 8_000, 130_000, 2_000),
)


def tally(replies: tuple[Reply, ...] | list[Reply]) -> Tally:
    """Add some replies into one tally: the one place the page's arithmetic is written down."""
    return Tally(
        requests=sum(reply.requests for reply in replies),
        input_tokens=sum(reply.input for reply in replies),
        output_tokens=sum(reply.output for reply in replies),
        cache_read_tokens=sum(reply.cached for reply in replies),
        reasoning_tokens=sum(reply.reasoning for reply in replies),
    )


def moment(reply: Reply) -> datetime:
    """Return when a reply was written, with no time zone, so the clock the page shows is this clock everywhere."""
    day = TODAY - timedelta(days=reply.day)
    return datetime(day.year, day.month, day.day, reply.hour, 0)


def sample_ledger() -> Ledger:
    """Return the sample project's usage: every total a sum of :data:`REPLIES`."""
    sessions: list[SessionUsage] = []
    for key, title in TITLES.items():
        rows = [reply for reply in REPLIES if reply.session == key]
        sessions.append(
            SessionUsage(
                session_id=f"{key}-session",
                title=title,
                started=min(moment(reply) for reply in rows),
                updated=max(moment(reply) for reply in rows),
                tally=tally(rows),
                models=tuple(sorted({reply.model for reply in rows})),
            )
        )
    sessions.sort(key=lambda row: row.updated, reverse=True)
    models = {name: tally([r for r in REPLIES if r.model == name]) for name in sorted({r.model for r in REPLIES})}
    days = {
        TODAY - timedelta(days=offset): tally([r for r in REPLIES if r.day == offset])
        for offset in sorted({r.day for r in REPLIES})
    }
    return Ledger(sessions=sessions, models=models, days=days, total=tally(REPLIES))


# -- the context report ------------------------------------------------------------------------------------------

#: Sources and what the tokenizer counted for each: ``(name, tokens, items)``.
SOURCES = (
    ("System prompt", 1_900, 1),
    ("Environment notes", 4_800, 2),
    ("Tool schemas", 11_000, 9),
    ("User messages", 100, 3),
    ("Assistant messages", 22_000, 12),
    ("Tool output", 60_000, 17),
)


def shares(*rows: tuple[str, int, int]) -> tuple[ContextShare, ...]:
    """Return the report's shares for some ``(name, tokens, items)`` rows."""
    return tuple(ContextShare(name, tokens, items) for name, tokens, items in rows)


COUNTER = "tiktoken cl100k_base"
SESSION_FILE = PurePosixPath("~/.zettcode/sessions/-Users-me-projects-api/01a145fa/data.jsonl")


def context_report(kind: str) -> tuple[ContextReport, int]:
    """Return a sample report and the window's compaction point, for one of the situations the guide describes."""
    window, trigger = 200_000, 160_000
    if kind == "live":
        # Mid-session: the provider reported the request, so the rows divide its total.
        return ContextReport(window, COUNTER, shares(*SOURCES), reported=103_241), trigger
    if kind == "near":
        # Close to the point where a request is summarized, after an earlier compaction left a summary behind.
        near = (
            ("System prompt", 1_900, 1),
            ("Environment notes", 4_800, 2),
            ("Tool schemas", 11_000, 9),
            ("User messages", 400, 8),
            ("Assistant messages", 41_000, 26),
            ("Tool output", 90_000, 31),
            ("Compaction summary", 3_600, 1),
        )
        return ContextReport(window, COUNTER, shares(*near), reported=158_900), trigger
    if kind == "resumed":
        # A session just reopened: nothing has been sent yet, so the environment notes and tool schemas are not
        # known and the provider has reported nothing for this request.
        seen = tuple(row for row in SOURCES if row[0] not in ("Environment notes", "Tool schemas"))
        return ContextReport(window, COUNTER, shares(*seen), partial=True), trigger
    raise ValueError(kind)


# -- the shell the pages are painted in --------------------------------------------------------------------------


@contextmanager
def shell(width: int, height: int) -> Iterator[ZettCodeApp]:
    """Yield an offline shell of a fixed size, with its files in a directory that is removed afterwards."""
    previous = Path.cwd()
    runtime: ZettCodeEngine | None = None
    with tempfile.TemporaryDirectory(prefix="zettcode-screens-") as directory:
        try:
            workspace = Path(directory)
            config = ZettCodeConfig(
                workspace=workspace,
                store=workspace / "sessions",
                models=(ModelConfig(model="example-model", token="example-token"),),
                plugins_enabled=False,
                skills_enabled=False,
                mcp_enabled=False,
            )
            runtime = ZettCodeEngine.preview(config)
            runtime.plugins = load_plugins(config, builtins=preview_plugins())
            app = ZettCodeApp(ZettCodeAgent(runtime), theme=THEME, auto_theme=False)
            app.app.resize(width, height)
            app.app.mount()
            yield app
        finally:
            os.chdir(previous)
            if runtime is not None:
                runtime.session_locks.release()


def full_screen(widget_factory: Callable[[], object], width: int, height: int) -> Canvas:
    """Paint one page over the whole terminal, the way the shell presents a page that takes the screen."""
    with shell(width, height) as app:
        app.app.push_screen(Screen(widget_factory(), name=PAGE_SCREEN, modal=True))
        app.app.request_layout()
        return app.app.render()


#: Rows each page takes, which is as many as its content and footer need: a taller terminal only adds blank lines.
USAGE_ROWS = {"Models": 17, "Sessions": 13, "Calendar": 20}
CONTEXT_ROWS = 30


def usage_canvas(tab: str) -> Canvas:
    """Paint the ``/usage`` page on one of its tabs."""
    return full_screen(
        lambda: UsagePage(sample_ledger(), workspace=WORKSPACE, today=TODAY, tab=tab), 100, USAGE_ROWS[tab]
    )


def context_canvas(kind: str) -> Canvas:
    """Paint the ``/context`` page for one of the sample situations."""
    report, trigger = context_report(kind)
    return full_screen(
        lambda: ContextPage(report, path=SESSION_FILE, model="claude-sonnet-4-5", trigger=trigger),  # type: ignore[arg-type]
        100,
        CONTEXT_ROWS,
    )


#: Every picture the guide shows: file name, how to paint it, and what a screen reader says it is.
SCREENS: tuple[tuple[str, Callable[[], Canvas], str], ...] = (
    (
        "usage-models",
        lambda: usage_canvas("Models"),
        "ZettCode's /usage page on the Models tab: input and output bars for each model",
    ),
    (
        "usage-sessions",
        lambda: usage_canvas("Sessions"),
        "ZettCode's /usage page on the Sessions tab: one row for each session with its token bars and cache share",
    ),
    (
        "usage-calendar",
        lambda: usage_canvas("Calendar"),
        "ZettCode's /usage page on the Calendar tab: a grid of weeks shaded by the tokens spent each day",
    ),
    (
        "context",
        lambda: context_canvas("live"),
        "ZettCode's /context page: how full the window is and how the tokens divide between sources",
    ),
    (
        "context-near",
        lambda: context_canvas("near"),
        "ZettCode's /context page close to the compaction point, with a compaction summary among the sources",
    ),
    (
        "context-resumed",
        lambda: context_canvas("resumed"),
        "ZettCode's /context page for a session just reopened, with two sources still pending",
    ),
)


def render_all() -> dict[str, str]:
    """Return every picture as SVG text, keyed by file name."""
    return {f"{name}.svg": svg(paint(), title) for name, paint, title in SCREENS}


def main() -> None:
    """Write the pictures to the chosen directory."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=OUTPUT, help="directory to write the SVG files into")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, text in render_all().items():
        (args.output / name).write_text(text, encoding="utf-8")
        print(f"wrote {args.output / name}")


if __name__ == "__main__":
    main()
