"""The ``/context`` page: how the window and the sources are drawn, and how its keys move."""

from __future__ import annotations

import pytest

from zettcode.app.agent.extensions.context import SOURCES, ContextReport, ContextShare
from zettcode.app.ui.widgets import ContextPage
from zettcode.app.ui.widgets import context_charts as charts
from zettcode.tui import DARK, LIGHT, TuiApp
from zettcode.tui.render.text import display_width
from zettcode.tui.testing import Harness

SHARES = (
    ContextShare("System prompt", 260, 1),
    ContextShare("Environment notes", 740, 2),
    ContextShare("Tool schemas", 1520, 9),
    ContextShare("User messages", 90, 3),
    ContextShare("Assistant messages", 3100, 12),
    ContextShare("Tool output", 20216, 17),
)


def report_of(shares=SHARES, *, window: int = 200_000, reported: int | None = None, partial: bool = False):
    return ContextReport(
        window=window, measured_by="tiktoken", shares=tuple(shares), partial=partial, reported=reported
    )


def text_of(line) -> str:
    return "".join(piece for piece, _ in line)


def texts(lines) -> list[str]:
    return [text_of(line) for line in lines]


# -- dividing a bar -----------------------------------------------------------
@pytest.mark.parametrize("cells", [1, 7, 30, 72])
def test_a_divided_bar_is_exactly_as_wide_as_the_bar(cells):
    """Rounding each part alone leaves the bar a cell short or long; the parts must add up."""
    parts = charts.allocate([260, 740, 1520, 90, 3100, 20216], cells)

    assert sum(parts) == cells or cells < 6


def test_a_source_that_is_there_keeps_a_cell_however_small_and_the_largest_pays():
    parts = charts.allocate([1, 1, 1, 100_000], 20)

    assert parts[:3] == [1, 1, 1], "three tokens are still seen next to a hundred thousand"
    assert parts[3] == 17 and sum(parts) == 20


def test_a_source_with_nothing_has_no_cell_and_an_empty_whole_has_none_at_all():
    assert charts.allocate([0, 50, 50], 10) == [0, 5, 5]
    assert charts.allocate([0, 0], 10) == [0, 0]
    assert charts.allocate([5, 5], 0) == [0, 0]


# -- the window ---------------------------------------------------------------
@pytest.mark.parametrize(
    ("used", "role"),
    [
        (0, "gauge_calm"),
        (119_999, "gauge_calm"),
        (120_000, "gauge_warm"),
        (159_999, "gauge_warm"),
        (160_000, "gauge_hot"),
    ],
)
def test_the_gauge_warms_three_quarters_of_the_way_to_compaction_and_turns_hot_at_it(used, role):
    assert charts.gauge_role(used, 160_000) == role


def test_the_gauge_is_filled_by_how_full_the_window_is_and_says_so_in_numbers():
    lines = charts.window_lines(report_of(reported=100_000), 160_000, 72)

    assert "100,000 / 200,000 tokens" in text_of(lines[0]) and "50.0% full" in text_of(lines[0])
    filled = "".join(piece for piece, role in lines[1] if role.startswith("gauge_"))
    assert len(filled) == 36, "half the window is half of the 72 cells"


def test_the_mark_sits_under_the_cell_where_compaction_starts():
    lines = charts.window_lines(report_of(), 160_000, 72)
    mark = texts(lines)[2]

    assert "compacts at 160,000 tokens (80.0%)" in mark
    assert mark.index(charts.MARK) == round(0.8 * 72) - 1, "under the last cell before the point"


def test_a_mark_too_near_the_right_edge_for_its_words_puts_them_to_its_left():
    mark = texts(charts.window_lines(report_of(), 190_000, 72))[2]

    assert mark.rstrip().endswith(charts.MARK) and "compacts at 190,000" in mark
    assert display_width(mark.rstrip()) <= 72


def test_the_three_numbers_add_up_and_each_is_a_share_of_the_window():
    rows = texts(charts.window_lines(report_of(reported=40_000), 160_000, 72))

    used = next(row for row in rows if row.startswith("Used"))
    until = next(row for row in rows if row.startswith("Until compaction"))
    free = next(row for row in rows if row.startswith("Free in window"))
    assert "40,000" in used and "20.0%" in used
    assert "120,000" in until and "60.0%" in until
    assert "160,000" in free and "80.0%" in free


def test_past_the_compaction_point_nothing_is_left_before_it_and_the_gauge_is_hot():
    lines = charts.window_lines(report_of(reported=170_000), 160_000, 72)

    until = next(text_of(line) for line in lines if text_of(line).startswith("Until compaction"))
    assert until.split()[2] == "0"
    assert {role for _, role in lines[1] if role.startswith("gauge_")} == {"gauge_hot"}


def test_a_model_that_is_never_compacted_has_no_mark_and_no_line_for_it():
    lines = charts.window_lines(report_of(reported=100_000), None, 72)

    assert charts.MARK not in "".join(texts(lines))
    assert not any(text.startswith("Until compaction") for text in texts(lines))


# -- where the tokens went ----------------------------------------------------
def test_the_stacked_bar_is_divided_in_source_order_and_each_source_has_its_own_colour():
    bar = charts.makeup_lines(report_of(), 72)[1]

    assert [role for _, role in bar] == [charts.SOURCE_ROLES[share.name] for share in SHARES]
    assert sum(len(piece) for piece, _ in bar) == 72
    assert len({charts.SOURCE_ROLES[name] for name in SOURCES}) == len(SOURCES)


def test_each_source_has_a_row_with_its_tokens_its_share_and_its_count():
    rows = {
        text[2:].split("  ")[0]: text
        for text in texts(charts.makeup_lines(report_of(), 100))
        if text and text[0] in "■·"
    }

    assert list(rows) == [share.name for share in SHARES]
    assert "20,216" in rows["Tool output"] and "78.0%" in rows["Tool output"]
    assert rows["Tool output"].rstrip().endswith("17")


def test_a_row_bar_is_the_share_of_what_was_counted_and_not_scaled_to_the_biggest():
    lines = charts.makeup_lines(report_of(), 100)
    biggest = next(line for line in lines if text_of(line).startswith("■ Tool output"))
    filled = "".join(piece for piece, role in biggest if role == charts.SOURCE_ROLES["Tool output"])

    # 78.0% of a 32-cell track, not all of it: the bar is a share, so it reads as one.
    assert 24 <= len(filled.strip("\u00a0")) - 1 <= 26


def test_what_only_a_request_carries_is_a_pending_row_until_one_is_sent():
    shares = [share for share in SHARES if share.name not in ("Environment notes", "Tool schemas")]
    rows = texts(charts.makeup_lines(report_of(shares, partial=True), 100))

    pending = [row for row in rows if "pending" in row]
    assert [row[2:].split("  ")[0] for row in pending] == ["Environment notes", "Tool schemas"]
    assert all("\u2014" in row for row in pending)
    assert not any("pending" in row for row in texts(charts.makeup_lines(report_of(), 100)))


@pytest.mark.parametrize("width", [30, 38, 43, 44, 60, 80, 120, 200])
def test_no_line_is_wider_than_the_page(width):
    report = report_of(reported=25_926, partial=True)

    for line in charts.context_lines(report, 160_000, width):
        assert display_width(text_of(line)) <= width, (width, text_of(line))


def test_the_item_count_is_the_first_thing_a_narrow_page_gives_up():
    wide = "\n".join(texts(charts.makeup_lines(report_of(), 100)))
    narrow = "\n".join(texts(charts.makeup_lines(report_of(), 40)))

    assert "Items" in wide and "Items" not in narrow
    assert "20,216" in narrow and "78.0%" in narrow


# -- who counted -------------------------------------------------------------
def test_a_provider_total_is_divided_between_the_sources_by_their_local_proportions():
    """The local count gives proportions only: each row is its share of what the provider billed."""
    report = report_of(reported=51_852)  # twice what was counted here

    assert charts.tokens_by_source(report)["Tool output"] == 40_432
    assert charts.tokens_by_source(report)["System prompt"] == 520
    row = next(text for text in texts(charts.makeup_lines(report, 100)) if text.startswith("■ Tool output"))
    assert "40,432" in row and "78.0%" in row, "the share is the same; the tokens are the provider's"


@pytest.mark.parametrize("reported", [30_000, 25_927, 26_001, 999_999, 7_777])
def test_the_rows_add_up_to_the_provider_total_exactly_however_the_proportions_round(reported):
    parts = charts.tokens_by_source(report_of(reported=reported))

    assert sum(parts.values()) == reported
    assert all(count >= 1 for count in parts.values()), "a source that is there keeps a token"


def test_without_a_provider_total_the_rows_are_the_local_counts_as_counted():
    parts = charts.tokens_by_source(report_of())

    assert parts == {share.name: share.tokens for share in SHARES}


def test_the_note_says_whose_total_it_is_and_that_the_split_is_worked_out_locally():
    notes = " ".join(texts(charts.note_lines(report_of(reported=30_000))))

    assert "provider" in notes and "local" in notes
    assert "%" not in notes, "no coverage figure to explain"


def test_a_total_the_provider_has_not_reported_is_counted_here_and_says_so():
    notes = " ".join(texts(charts.note_lines(report_of())))

    assert "has not reported" in notes


def test_the_counters_name_is_never_on_the_page_but_an_estimate_is_admitted():
    exact = report_of(reported=30_000)
    guess = ContextReport(window=200_000, measured_by="~4 chars/token", shares=SHARES)

    for report in (exact, guess):
        page = "\n".join(texts(charts.context_lines(report, 160_000, 100)))
        assert "tiktoken" not in page and "cl100k" not in page and "chars/token" not in page
    assert "estimates" in "\n".join(texts(charts.note_lines(guess)))
    assert "estimates" not in "\n".join(texts(charts.note_lines(exact)))


def test_a_share_of_nothing_is_a_dash_and_not_a_division_by_zero():
    assert charts.percent(5, 0) == "\u2014"
    assert charts.percent(1, 8) == "12.5%"


# -- the page ----------------------------------------------------------------
@pytest.mark.parametrize("theme", [DARK, LIGHT])
def test_the_sources_are_seven_distinct_colours_and_the_gauge_three_in_either_theme(theme):
    page = ContextPage(report_of())
    app = TuiApp(page, width=80, height=30, theme=theme)
    app.mount()

    sources = {page.style_of(role).foreground for role in charts.SOURCE_ROLES.values()}
    gauge = {page.style_of(role).foreground for role in ("gauge_calm", "gauge_warm", "gauge_hot")}

    assert len(sources) == len(SOURCES)
    assert len(gauge) == 3


def test_the_page_names_the_model_the_file_and_the_window():
    page = ContextPage(report_of(reported=25_926), model="claude-opus-4-5", trigger=160_000)
    text = Harness(page, width=100, height=34).render().text

    assert "Context" in text and "claude-opus-4-5" in text
    assert "25,926 / 200,000 tokens" in text and "compacts at 160,000" in text
    assert page.title == "Context  25,926 / 200,000 tokens"


def test_escape_and_q_leave_through_the_owners_callback():
    left: list[str] = []
    harness = Harness(ContextPage(report_of(), on_cancel=lambda: left.append("closed")), width=60, height=14)

    harness.press("escape")
    harness.write("q")

    assert left == ["closed", "closed"]


def test_a_page_too_short_for_everything_scrolls_and_never_past_its_ends():
    harness = Harness(ContextPage(report_of(), trigger=160_000), width=80, height=12)
    page = harness.root
    harness.render()

    assert "scroll" in harness.render().text, "the footer says there is more"
    harness.press("down")
    harness.press("down")
    assert page.offset == 2
    harness.press("end")
    furthest = page.offset
    harness.press("down")
    assert page.offset == furthest
    harness.press("home")
    harness.press("up")
    assert page.offset == 0


def test_while_a_source_is_unknown_the_provider_total_is_not_handed_to_the_known_rows():
    """The provider's number is for the whole request. Dividing it between the sources that can be
    seen would give them the tokens of the ones that cannot: a resumed session showed its assistant
    messages as nine tenths of a request that mostly was tool schemas."""
    known = [share for share in SHARES if share.name not in ("Environment notes", "Tool schemas")]
    report = report_of(known, reported=60_000, partial=True)

    assert charts.tokens_by_source(report) == {share.name: share.tokens for share in known}
    lines = charts.makeup_lines(report, 100)
    assert f"{report.measured:,} tokens" in text_of(lines[0]) and "60,000" not in text_of(lines[0])
    note = " ".join(texts(charts.note_lines(report)))
    assert "do not add up" in note and "until a request has been sent" in note


def test_once_every_source_is_there_the_provider_total_is_divided_again():
    report = report_of(reported=60_000, partial=False)

    assert sum(charts.tokens_by_source(report).values()) == 60_000
    assert "do not add up" not in " ".join(texts(charts.note_lines(report)))


def test_a_total_nobody_reported_and_a_source_still_unknown_says_what_is_missing():
    note = " ".join(texts(charts.note_lines(report_of(partial=True))))

    assert "not counted until a request has been sent" in note
