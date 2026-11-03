"""The ``/resume`` panel: each session with how many entries it holds and what it cost."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from zettcode.app.ui.widgets import SessionsPage
from zettcode.app.ui.widgets.sessions_page import GAP, KEYS, MARKER, MIN_TITLE, NONE
from zettcode.sdk.types import SessionInfo
from zettcode.sdk.types import SessionStatsInfo as SessionStats
from zettcode.tui import DARK, Rect
from zettcode.tui.core.events import KeyEvent, PasteEvent, TextEvent
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

    heading = panel.heading
    assert "Entries" not in heading and "Input" not in heading
    assert "Updated" in heading and heading.rstrip().endswith("ID")
    assert all(NONE not in row for row in rows_of(panel))
    assert rows_of(panel)[0].rstrip().endswith("01a1010f")


def test_a_heading_names_the_figures_and_stands_over_them():
    panel = page()
    heading = panel.heading
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
    items = panel.arrange(width)
    column = max(display_width(item.label) for item in items)
    return [
        item.label + " " * (column - display_width(item.label) + GAP) + item.description for item in items
    ], panel.heading


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

    roomy = panel.arrange(200)
    tight = panel.arrange(60)

    assert roomy[0].label.endswith("on and on")
    assert tight[0].label.endswith("\u2026") and display_width(tight[0].label) < display_width(roomy[0].label)


def test_the_title_keeps_a_readable_width_by_giving_up_columns_first():
    panel = page()

    items = panel.arrange(60)
    heading = panel.heading

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
    assert wide != narrow and ("Cached" not in panel.heading or "ID" not in panel.heading)
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
    heading, first = _hues(5), _hues(6)

    assert first["12.3K"] == DARK.accent
    assert first["1.23K"] == DARK.warning
    assert first["01a1010f"] == DARK.muted
    assert len({first["12.3K"], first["1.23K"], first["87.00%"]}) == 3
    assert len({heading["Input"], heading["Output"], heading["Cached"]}) == 3
    assert heading["Input"] != first["12.3K"], "the heading stands back from the figures it names"


def test_the_cached_column_is_dimmer_the_less_the_cache_did():
    high, low = _hues(6)["87.00%"], _hues(7)["0.00%"]

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


# -- searching --------------------------------------------------------------------------------------


def typed(panel: SessionsPage, text: str) -> None:
    """Type into the panel one character at a time, as a terminal delivers it."""
    for character in text:
        panel.capture_event(TextEvent(text=character), None)  # type: ignore[arg-type]


def test_typing_narrows_the_rows_to_the_sessions_whose_title_holds_it():
    panel = page()
    panel.layout(Rect(0, 0, 110, 14))

    typed(panel, "parser")

    assert [item.value for item in panel.list.items] == ["01a1010fabcdef"]
    assert panel.query == "parser"


def test_the_search_reads_case_folded_and_finds_a_session_by_any_part_of_its_id():
    panel = page()

    typed(panel, "FLASK")
    assert [item.value for item in panel.list.items] == ["01a10116abcdef"]

    panel.capture_event(KeyEvent(key="escape"), None)  # type: ignore[arg-type]
    typed(panel, "01a10119")
    assert [item.value for item in panel.list.items] == ["01a10119abcdef"]


def test_backspace_widens_the_list_and_an_empty_box_is_the_store_order_again():
    panel = page()
    typed(panel, "01a1011")
    assert [item.value for item in panel.list.items] == ["01a10119abcdef", "01a10116abcdef"]

    panel.capture_event(KeyEvent(key="backspace"), None)  # type: ignore[arg-type]
    assert panel.query == "01a101"
    assert [item.value for item in panel.list.items] == [session.id for session in SESSIONS]

    for _ in range(len(panel.query)):
        panel.capture_event(KeyEvent(key="backspace"), None)  # type: ignore[arg-type]
    assert panel.query == ""
    assert [item.value for item in panel.list.items] == [session.id for session in SESSIONS]


def test_escape_clears_the_search_before_it_gives_the_page_up():
    cancelled: list[bool] = []
    panel = SessionsPage(
        SESSIONS, stats=STATS, on_select=lambda _: None, on_cancel=lambda: cancelled.append(True), now=NOW
    )
    typed(panel, "flask")

    assert panel.capture_event(KeyEvent(key="escape"), None) is True  # type: ignore[arg-type]
    assert panel.query == "" and panel.list.items and cancelled == []

    assert panel.capture_event(KeyEvent(key="escape"), None) is True  # type: ignore[arg-type]
    assert cancelled == [True]


def test_a_search_pasted_in_one_go_is_read_as_one_line():
    panel = page()

    panel.capture_event(PasteEvent(text="flask\n"), None)  # type: ignore[arg-type]

    assert panel.query == "flask"
    assert [item.value for item in panel.list.items] == ["01a10116abcdef"]


def test_a_search_that_matches_nothing_says_so_where_the_rows_would_be():
    panel = page()
    typed(panel, "nothing here")

    text = render_block(panel, width=110, height=14, theme=DARK)

    assert "No session matches \u201cnothing here\u201d" in text


def test_the_panel_shows_the_box_and_says_that_escape_clears_it_while_searching():
    empty = render_block(page(), width=110, height=16, theme=DARK)

    assert "search by title or id" in empty
    assert "type to search" in empty and "esc back" in empty

    searching_panel = page()
    typed(searching_panel, "fix")
    searching = render_block(searching_panel, width=110, height=16, theme=DARK)

    assert "\u2502 fix" in searching
    assert "esc clear" in searching and "esc back" not in searching


def test_the_search_field_is_a_rounded_box_with_its_label_and_a_caret_where_the_keyboard_is():
    quiet_panel = page()
    typed(quiet_panel, "fix")
    quiet = render_block(quiet_panel, width=110, height=16, theme=DARK)

    assert "\u256d\u2500 Search \u2500" in quiet
    assert "\u2570" in quiet and "\u256f" in quiet
    assert "\u2502 fix " in quiet and "\u2588" not in quiet, "the list has the keyboard, so no cursor"

    focused_panel = page()
    typed(focused_panel, "fix")
    focused_panel.focused = True
    focused = render_block(focused_panel, width=110, height=16, theme=DARK)

    assert "\u2502 fix\u2588" in focused, "the query sits inside the box with the block cursor after it"


def test_the_box_still_appears_on_a_terminal_narrow_enough_to_leave_the_label_out():
    panel = page()

    text = render_block(panel, width=12, height=16, theme=DARK)

    assert "\u256d" in text and "\u256f" in text
    assert "Search" not in text


def test_enter_in_the_box_belongs_to_the_panel_even_when_nothing_matches():
    panel = page()
    panel.focused = True
    typed(panel, "nothing here")
    assert panel.list.items == ()

    assert panel.capture_event(KeyEvent(key="enter"), None) is True, "the shell must not see the Enter"  # type: ignore[arg-type]


def test_a_query_of_only_spaces_is_no_query_at_all():
    cancelled: list[bool] = []
    panel = SessionsPage(
        SESSIONS, stats=STATS, on_select=lambda _: None, on_cancel=lambda: cancelled.append(True), now=NOW
    )

    typed(panel, " ")
    assert panel.query == "" and panel.footer == KEYS
    assert len(panel.list.items) == len(SESSIONS)

    panel.capture_event(KeyEvent(key="escape"), None)  # type: ignore[arg-type]
    assert cancelled == [True], "with nothing to clear, Escape closes the panel"

    spaced = page()
    typed(spaced, " ")
    typed(spaced, "fix")
    assert spaced.query == "fix"


def test_a_box_with_no_room_for_its_middle_is_not_drawn_outside_itself():
    for width in (4, 5):
        text = render_block(page(), width=width, height=16, theme=DARK)
        assert "\u2502" not in text and "\u256d" not in text, f"no box at width {width}"

    text = render_block(page(), width=6, height=16, theme=DARK)
    assert "\u256d\u256e" in text and "\u2570\u256f" in text


def test_a_page_too_short_for_the_heading_keeps_the_keys_and_does_not_overlap_them():
    shortest = render_block(page(), width=60, height=5, theme=DARK)
    assert "Sessions" in shortest and "esc back" in shortest
    assert "\u256d" not in shortest, "the box gives way to the keys rather than being painted over"

    short = render_block(page(), width=60, height=6, theme=DARK)
    assert "\u256d" in short and "Updated" not in short
    assert "esc back" in short

    taller = render_block(page(), width=60, height=7, theme=DARK)
    assert "Updated" in taller
    assert "esc back" in taller


def test_the_no_match_line_appears_only_when_its_row_is_above_the_keys():
    panel = page()
    typed(panel, "nothing here")

    tight = render_block(panel, width=60, height=7, theme=DARK)
    assert "No session matches" not in tight and "esc clear" in tight

    roomy_panel = page()
    typed(roomy_panel, "nothing here")
    roomy = render_block(roomy_panel, width=60, height=8, theme=DARK)
    assert "No session matches" in roomy and "esc clear" in roomy


def test_an_arrow_key_in_the_box_without_a_host_is_consumed_and_changes_nothing():
    panel = page()
    panel.focused = True
    typed(panel, "fix")

    assert panel.capture_event(KeyEvent(key="up"), None) is True  # type: ignore[arg-type]
    assert panel.query == "fix" and panel.focused
