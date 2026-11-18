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
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import cast

from render_terminal import preview, preview_plugins, svg

from zettcode.app.agent.agent import TerminalAgent
from zettcode.app.plugins.loader import load_terminal_plugins, terminal_plugins
from zettcode.app.ui.app import ZettCodeApp
from zettcode.app.ui.shell import APPROVAL_ROWS, PAGE_SCREEN
from zettcode.app.ui.widgets import (
    ApprovalPage,
    EffortPage,
    FormPage,
    ModelPage,
    PetPage,
    PluginsPage,
    SelfCompactPage,
    SessionsPage,
    StatuslinePage,
    bottom_panel,
)
from zettcode.app.ui.widgets.effort_page import EFFORT_ROWS
from zettcode.app.ui.widgets.form_page import Field, form_rows
from zettcode.app.ui.widgets.pet_page import pet_rows
from zettcode.app.ui.widgets.plugins_page import PluginRow
from zettcode.app.ui.widgets.self_compact_page import SELF_COMPACT_ROWS
from zettcode.commands.context_page import ContextPage
from zettcode.commands.hub import DAEMONS, Daemon, HubData, HubPage
from zettcode.commands.usage_page import UsagePage
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.core import ZettCodeEngine
from zettcode.jit_harness.page import HarnessPage, HarnessTarget, TableRow, TableView
from zettcode.pets import bundled_pets
from zettcode.plugin_api.pets import PetCatalog
from zettcode.sdk.types import (
    ContextReport,
    ContextShare,
    DayTotals,
    ModelInfo,
    ModelTotals,
    SessionInfo,
    SessionStatsInfo,
    SessionTotals,
    Totals,
    WorkspaceUsage,
)
from zettcode.tui import DARK, Canvas, Screen

#: The page the documentation shows is the dark palette on the same background the home page's picture uses.
THEME = replace(DARK, background="#232a2e")

#: The last day of the usage calendar, and the project the usage page says it is about.
TODAY = date(2026, 10, 17)
WORKSPACE = "~/projects/api"

#: The directory the sample `/context` session works in, painted as the path it is.
WORKSPACE_PATH = PurePosixPath(WORKSPACE)

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


def tally(replies: tuple[Reply, ...] | list[Reply]) -> Totals:
    """Add some replies into one tally: the one place the page's arithmetic is written down."""
    return Totals(
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


def sample_ledger() -> WorkspaceUsage:
    """Return the sample project's usage: every total a sum of :data:`REPLIES`."""
    sessions: list[SessionTotals] = []
    for key, title in TITLES.items():
        rows = [reply for reply in REPLIES if reply.session == key]
        sessions.append(
            SessionTotals(
                id=f"{key}-session",
                title=title,
                started=min(moment(reply) for reply in rows),
                updated=max(moment(reply) for reply in rows),
                tokens=tally(rows),
                models=tuple(sorted({reply.model for reply in rows})),
            )
        )
    sessions.sort(key=lambda row: row.updated, reverse=True)
    models = tuple(
        ModelTotals(name, tally([r for r in REPLIES if r.model == name])) for name in sorted({r.model for r in REPLIES})
    )
    days = tuple(
        DayTotals(TODAY - timedelta(days=offset), tally([r for r in REPLIES if r.day == offset]))
        for offset in sorted({r.day for r in REPLIES})
    )
    return WorkspaceUsage(sessions=tuple(sessions), models=models, days=days, total=tally(REPLIES))


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


def report(window: int, counter: str, rows: tuple[ContextShare, ...], *, reported: int | None = None, partial=False):
    """Return a report the way the engine builds one: the provider's count when it gave one, else the tokenizer's."""
    return ContextReport(
        window,
        reported if reported is not None else sum(row.tokens for row in rows),
        counter,
        rows,
        partial=partial,
        from_provider=reported is not None,
    )


def context_report(kind: str) -> tuple[ContextReport, int]:
    """Return a sample report and the window's compaction point, for one of the situations the guide describes."""
    window, trigger = 200_000, 160_000
    if kind == "live":
        # Mid-session: the provider reported the request, so the rows divide its total.
        return report(window, COUNTER, shares(*SOURCES), reported=103_241), trigger
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
        return report(window, COUNTER, shares(*near), reported=158_900), trigger
    if kind == "resumed":
        # A session just reopened: nothing has been sent yet, so the environment notes and tool schemas are not
        # known and the provider has reported nothing for this request.
        seen = tuple(row for row in SOURCES if row[0] not in ("Environment notes", "Tool schemas"))
        return report(window, COUNTER, shares(*seen), partial=True), trigger
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
            runtime = ZettCodeEngine.preview(config, terminal_plugins)
            runtime.plugins = load_terminal_plugins(config, builtins=preview_plugins(), agent=False)
            app = ZettCodeApp(TerminalAgent(runtime), theme=THEME, auto_theme=False)
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
        lambda: ContextPage(
            report,
            path=SESSION_FILE,
            workspace=WORKSPACE_PATH,
            model="claude-sonnet-4-5",
            trigger=trigger,
        ),
        100,
        CONTEXT_ROWS,
    )


# -- the model picker --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SampleModels:
    """A client that answers the one question the model picker asks it: which models were configured.

    The picker reads ``client.models`` and nothing else, so a picture of it needs no runtime, no connection
    and no token — only the entries the sample configuration file holds.
    """

    models: Sequence[ModelInfo]


def sample_models() -> tuple[ModelInfo, ...]:
    """Return four connections the way one configuration file holds them: a file entry for each API, and a local one."""
    return (
        ModelInfo(
            name="DeepSeek Pro",
            model="deepseek-v4-pro",
            context_window=1_000_000,
            multimodal=False,
            efforts=("low", "medium", "high"),
            active=True,
            display_model="DeepSeek Pro",
            base_url="https://api.deepseek.com",
        ),
        ModelInfo(
            name="Claude Sonnet 4.5",
            model="claude-sonnet-4-5",
            context_window=200_000,
            multimodal=True,
            efforts=("low", "medium", "high"),
            api="anthropic",
        ),
        ModelInfo(
            name="GPT-5",
            model="gpt-5",
            context_window=400_000,
            multimodal=True,
            efforts=("minimal", "low", "medium", "high"),
            api="responses",
        ),
        ModelInfo(
            name="Qwen3 Coder (local)",
            model="qwen3-coder",
            context_window=262_144,
            multimodal=False,
            efforts=(),
            base_url="http://localhost:11434/v1",
        ),
    )


def models_canvas() -> Canvas:
    """Paint ``/model`` over the conversation, with every entry the sample file holds."""
    models = sample_models()
    return full_screen(
        lambda: ModelPage(SampleModels(models), on_select=lambda entry: None, on_cancel=lambda: None),
        100,
        len(models) + 6,
    )


# -- the approval prompt -----------------------------------------------------------------------------------------


#: The command the sample conversation asks to run, and the directory it runs in.
APPROVAL_COMMAND = "pytest tests/test_users.py -q"


def approval_canvas() -> Canvas:
    """Paint the approval prompt the way the shell shows it: a strip at the bottom of the conversation.

    This is the one interaction the program cannot do without and prose describes badly — five answers, each with
    its own key, one of which changes the permission level for the rest of the session — so the picture is the
    prompt itself, over the conversation that asked for the command.
    """

    def open_the_prompt(app: ZettCodeApp) -> None:
        page = ApprovalPage(
            APPROVAL_COMMAND,
            on_choice=lambda choice: None,
            permission="ask",
            work_dir="~/projects/api",
        )
        app.app.push_screen(Screen(bottom_panel(page, rows=APPROVAL_ROWS), name=PAGE_SCREEN, modal=True))

    return preview(open_the_prompt)


#: The clock ``/resume`` reads its ages from, fixed so the picture says the same thing on every build.
RESUMED_AT = datetime(2026, 10, 17, 11, 0)


def session_rows() -> tuple[tuple[SessionInfo, ...], dict[str, SessionStatsInfo]]:
    """Return five stored sessions and their totals, in the store's order: newest first."""
    rows = (
        SessionInfo(
            id="1a2b3c4d",
            title="Fix the parser crash",
            created_at=RESUMED_AT - timedelta(days=2, hours=4),
            updated_at=RESUMED_AT - timedelta(minutes=3),
        ),
        SessionInfo(
            id="9f8e7d6c",
            title=None,
            created_at=RESUMED_AT - timedelta(hours=17),
            updated_at=RESUMED_AT - timedelta(hours=17),
        ),
        SessionInfo(
            id="4c5d6e7f",
            title="Refactor the config loader",
            created_at=RESUMED_AT - timedelta(days=6),
            updated_at=RESUMED_AT - timedelta(days=1, hours=2),
        ),
        SessionInfo(
            id="2b3c4d5e",
            title="Pagination for /users",
            created_at=RESUMED_AT - timedelta(days=11),
            updated_at=RESUMED_AT - timedelta(days=3),
        ),
        SessionInfo(
            id="7a8b9c0d",
            title="Review the tools port",
            created_at=RESUMED_AT - timedelta(days=13),
            updated_at=RESUMED_AT - timedelta(days=8),
        ),
    )
    stats = {
        "1a2b3c4d": SessionStatsInfo(
            id="1a2b3c4d",
            entries=41,
            requests=12,
            input_tokens=12_300,
            output_tokens=1_200,
            cache_read_tokens=10_700,
            cache_reported=True,
        ),
        "9f8e7d6c": SessionStatsInfo(id="9f8e7d6c", entries=3, requests=1, input_tokens=3_900, cache_reported=True),
        "4c5d6e7f": SessionStatsInfo(
            id="4c5d6e7f",
            entries=118,
            requests=34,
            input_tokens=210_000,
            output_tokens=18_400,
            cache_read_tokens=164_000,
            cache_reported=True,
        ),
        "2b3c4d5e": SessionStatsInfo(
            id="2b3c4d5e",
            entries=76,
            requests=21,
            input_tokens=96_500,
            output_tokens=7_800,
            cache_read_tokens=61_000,
            cache_reported=True,
        ),
        "7a8b9c0d": SessionStatsInfo(id="7a8b9c0d", entries=52, requests=15, input_tokens=64_000, output_tokens=5_100),
    }
    return rows, stats


def sessions_canvas() -> Canvas:
    """Paint ``/resume``: the stored sessions, what each cost, and the box that searches them."""
    rows, stats = session_rows()
    return full_screen(
        lambda: SessionsPage(rows, stats=stats, on_select=lambda session: None, on_cancel=lambda: None, now=RESUMED_AT),
        110,
        14,
    )


# -- the plugin switches -----------------------------------------------------------------------------------------


def plugin_rows() -> tuple[PluginRow, ...]:
    """Return the switches a real page could have: the program's own first, then installed ones.

    The rows are the shape the editor builds — what a plugin calls itself, the distribution that carries it, whether
    it is compiled in, whether it is on, and the key or distribution a switch is written with — with one compiled-in
    plugin that failed, because a page with no failure does not show what a failure looks like.
    """
    return (
        PluginRow(
            "presenters",
            "zettcode-presenters",
            builtin=True,
            setting="rows.enabled",
            description="The rows of the conversation and how they are drawn",
        ),
        PluginRow(
            "skills",
            "zettcode-skills",
            builtin=True,
            setting="skills.enabled",
            description="The skills a workspace declares, as @ references",
        ),
        PluginRow(
            "mcp",
            "zettcode-mcp",
            builtin=True,
            setting="mcp.enabled",
            description="MCP servers from the configuration and the workspace",
        ),
        PluginRow(
            "todos",
            "zettcode-todos",
            builtin=True,
            enabled=False,
            setting="harness.todowrite",
            description="The todo_write tool and the plan it keeps above the composer",
        ),
        PluginRow(
            "coding",
            "zettcode-code-agents",
            builtin=True,
            failure="no plugin provides the model",
            switchable=False,
            why="its setting is unknown to a process that could not load it",
        ),
        PluginRow(
            "monitor",
            "zettcode-monitor",
            description="Every model call, exported as HTML",
        ),
        PluginRow(
            "recap",
            "zettcode-recap",
            enabled=False,
            description="A recap of what the session did when you come back",
        ),
    )


def plugins_canvas() -> Canvas:
    """Paint ``/plugins``: the switches, the key each one writes, and what the marked plugin adds."""
    rows = plugin_rows()
    return full_screen(
        lambda: PluginsPage(rows, on_apply=lambda written: None, on_cancel=lambda: None),
        120,
        18,
    )


# -- the panels a command opens ---------------------------------------------------------------------------------

#: One line per reasoning level, as the effort panel shows it under the rail.
EFFORT_NOTES = {
    "off": "no deliberate reasoning",
    "minimal": "a token of thought, fastest",
    "low": "quick answers",
    "medium": "the default balance",
    "high": "more thought on hard problems",
    "xhigh": "a long think on hard problems",
    "max": "the highest budget the provider takes",
    "ultra": "above max; a provider maps it down when it must",
}


def effort_canvas() -> Canvas:
    """Paint ``/effort``: the rail, the knob at the level in force, and what the level under it means."""
    levels = tuple(EFFORT_NOTES)
    return full_screen(
        lambda: EffortPage(
            levels,
            "medium",
            notes=EFFORT_NOTES,
            on_select=lambda level: None,
            on_cancel=lambda: None,
        ),
        100,
        EFFORT_ROWS,
    )


def compact_canvas() -> Canvas:
    """Paint ``/compact``: the session's own choice beside the default every other session follows."""
    return full_screen(
        lambda: SelfCompactPage(
            None,
            True,
            on_apply=lambda choice, default: None,
            on_cancel=lambda: None,
        ),
        100,
        SELF_COMPACT_ROWS + 2,
    )


def statusline_canvas() -> Canvas:
    """Paint ``/statusline``: the two bars as the choices stand, and a switch for every named part."""
    return full_screen(
        lambda: StatuslinePage(
            {"handle", "speed", "cache"},
            on_apply=lambda shown: None,
            on_cancel=lambda: None,
        ),
        100,
        22,
    )


def pet_canvas() -> Canvas:
    """Paint ``/pet``: every pet offered, the one out marked, and the marked one going through its moods."""
    catalog = PetCatalog(bundled_pets())
    return full_screen(
        lambda: PetPage(
            catalog,
            "penguin",
            on_move=lambda name: None,
            on_select=lambda name: None,
            on_cancel=lambda: None,
        ),
        100,
        pet_rows(len(catalog.names()), 40),
    )


# -- the hub ----------------------------------------------------------------------------------------------------

#: The clock ``/hub`` counts its ages from, fixed for the same reason the resume panel has one.
HUB_NOW = 1_792_000_000.0


def hub_canvas() -> Canvas:
    """Paint ``/hub`` on its Daemons tab: what each daemon is doing, and the keys that act on the row under the mark.

    The rows are the shape the tab builds — the daemon's name and title, its session, the model and the level it runs
    at, and how long ago its record was written — and the keys are the page's own footer, which is where a reader
    learns that Enter starts an offline daemon and that deleting takes two presses.
    """
    data = HubData(
        daemons=(
            Daemon(
                session_id="01a1ea21",
                label="builder",
                status="running",
                model="deepseek-v4-pro",
                name="builder",
                title="tool builder",
                effort="medium",
                permission="safe",
                activity=HUB_NOW - 12,
            ),
            Daemon(
                session_id="01a1ea03",
                label="review-diff",
                status="running",
                model="claude-sonnet-4-5",
                name="review-diff-emphasis",
                title="Review word-level diff emphasis",
                effort="high",
                permission="full",
                activity=HUB_NOW - 240,
            ),
            Daemon(
                session_id="01a1e9d6",
                label="review-tools",
                status="offline",
                model="deepseek-v4-pro",
                name="review-tools",
                title="Review the tools port",
                effort="high",
                permission="full",
                activity=HUB_NOW - 5400,
            ),
        ),
        note="3 daemons \u00b7 2 running",
        now=HUB_NOW,
    )
    page = HubPage(data, on_close=lambda: None, on_stop=lambda sid: None, on_restart=lambda sid: None)
    page._show(DAEMONS)
    return full_screen(lambda: page, 118, 14)


# -- the add-a-model form ---------------------------------------------------------------------------------------


def config_form_canvas() -> Canvas:
    """Paint the form ``/config`` asks for with: the lines, the box around the one the cursor is in, and its hint.

    The fields are the ones the flow builds for a chat endpoint, in its order and with its labels, so the picture
    answers "what am I being asked for" the way the real page does.
    """
    fields = (
        Field(
            "model", "Model id", initial="deepseek-v4-pro", hint="The id the endpoint calls the model.", required=True
        ),
        Field("token", "Token", initial="sk-9f2c1d7a4b", secret=True, placeholder="optional"),
        Field("url", "Address", initial="https://api.deepseek.com"),
        Field("name", "Shown name", initial="DeepSeek Pro"),
        Field(
            "context_window",
            "Context window",
            initial="1000000",
            hint="Tokens the model can carry. Leave it empty to use the endpoint's own.",
        ),
        Field("compact_percent", "Compress at", initial="80%", placeholder="80%"),
    )
    return full_screen(
        lambda: FormPage(
            "Add a model \u2014 OpenAI Chat API",
            fields,
            on_submit=lambda values: None,
            on_cancel=lambda: None,
            cancel_label="esc back",
        ),
        100,
        form_rows(len(fields)),
    )


#: The harness root the page prints, written as the page prints it: ``~`` stays a literal here so the picture is the
#: same on every machine that builds the guide, instead of the home directory of whoever ran the generator.
HARNESS_ROOT = cast("Path", PurePosixPath("~/.zettcode/harness"))


def harness_canvas() -> Canvas:
    """Paint ``/harness``: one repository per session, and the tab strip that reaches its tools and files.

    The rows are the shape ``HarnessCommand`` builds — the session id in the first column, then its title, the
    repository that session wrote, and what that repository is for — with the current session marked, so the page
    says what a harness *is*: tools written for one conversation, kept beside the others and borrowable.
    """
    here, other, third = (
        Path("/tmp/harness/api-1f3c"),
        Path("/tmp/harness/api-8b21"),
        Path("/tmp/harness/api-c40e"),
    )
    views = (
        TableView(
            "Harnesses",
            ("SESSION", "TITLE", "REPOSITORY", "DESCRIPTION"),
            (
                TableRow(
                    HarnessTarget("api-1f3c", here),
                    ("api-1f3c", "Refactor the config loader", "loader-tools", "Find every caller of load_config"),
                    current=True,
                ),
                TableRow(
                    HarnessTarget("api-8b21", other),
                    ("api-8b21", "Pagination for /users", "pager-tools", "List the pages one view can return"),
                ),
                TableRow(
                    HarnessTarget("api-c40e", third),
                    ("api-c40e", "Fix the parser crash", "parser-tools", "Reproduce the crash from a log line"),
                ),
            ),
            "accent = current session \u00b7 enter borrow \u00b7 esc close",
        ),
        TableView(
            "Tools",
            ("TOOL", "SOURCE", "STATUS", "DESCRIPTION"),
            (
                TableRow(
                    None,
                    ("list_callers", "jit/loader-tools", "active", "List the call sites of a function"),
                    current=True,
                ),
                TableRow(None, ("rewrite_caller", "jit/loader-tools", "available", "Rewrite one call site")),
            ),
            "accent = active \u00b7 error colour = banned \u00b7 esc close",
        ),
        TableView(
            "Files",
            ("FILE", "DESCRIPTION", "SIZE", "PATH"),
            (TableRow(None, ("NOTES.md", "How the two tools work together", "1,204 B", ".")),),
        ),
    )
    return full_screen(
        lambda: HarnessPage(
            state="on",
            directory=HARNESS_ROOT,
            views=views,
            on_switch=lambda target: None,
            on_close=lambda: None,
        ),
        100,
        11,
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
    (
        "models",
        models_canvas,
        "ZettCode's /model picker: four connections from one configuration file, the current one marked",
    ),
    (
        "harness",
        harness_canvas,
        "ZettCode's /harness page: a repository per session, with the Tools and Files tabs beside it",
    ),
    (
        "sessions",
        sessions_canvas,
        "ZettCode's /resume picker: five stored sessions with their age, entries and token figures, over a search box",
    ),
    (
        "plugins",
        plugins_canvas,
        "ZettCode's /plugins page: the program's own switches first, then installed ones, each with the key or "
        "distribution it writes",
    ),
    (
        "effort",
        effort_canvas,
        "ZettCode's /effort panel: a rail of eight reasoning levels with the knob on medium",
    ),
    (
        "compact",
        compact_canvas,
        "ZettCode's /compact panel: this session's own choice over the default every other session follows",
    ),
    (
        "statusline",
        statusline_canvas,
        "ZettCode's /statusline panel: the header and the status line as the choices stand, with a switch for every "
        "named part",
    ),
    (
        "pets",
        pet_canvas,
        "ZettCode's /pet panel: the pets on the left with the one out marked, and that pet on its stage",
    ),
    (
        "hub",
        hub_canvas,
        "ZettCode's /hub page on the Daemons tab: three daemons with their model and permission level, and the keys "
        "that start, restart, stop and delete",
    ),
    (
        "config-form",
        config_form_canvas,
        "The form /config asks for a model with: the model id, token, address, shown name, context window and the "
        "point it compresses at, each in a box",
    ),
    (
        "approval",
        approval_canvas,
        "ZettCode's approval prompt under a conversation: the command, the directory it runs in, and five numbered "
        "answers with their keys",
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
