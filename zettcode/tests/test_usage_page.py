"""The ``/usage`` page: how its numbers are drawn, how its keys move, and that the command opens it."""

from __future__ import annotations

import colorsys
from datetime import date, timedelta
from pathlib import Path

import pytest
from zett_agent.messages import AssistantMessage, UserMessage
from zett_agent.model import ModelUsage

from zettcode.app.commands import CommandContext
from zettcode.app.plugins import TerminalContainer
from zettcode.app.plugins.builtins import BUILTIN_PLUGINS, UsageCommand
from zettcode.app.ui.widgets import UsagePage
from zettcode.app.ui.widgets import usage_charts as charts
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.storage import SessionStore
from zettcode.sdk.client import Client
from zettcode.sdk.types import DayTotals, ModelTotals, SessionTotals, Totals, WorkspaceUsage
from zettcode.tui import DARK, LIGHT, TuiApp
from zettcode.tui.core.events import MouseAction, MouseEvent
from zettcode.tui.render import blend, parse_hex
from zettcode.tui.testing import Harness
from zettcode.tui.testing.snapshot import render_block

TODAY = date(2026, 10, 16)  # a Friday


def tally(total_in: int, total_out: int = 0, requests: int = 1) -> Totals:
    return Totals(requests=requests, input_tokens=total_in, output_tokens=total_out)


def ledger_of(
    days: dict[date, Totals] | None = None, models: dict[str, Totals] | None = None, sessions=()
) -> WorkspaceUsage:
    counted = list((models or days or {}).values())
    total = Totals(
        requests=sum(t.requests for t in counted),
        input_tokens=sum(t.input_tokens for t in counted),
        output_tokens=sum(t.output_tokens for t in counted),
        cache_read_tokens=sum(t.cache_read_tokens for t in counted),
        reasoning_tokens=sum(t.reasoning_tokens for t in counted),
    )
    return WorkspaceUsage(
        sessions=tuple(sessions),
        models=tuple(ModelTotals(name, t) for name, t in (models or {}).items()),
        days=tuple(DayTotals(day, t) for day, t in (days or {}).items()),
        total=total,
    )


def text_of(line) -> str:
    return "".join(piece for piece, _ in line)


def hls(colour: str) -> tuple[float, float, float]:
    return colorsys.rgb_to_hls(*(channel / 255 for channel in parse_hex(colour)))


def distance(first: str, second: str) -> float:
    return sum((a - b) ** 2 for a, b in zip(parse_hex(first), parse_hex(second), strict=True)) ** 0.5


# -- numbers and bars --------------------------------------------------------
@pytest.mark.parametrize(
    ("count", "written"),
    [
        (0, "0"),
        (999, "999"),
        (1000, "1.00K"),
        (12_345, "12.3K"),
        (999_400, "999K"),
        (999_600, "1.00M"),
        (1_460_000_000, "1.46B"),
        (2_000_000_000_000, "2.00T"),
        (10**15, "1000T"),
    ],
)
def test_a_count_is_written_in_three_digits_with_a_unit(count, written):
    assert charts.compact(count) == written


def test_a_bar_is_whole_blocks_and_one_partial_and_never_longer_than_its_track():
    assert charts.bar(10, 10, 8) == "\u2588" * 8
    assert charts.bar(5, 10, 8) == "\u2588" * 4
    assert charts.bar(1, 8 * 8, 8) == "\u258f", "an eighth of a cell"
    assert charts.bar(99, 10, 8) == "\u2588" * 8, "a value past the maximum is held at the track"
    assert charts.bar(0, 10, 8) == "" and charts.bar(5, 0, 8) == "" and charts.bar(5, 10, 0) == ""


def test_a_tiny_value_still_shows_next_to_a_huge_one():
    assert charts.bar(1, 10**9, 20) == "\u258f"


def test_a_square_root_scale_lifts_small_values_off_the_floor():
    assert len(charts.bar(1, 100, 20, curve=0.5)) > len(charts.bar(1, 100, 20))


def test_a_meter_fills_its_track_so_columns_line_up():
    for value in (0, 1, 50, 100):
        line = charts.meter(value, 100, 12, "input")
        assert charts.line_width(line) == 12


# -- the calendar ------------------------------------------------------------
def test_a_calendar_week_opens_on_sunday():
    assert charts.week_start(TODAY) == date(2026, 10, 11)
    assert charts.week_start(date(2026, 10, 11)) == date(2026, 10, 11)
    assert charts.week_start(date(2026, 10, 17)) == date(2026, 10, 11)


def test_the_calendar_ends_on_the_week_of_today_and_fits_the_page():
    assert charts.weeks_that_fit(100) == 48
    assert charts.weeks_that_fit(1000) == charts.MAX_WEEKS
    assert charts.weeks_that_fit(2) == 1
    assert charts.first_day(TODAY, 1) == date(2026, 10, 11)
    assert charts.first_day(TODAY, 3) == date(2026, 9, 27)


def test_shades_follow_the_quartiles_of_the_days_that_were_used():
    days = {TODAY - timedelta(days=n): tally(100 * (n + 1)) for n in range(8)}
    days[TODAY - timedelta(days=20)] = tally(0)

    shades = charts.levels(days)

    assert TODAY - timedelta(days=20) not in shades, "a day that spent nothing has no shade"
    assert set(shades.values()) == {1, 2, 3, 4}
    assert shades[TODAY - timedelta(days=7)] == 4 and shades[TODAY] == 1


def test_a_single_used_day_is_shaded_and_no_day_is_not():
    assert charts.levels({TODAY: tally(5)}) == {TODAY: 1}
    assert charts.levels({}) == {}


def test_streaks_count_runs_of_used_days_and_do_not_break_at_midnight():
    used = {TODAY - timedelta(days=n): tally(1) for n in (1, 2, 3, 10, 11)}

    assert charts.streaks(used, TODAY) == (3, 3), "yesterday still carries the run into a day not yet used"
    used[TODAY] = tally(1)
    assert charts.streaks(used, TODAY) == (4, 4)
    del used[TODAY - timedelta(days=1)]
    assert charts.streaks(used, TODAY) == (2, 1)
    assert charts.streaks({}, TODAY) == (0, 0)


def test_the_calendar_draws_seven_rows_a_square_for_every_day_up_to_today_and_a_legend():
    days = {TODAY: tally(100), TODAY - timedelta(days=1): tally(1)}
    head, body, start, weeks = charts.calendar_tab(ledger_of(days=days), 60, TODAY, TODAY)

    rows = body[1:8]
    assert weeks == charts.weeks_that_fit(60) and start == charts.first_day(TODAY, weeks)
    assert all(line_cells(row) == weeks for row in rows[:5]), "Sunday to Thursday have a day in the last week"
    assert line_cells(rows[5]) == weeks, "Friday is today"
    assert line_cells(rows[6]) == weeks - 1, "Saturday has not happened yet"
    assert text_of(body[9]).strip().startswith("Less") and text_of(body[9]).strip().endswith("More")
    assert "Fri 16 Oct 2026" in text_of(body[11])
    assert "2 active days" in text_of(body[12])
    assert "All models" in text_of(head[0])


def line_cells(row) -> int:
    return sum(piece.count("\u25a0") for piece, _ in row)


def test_the_chosen_day_is_marked_and_the_others_are_not():
    days = {TODAY: tally(100)}
    _, body, _, _ = charts.calendar_tab(ledger_of(days=days), 40, TODAY, TODAY - timedelta(days=1))

    marked = [(piece, role) for row in body[1:8] for piece, role in row if role.endswith("*")]
    assert len(marked) == 1


def test_months_are_named_once_and_never_over_each_other():
    names = charts.month_labels(date(2025, 10, 5), 53)

    assert list(names.values())[0] == "Oct", "a calendar that opens mid-month says which"
    columns = sorted(names)
    assert all(later - earlier >= 2 for earlier, later in zip(columns, columns[1:], strict=False))
    assert list(names.values())[:3] == ["Oct", "Nov", "Dec"]


def test_an_opening_month_that_is_over_in_a_column_gives_way_to_the_next():
    names = charts.month_labels(date(2025, 10, 19), 10)

    assert list(names.values())[:2] == ["Nov", "Dec"], "October had one column and no room for its name"
    assert 0 not in names


def test_a_day_with_nothing_says_so_and_a_day_with_something_says_what():
    days = {TODAY: Totals(requests=2, input_tokens=900, output_tokens=100)}
    ledger = ledger_of(days=days)

    quiet = text_of(charts._facts(ledger, TODAY, TODAY - timedelta(days=3))[0])
    busy = text_of(charts._facts(ledger, TODAY, TODAY)[0])

    assert "nothing spent" in quiet
    assert "1.00K tokens" in busy and "in 900" in busy and "out 100" in busy and "2 requests" in busy


# -- the other two tabs ------------------------------------------------------
def test_the_models_tab_ranks_by_total_and_scales_input_and_output_apart():
    models = {"small": tally(100, 10), "big": tally(10_000, 100)}
    head, body = charts.models_tab(ledger_of(models=models), 100)

    names = [text_of(line) for line in body if line and line[0][1] == "heading"]
    assert [name.split()[0] for name in names] == ["big", "small"]

    def filled(line, role):
        return sum(len(piece) for piece, name in line if name == role)

    inputs = [line for line in body if text_of(line).startswith("  input")]
    outputs = [line for line in body if text_of(line).startswith("  output")]
    track = filled(inputs[0], "input")
    assert track == filled(outputs[0], "output"), (
        "the largest of each is a full bar, though one is a hundredth of the other"
    )
    assert filled(outputs[1], "output") > filled(inputs[1], "input"), "each direction has its own scale"


def test_the_models_tab_with_no_model_says_there_is_nothing():
    _, body = charts.models_tab(ledger_of(), 80)

    assert "No model replies" in text_of(body[0])


def test_session_bars_give_way_before_the_title_does():
    wide = charts.session_columns(120)
    narrow = charts.session_columns(60)
    tiny = charts.session_columns(30)

    assert wide[0] == 14 and narrow[0] < wide[0] and tiny[0] == 0
    for width in (120, 100, 80, 60, 40, 30):
        track, title = charts.session_columns(width)
        assert title >= 0, "a page too narrow for a title drops it rather than running over the edge"


def test_a_session_row_is_the_width_of_the_page_it_was_drawn_for():
    from datetime import datetime, timezone

    row = SessionTotals(
        "s",
        "A title",
        datetime(2026, 10, 9, tzinfo=timezone.utc),
        datetime(2026, 10, 9, tzinfo=timezone.utc),
        tally(10, 2),
        ("m",),
    )
    ledger = ledger_of(models={"m": tally(10, 2)}, sessions=[row])
    for width in (120, 100, 60, 40, 30):
        _, body = charts.sessions_tab(ledger, width)
        assert charts.line_width(body[0]) <= width, width


# -- the page ----------------------------------------------------------------
def page_of(ledger: WorkspaceUsage, **options) -> UsagePage:
    return UsagePage(ledger, workspace="~/projects/api", today=TODAY, **options)


def sample() -> WorkspaceUsage:
    days = {TODAY - timedelta(days=n): tally(1000 * (n + 1), 10 * (n + 1)) for n in range(5)}
    models = {"alpha": tally(15_000, 150, requests=5)}
    return ledger_of(days=days, models=models)


def test_the_page_opens_on_the_tab_it_is_asked_for_and_falls_back_to_models():
    assert page_of(sample()).tab_name == "Models"
    assert page_of(sample(), tab="Calendar").tab_name == "Calendar"
    assert page_of(sample(), tab="nonsense").tab_name == "Models"


@pytest.mark.parametrize("tab", ["Models", "Sessions", "Calendar"])
@pytest.mark.parametrize("size", [(100, 30), (60, 16), (20, 8), (8, 4)])
def test_every_tab_paints_at_every_size_without_error(tab, size):
    block = render_block(page_of(sample(), tab=tab), width=size[0], height=size[1])

    assert "Usage" in block or size[0] < 10


@pytest.mark.parametrize("theme", [DARK, LIGHT])
def test_the_calendar_shades_are_five_distinct_colours_in_either_theme(theme):
    page = page_of(sample(), tab="Calendar")
    app = TuiApp(page, width=60, height=20, theme=theme)
    app.mount()

    colours = {page.style_of(f"heat{level}").foreground for level in range(5)}

    assert len(colours) == 5
    chosen = page.style_of("heat2*")
    assert chosen.background != page.style_of("heat2").background and chosen.bold, (
        "the chosen day is lifted off the page"
    )
    assert chosen.foreground == page.style_of("heat2").foreground, "and keeps its own shade"


@pytest.mark.parametrize("theme", [DARK, LIGHT])
def test_the_calendar_is_orange_gold_and_told_apart_from_an_empty_day_and_from_its_neighbours(theme):
    page = page_of(sample(), tab="Calendar")
    TuiApp(page, width=60, height=20, theme=theme).mount()

    empty = page.style_of("heat0").foreground
    shades = [page.style_of(f"heat{level}").foreground for level in range(1, charts.LEVELS)]

    for shade in shades:
        hue = hls(shade)[0] * 360
        assert 20 <= hue <= 45, f"{theme.name}: {shade} is hue {hue:.0f}, not orange-gold"
    assert distance(empty, shades[0]) >= 40, "the quietest active day is not mistaken for an empty one"
    steps = [distance(first, second) for first, second in zip(shades, shades[1:], strict=False)]
    assert min(steps) >= 22, f"{theme.name}: neighbouring levels are {steps} apart"


@pytest.mark.parametrize("theme", [DARK, LIGHT])
def test_every_calendar_level_stands_deeper_and_further_from_the_page_than_the_one_below(theme):
    page = page_of(sample(), tab="Calendar")
    TuiApp(page, width=60, height=20, theme=theme).mount()

    shades = [page.style_of(f"heat{level}").foreground for level in range(1, charts.LEVELS)]
    distances = [distance(theme.surface_alt, shade) for shade in shades]

    assert distances == sorted(distances) and len(set(shades)) == len(shades)
    base = blend(theme.warning, theme.tools.write, 0.5)
    assert hls(shades[-1])[1] < hls(base)[1], "the busiest day is deeper than the colour it is made from"
    assert hls(shades[-1])[2] > hls(base)[2], "and more saturated"


def test_tab_and_the_number_keys_switch_views_and_start_each_at_its_top():
    harness = Harness(page_of(sample()), width=80, height=20)

    harness.press("tab")
    assert harness.root.tab_name == "Sessions"
    harness.press("tab")
    assert harness.root.tab_name == "Calendar"
    harness.press("tab")
    assert harness.root.tab_name == "Models"
    harness.press("backtab")
    assert harness.root.tab_name == "Calendar"
    harness.write("1")
    assert harness.root.tab_name == "Models"
    harness.write("3")
    assert harness.root.tab_name == "Calendar"


def test_the_arrow_keys_choose_a_day_and_stop_at_both_ends():
    harness = Harness(page_of(sample(), tab="Calendar"), width=100, height=30)
    page = harness.root
    harness.render()

    harness.press("left")
    assert page.selected == TODAY - timedelta(days=7)
    harness.press("up")
    assert page.selected == TODAY - timedelta(days=8)
    harness.press("down")
    harness.press("right")
    assert page.selected == TODAY
    harness.press("right")
    assert page.selected == TODAY, "no day after today"
    harness.press("home")
    assert page.selected == charts.first_day(TODAY, charts.weeks_that_fit(page.rect.width - 4))
    harness.press("left")
    assert page.selected == charts.first_day(TODAY, charts.weeks_that_fit(page.rect.width - 4)), "nor before the first"
    harness.press("end")
    assert page.selected == TODAY


def test_a_long_list_scrolls_by_key_page_and_wheel_and_never_past_its_ends():
    rows = [SessionTotals(f"s{n}", f"session {n}", _t(n), _t(n), tally(n + 1, 1), ("m",)) for n in range(40)]
    harness = Harness(page_of(ledger_of(models={"m": tally(100)}, sessions=rows), tab="Sessions"), width=80, height=14)
    page = harness.root
    harness.render()

    harness.press("down")
    harness.press("down")
    assert page.offset == 2
    harness.press("up")
    assert page.offset == 1
    harness.press("page_down")
    assert page.offset == 1 + page._body_rows - 1
    harness.press("end")
    furthest = page.offset
    assert furthest == 40 - page._body_rows
    harness.press("down")
    assert page.offset == furthest
    harness.press("home")
    assert page.offset == 0
    harness.press("up")
    assert page.offset == 0
    harness.dispatch(MouseEvent(x=10, y=5, action=MouseAction.SCROLL_DOWN))
    assert page.offset == 3
    harness.dispatch(MouseEvent(x=10, y=5, action=MouseAction.SCROLL_UP))
    assert page.offset == 0
    assert "session 0" in harness.render().text
    harness.press("tab")
    assert page.offset == 0, "another tab starts at its top"


def _t(day: int):
    from datetime import datetime, timezone

    return datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=day)


def test_escape_and_q_leave_through_the_owners_callback():
    left: list[str] = []
    harness = Harness(page_of(sample(), on_cancel=lambda: left.append("closed")), width=60, height=14)

    harness.press("escape")
    harness.write("q")

    assert left == ["closed", "closed"]


def test_keys_the_page_does_not_use_are_left_for_others():
    harness = Harness(page_of(sample()), width=60, height=14)

    assert harness.press("f5") is False
    assert harness.write("x") is False
    assert harness.press("a", control=True) is False


# -- the command -------------------------------------------------------------
class Silent:
    def markdown(self, text): ...
    def notice(self, text): ...
    def error(self, text): ...
    def notify(self, text, *, level="info"): ...


def host_for(config: ZettCodeConfig):
    """A stand-in for the shell that has what the command asks of it: a client over a configuration."""
    from types import SimpleNamespace

    agent = SimpleNamespace(runtime=SimpleNamespace(config=config, session_id="s"))
    return SimpleNamespace(client=Client._around(agent))  # type: ignore[arg-type]


def command_over(tmp_path: Path):
    (tmp_path / "work").mkdir(exist_ok=True)
    config = ZettCodeConfig(
        workspace=tmp_path / "work",
        store=tmp_path / "sessions",
        models=(ModelConfig(model="m", token="t"),),
        plugins_enabled=False,
        skills_enabled=False,
        mcp_enabled=False,
    )
    container = TerminalContainer(config)
    UsageCommand().activate(container)
    return config, container.commands[0]


def test_usage_is_one_of_the_builtin_plugins_and_a_command_that_may_run_beside_a_request(tmp_path: Path):
    assert any(isinstance(plugin, UsageCommand) for plugin in BUILTIN_PLUGINS)
    container = TerminalContainer(ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),)))
    UsageCommand().activate(container)

    (command,) = container.commands
    assert command.name == "/usage" and command.when_busy == "now"
    assert command.description


async def test_the_command_says_so_instead_of_opening_an_empty_page(tmp_path: Path):
    config, command = command_over(tmp_path)

    result = await command.handler(CommandContext(argument="", ui=Silent(), host=host_for(config)))

    assert result.widget is None and "No model replies" in result.message
    assert not (tmp_path / "sessions").exists(), "looking must not create the store"


async def test_the_command_opens_a_page_of_what_the_workspace_spent(tmp_path: Path):
    config, command = command_over(tmp_path)
    store = SessionStore(config.store, config.workspace)
    await store.append("a", "r", UserMessage(content="q"))
    await store.append(
        "a",
        "r",
        AssistantMessage(content="x", model="alpha"),
        usage=ModelUsage(
            input_tokens=500, output_tokens=50, cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0
        ),
    )

    result = await command.handler(CommandContext(argument="", ui=Silent(), host=host_for(config)))

    assert isinstance(result.widget, UsagePage)
    assert result.widget.ledger.total.total_tokens == 550
    assert [entry.model for entry in result.widget.ledger.models] == ["alpha"]
    assert "work" in result.widget.workspace


async def test_a_second_look_sees_what_was_spent_in_between(tmp_path: Path):
    config, command = command_over(tmp_path)
    store = SessionStore(config.store, config.workspace)
    usage = ModelUsage(
        input_tokens=100, output_tokens=10, cache_read_tokens=0, cache_write_tokens=0, reasoning_tokens=0
    )
    await store.append("a", "r1", AssistantMessage(content="x", model="m"), usage=usage)
    host = host_for(config)
    first = await command.handler(CommandContext(argument="", ui=Silent(), host=host))
    await store.append("a", "r2", AssistantMessage(content="y", model="m"), usage=usage)

    second = await command.handler(CommandContext(argument="", ui=Silent(), host=host))

    assert (first.widget.ledger.total.total_tokens, second.widget.ledger.total.total_tokens) == (110, 220)


async def test_the_page_reads_what_the_reader_produced(tmp_path: Path):
    config, _ = command_over(tmp_path)
    ledger = await host_for(config).client.usage_ledger()

    assert UsagePage(ledger).ledger is ledger


def test_the_sessions_tab_shows_both_when_a_session_began_and_when_it_last_changed():
    """The order is the last change, so the page has to say what that was, next to the start."""
    from datetime import datetime

    from zettcode.sdk.types import SessionTotals

    row = SessionTotals(
        "s",
        "A title",
        datetime(2026, 10, 9, 8, 0),
        datetime(2026, 10, 16, 17, 5),
        tally(10, 2),
        ("m",),
    )
    head, body = charts.sessions_tab(ledger_of(models={"m": tally(10, 2)}, sessions=[row]), 100)

    assert "Began" in text_of(head[1]) and "Updated" in text_of(head[1])
    line = text_of(body[0])
    assert "Oct  9 08:00" in line and "Oct 16 17:05" in line


def test_a_narrow_sessions_tab_keeps_the_last_change_and_drops_the_start():
    """A row is still a row at forty columns; the created time is what gives way, not the order's own time."""
    from datetime import datetime

    from zettcode.sdk.types import SessionTotals

    row = SessionTotals("s", "A title", datetime(2026, 10, 9), datetime(2026, 10, 16), tally(10, 2), ("m",))
    head, body = charts.sessions_tab(ledger_of(models={"m": tally(10, 2)}, sessions=[row]), 40)

    assert "Updated" in text_of(head[1]) and "Began" not in text_of(head[1])
    assert "Oct 16" in text_of(body[0]) and "Oct  9" not in text_of(body[0])


def test_a_truncated_cjk_title_does_not_push_the_token_columns_out_by_a_column():
    """The columns are read down the page: a row one column wide breaks the table.

    A title cut at the column budget used to come out one column wider when the character at
    the cut was a wide one, because the truncation kept it whole and then appended the ellipsis.
    Every CJK title longer than its column shifted the bars and the counts of that row right by
    one, which is why some rows lined up and others did not.
    """
    from datetime import datetime

    from zettcode.sdk.types import SessionTotals
    from zettcode.tui.render import display_width

    def row(session_id: str, title: str) -> SessionTotals:
        return SessionTotals(session_id, title, datetime(2026, 10, 9), datetime(2026, 10, 16), tally(10, 2), ("m",))

    rows = [row("a", "A title long enough to be cut"), row("b", "档位切换滑动动画代码很长很长")]
    _, body = charts.sessions_tab(ledger_of(models={"m": tally(10, 2)}, sessions=rows), 60)
    lines = [text_of(line) for line in body]

    assert "…" in lines[0] and "…" in lines[1], "both titles were cut, which is the point"
    # A code-point index counts a CJK title by characters, not columns, so measure the columns.
    starts = [display_width(line[: line.index("10")]) for line in lines]
    assert starts[0] == starts[1], "the counts start in the same column"


def test_the_sessions_tab_shows_each_sessions_cache_hit_rate():
    """Cached input is most of a long session's input; the row says how much, to two decimals."""
    from datetime import datetime

    from zettcode.sdk.types import SessionTotals

    row = SessionTotals("s", "A title", datetime(2026, 10, 9), datetime(2026, 10, 16), Totals(1, 1000, 10, 750), ("m",))
    head, body = charts.sessions_tab(ledger_of(models={"m": row.tokens}, sessions=[row]), 100)

    assert "Cached" in text_of(head[1])
    assert "75.00%" in text_of(body[0])


def test_a_cache_rate_is_written_to_two_decimals_everywhere_in_usage():
    from datetime import datetime

    from zettcode.sdk.types import SessionTotals

    row = SessionTotals("s", "A title", datetime(2026, 10, 9), datetime(2026, 10, 16), Totals(1, 1000, 10, 0), ("m",))
    ledger = ledger_of(models={"m": row.tokens}, sessions=[row])
    head, body = charts.sessions_tab(ledger, 100)
    models_head, models_body = charts.models_tab(ledger, 100)

    assert "0.00%" in text_of(head[0]), "the workspace total"
    assert "0.00%" in text_of(body[0]), "the session"
    assert any("0.00% cached" in text_of(line) for line in models_body), "each model"


def test_the_cache_column_gives_way_before_the_counts_on_a_narrow_page():
    """Two decimals need seven columns; the row keeps its counts and its title instead."""
    from datetime import datetime

    from zettcode.sdk.types import SessionTotals

    row = SessionTotals("s", "A title", datetime(2026, 10, 9), datetime(2026, 10, 16), Totals(1, 1000, 10, 750), ("m",))
    head, _ = charts.sessions_tab(ledger_of(models={"m": row.tokens}, sessions=[row]), 40)

    assert "Cached" not in text_of(head[1]), "no room for it here"
    assert "Input" in text_of(head[1]) and "Output" in text_of(head[1])


def test_the_cache_column_draws_a_bar_that_can_be_compared_across_rows():
    """A share is read against a whole, so the bar is 0-100% and not scaled to the busiest row."""
    from datetime import datetime

    from zettcode.sdk.types import SessionTotals

    def session(name: str, cached: int) -> SessionTotals:
        return SessionTotals(
            name, name, datetime(2026, 10, 9), datetime(2026, 10, 16), Totals(1, 1000, 10, cached), ("m",)
        )

    rows = [session("none", 0), session("half", 500), session("most", 900), session("all", 1000)]
    _, body = charts.sessions_tab(ledger_of(models={"m": Totals(4, 4000, 40, 2400)}, sessions=rows), 120)

    def cached_bar(line) -> str:
        """The cells of the bar that is painted with the cache role, filled part only."""
        return "".join(piece for piece, role in line if role == "cached")

    bars = {
        name: cached_bar(line) for line in body for name in ("none", "half", "most", "all") if name in text_of(line)
    }
    assert bars["none"] == "" and bars["half"] != "" and len(bars["all"]) == charts.cache_track(14)
    assert len(bars["none"]) < len(bars["half"]) < len(bars["most"]) <= len(bars["all"])
    assert len(bars["half"]) * 2 == len(bars["all"]), "half is half the bar"
    assert all(charts.line_width(line) <= 120 for line in body)


def test_the_cache_bar_goes_with_the_other_bars_on_a_page_without_room_for_them():
    from datetime import datetime

    from zettcode.sdk.types import SessionTotals

    row = SessionTotals("s", "A title", datetime(2026, 10, 9), datetime(2026, 10, 16), Totals(1, 1000, 10, 750), ("m",))
    _, body = charts.sessions_tab(ledger_of(models={"m": row.tokens}, sessions=[row]), 80)

    assert not any(role == "cached" for _, role in body[0]), "numbers alone, as for the token bars"
    assert "75.00%" in text_of(body[0])
