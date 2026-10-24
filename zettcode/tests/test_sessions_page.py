"""The ``/resume`` panel: each session with how many entries it holds and what it cost."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from zettcode.app.ui.widgets import SessionsPage
from zettcode.app.ui.widgets.sessions_page import GAP, MARKER, MIN_TITLE, NONE
from zettcode.engine.storage import SessionInfo, SessionStats
from zettcode.tui import DARK, Rect
from zettcode.tui.core.events import KeyEvent
from zettcode.tui.render import display_width
from zettcode.tui.testing.snapshot import render_block

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def session(identity: str, title: str | None, ago: timedelta) -> SessionInfo:
    return SessionInfo(identity, title, NOW - ago, NOW - ago)


SESSIONS = [
    session("01a1010fabcdef", "Fix the parser crash", timedelta(minutes=3)),
    session("01a10119abcdef", None, timedelta(hours=17)),
    session("01a10116abcdef", "Flask \u5b9e\u73b0 Python \u670d\u52a1\u5668", timedelta(days=2)),
]

STATS = {
    "01a1010fabcdef": SessionStats(
        "01a1010fabcdef", entries=41, requests=6, input_tokens=12_345, output_tokens=1_234, cache_read_tokens=10_740
    ),
    "01a10119abcdef": SessionStats("01a10119abcdef", entries=3, requests=1, input_tokens=3_900, output_tokens=2),
    "01a10116abcdef": SessionStats("01a10116abcdef"),
}


def page(stats=STATS, sessions=SESSIONS, **options) -> SessionsPage:
    return SessionsPage(
        sessions,
        stats=stats,
        on_select=options.pop("on_select", lambda _: None),
        on_cancel=lambda: None,
        now=NOW,
        **options,
    )


def rows_of(panel: SessionsPage) -> list[str]:
    """Each row as the list draws it: the label, then the description, the way the two are laid side by side."""
    column = max(display_width(item.label) for item in panel.list.items)
    return [
        item.label + " " * (column - display_width(item.label) + GAP) + item.description for item in panel.list.items
    ]


# -- what a row says -------------------------------------------------------------------------------


def test_a_row_shows_when_the_session_changed_how_long_it_is_what_it_cost_and_its_id():
    first, second, third = rows_of(page())

    assert "3m ago" in first and "41" in first and "12.3K" in first and "1.23K" in first
    assert "87.00%" in first, "10,740 of 12,345 input tokens came from the cache, to two decimals"
    assert first.rstrip().endswith("01a1010f")
    assert second.rstrip().endswith("01a10119") and "3.90K" in second and " 0.00%" in second
    assert "New session" in second


def test_the_cached_share_is_a_dash_before_there_was_any_input():
    third = rows_of(page())[2]

    assert third.count(NONE) == 1, "the three counts are zeros; only the share has nothing to be a share of"
    assert third.split()[-2] == NONE
    assert "2d ago" in third and third.rstrip().endswith("01a10116")


def test_a_session_missing_from_the_totals_is_a_row_of_dashes_and_the_others_keep_their_figures():
    without_one = dict(STATS)
    del without_one["01a1010fabcdef"]

    first, second, _ = rows_of(page(without_one))

    assert first.count(NONE) == 4 and "12.3K" not in first
    assert "3.90K" in second


def test_without_totals_at_all_the_panel_is_the_age_and_the_id_it_always_was():
    panel = page(None)

    heading = panel.subtitle
    assert heading is not None and "Entries" not in heading and "Input" not in heading
    assert "Updated" in heading and heading.rstrip().endswith("ID")
    assert all(NONE not in row for row in rows_of(panel))
    assert rows_of(panel)[0].rstrip().endswith("01a1010f")


def test_a_heading_names_the_figures_and_stands_over_them():
    panel = page()
    heading = panel.subtitle
    assert heading is not None
    rows = rows_of(panel)

    for name in ("Updated", "Entries", "Input", "Output", "Cached", "ID"):
        assert name in heading
    # Right-aligned figures end under the end of their heading; the id starts under its own. The list draws a
    # marker of MARKER columns before each label, which the rows above are without.
    for name, sample in (("Updated", "3m ago"), ("Entries", "41"), ("Input", "12.3K"), ("Output", "1.23K")):
        end = heading.index(name) + len(name)
        assert MARKER + rows[0].index(sample) + len(sample) == end, name
    assert MARKER + rows[0].index("01a1010f") == heading.index("ID")


def test_rows_are_numbered_and_a_wide_title_is_measured_in_columns_not_characters():
    rows = rows_of(page())

    assert [item.label[:3] for item in page().list.items] == ["1. ", "2. ", "3. "]
    # Every figure starts in one column however wide a title is (the third is Chinese).
    assert len({display_width(row[: row.index("ago")]) for row in rows}) == 1


# -- fitting the width ------------------------------------------------------------------------------


def fitted(panel: SessionsPage, width: int) -> tuple[list[str], str]:
    items, heading = panel.arrange(width)
    column = max(display_width(item.label) for item in items)
    return [item.label + " " * (column - display_width(item.label) + GAP) + item.description for item in items], heading


@pytest.mark.parametrize("width", [20, 30, 40, 50, 60, 70, 80, 100, 140])
def test_no_row_and_no_heading_is_wider_than_the_list_it_is_made_for(width: int):
    rows, heading = fitted(page(), width)

    assert all(display_width(row) <= max(width, MARKER + GAP + 4) for row in rows + [heading])


def test_the_columns_on_the_right_are_given_up_before_the_title_is_cut():
    panel = page()
    order = ["ID", "Cached", "Output", "Input", "Entries", "Updated"]
    kept = []
    for width in range(110, 24, -2):
        _, heading = fitted(panel, width)
        kept.append([name for name in order[::-1] if name in heading])
    shown = [len(names) for names in kept]

    assert shown == sorted(shown, reverse=True), "narrower never shows more"
    assert shown[0] == 6 and shown[-1] >= 1
    # Always the leftmost columns that stay: a column never survives the loss of one before it.
    names = ["Updated", "Entries", "Input", "Output", "Cached", "ID"]
    assert all(names[: len(columns)] == columns for columns in kept)


def test_a_title_is_kept_whole_while_there_is_room_and_cut_with_an_ellipsis_when_there_is_not():
    long = [
        session("01a1010fabcdef", "An unusually long title that goes on and on and on and on", timedelta(minutes=1))
    ]
    panel = SessionsPage(long, stats={}, on_select=lambda _: None, on_cancel=lambda: None, now=NOW)

    roomy, _ = panel.arrange(200)
    tight, _ = panel.arrange(60)

    assert roomy[0].label.endswith("on and on")
    assert tight[0].label.endswith("\u2026") and display_width(tight[0].label) < display_width(roomy[0].label)


def test_the_title_keeps_a_readable_width_by_giving_up_columns_first():
    panel = page()

    items, heading = panel.arrange(60)

    widest = max(display_width(f"{n}. {s.title or 'New session'}") for n, s in enumerate(SESSIONS, 1))
    title_room = 60 - MARKER - GAP - sum(len(column) for column in heading.split())  # a rough bound
    assert max(display_width(item.label) for item in items) >= min(MIN_TITLE, widest)
    assert title_room > 0


# -- the page ---------------------------------------------------------------------------------------


def test_laying_out_at_a_new_width_makes_the_rows_again_and_keeps_the_highlighted_one():
    panel = page()
    panel.list.select(2, notify=False)
    wide = panel.list.items

    panel.layout(Rect(0, 0, 70, 14))
    narrow = panel.list.items

    assert panel.list.selected == 2
    assert wide != narrow and "Cached" not in (panel.subtitle or "") or "ID" not in (panel.subtitle or "")
    panel.layout(Rect(0, 0, 70, 14))
    assert panel.list.items is narrow, "the same width is not made again"


def _hues(row: int, width: int = 110) -> dict[str, str | None]:
    """The foreground of the first character of each word on one screen row of the panel."""
    from zettcode.tui.core.app import TuiApp

    app = TuiApp(page(), width=width, height=10, theme=DARK)
    app.mount()
    cells = [cell for cell in app.render().cells[row] if not cell.continuation]
    words: dict[str, str | None] = {}
    for x, cell in enumerate(cells):
        if cell.character != " " and (x == 0 or cells[x - 1].character == " "):
            word = "".join(c.character for c in cells[x:]).split(" ")[0]
            words[word] = cell.style.foreground
    return words


def test_each_figure_column_has_its_own_colour_and_its_heading_is_a_dimmer_shade_of_it():
    heading, first = _hues(2), _hues(4)

    assert first["12.3K"] == DARK.accent
    assert first["1.23K"] == DARK.warning
    assert first["01a1010f"] == DARK.muted
    assert len({first["12.3K"], first["1.23K"], first["87.00%"]}) == 3
    assert len({heading["Input"], heading["Output"], heading["Cached"]}) == 3
    assert heading["Input"] != first["12.3K"], "the heading stands back from the figures it names"


def test_the_cached_column_is_dimmer_the_less_the_cache_did():
    high, low = _hues(4)["87.00%"], _hues(5)["0.00%"]

    assert high != low, "87% and 0% must not read as the same colour"


def test_the_panel_draws_its_heading_its_rows_and_the_hint():
    text = render_block(page(), width=110, height=10, theme=DARK)

    assert "Sessions" in text and "Updated" in text and "Cached" in text
    assert "Fix the parser crash" in text and "12.3K" in text and "enter open" in text


def test_enter_commits_the_highlighted_sessions_whole_id_and_escape_gives_the_panel_up():
    chosen: list[str] = []
    cancelled: list[bool] = []
    panel = SessionsPage(
        SESSIONS, stats=STATS, on_select=chosen.append, on_cancel=lambda: cancelled.append(True), now=NOW
    )
    panel.list.select(1)

    panel.list.activate()
    panel.capture_event(KeyEvent(key="escape"), None)  # type: ignore[arg-type]

    assert chosen == ["01a10119abcdef"] and cancelled == [True]


def test_an_empty_list_is_still_a_page():
    panel = SessionsPage([], stats={}, on_select=lambda _: None, on_cancel=lambda: None, now=NOW)

    panel.layout(Rect(0, 0, 80, 14))

    assert panel.list.items == ()
