"""Presenters turn entries into styled, width-bound lines."""

from dataclasses import replace

import pytest

from zettcode.app.agent.conversation.entries import (
    EntryKind,
    EntryStatus,
    MarkdownEntry,
    TextEntry,
    ThinkingEntry,
    ToolEntry,
    WaitEntry,
)
from zettcode.app.agent.conversation.presenters import (
    DEFAULT_PRESENTERS,
    AnnouncementPresenter,
    NoticePresenter,
    Presenter,
    Presenters,
    ThinkingPresenter,
    ToolPresenter,
    UserPresenter,
    WaitPresenter,
    WelcomePresenter,
    block_for,
    render_entry,
    tool_color,
)
from zettcode.app.agent.conversation.rows import COMPACTING_LABEL, PULSE_FRAMES, STOP_HINT
from zettcode.app.agent.conversation.transcript import Transcript
from zettcode.app.ui.widgets.transcript import TranscriptSource
from zettcode.tui import DARK, LIGHT, SEPARATOR, TextLine
from zettcode.tui.render import display_width


def _rows(source, width: int = 40) -> list[str]:
    """Return the text of every line a line source holds."""
    return [source.line(index, width).text for index in range(source.count(width))]


def test_every_kind_of_entry_has_exactly_one_presenter():
    """The enum and the registry cannot drift apart: a new kind with no presenter fails here.

    This is the whole of what "add a kind of row" asks of the registry — a member of
    :class:`EntryKind` and a presenter that names it — and it is checked for the
    enum rather than for a hand-written list of the kinds that existed on the day
    the test was written.
    """
    presented = [presenter.kind for presenter in DEFAULT_PRESENTERS.presenters]

    assert sorted(presented) == sorted(EntryKind), "every kind has a presenter, and no kind has two"
    assert all(isinstance(presenter, Presenter) for presenter in DEFAULT_PRESENTERS.presenters)


def test_each_entry_is_drawn_by_the_presenter_for_its_kind():
    entries = (
        (TextEntry(id=1, kind="welcome", text="hello"), WelcomePresenter),
        (TextEntry(id=2, kind="notice", text="saved"), NoticePresenter),
        (TextEntry(id=8, kind="announcement", text="Model changed from A to B."), AnnouncementPresenter),
        (TextEntry(id=3, kind="user", text="hello"), UserPresenter),
        (WaitEntry(id=4, started_at=0.0), WaitPresenter),
        (ThinkingEntry(id=5, text="reasoning", expanded=True), ThinkingPresenter),
        (ToolEntry(id=6, call_id="call-1", tool="read_file", title="Read app.py", text="content"), ToolPresenter),
    )
    for entry, presenter in entries:
        assert type(DEFAULT_PRESENTERS.for_entry(entry)) is presenter, entry.kind
        assert render_entry(entry, 40, DARK, 0)

    for kind in (EntryKind.ANSWER, EntryKind.MESSAGE):
        markdown = MarkdownEntry(id=9, kind=kind)
        markdown.markdown.append("# heading")
        assert DEFAULT_PRESENTERS.for_entry(markdown).kind is kind
        assert render_entry(markdown, 40, DARK, 0), "Markdown can also say all its rows at once"


def test_a_later_presenter_for_a_kind_replaces_the_earlier_one():
    """One presenter per kind, so overriding a kind is a replacement and not a chain to order."""

    class CustomNotice(Presenter):
        kind = EntryKind.NOTICE

        def lines(self, entry, width, theme, frame):
            return [TextLine()]

    notice = TextEntry(id=1, kind="notice", text="handled")
    presenters = DEFAULT_PRESENTERS.replacing(CustomNotice())
    assert presenters.lines(notice, 40, DARK, 0) == [TextLine()]
    assert len(presenters.presenters) == len(DEFAULT_PRESENTERS.presenters), "replaced, not added"

    transcript = Transcript(presenters=presenters)
    transcript.notice("handled")
    source = TranscriptSource(transcript, theme=DARK)
    assert source.count(40) == 1

    transcript.presenters = DEFAULT_PRESENTERS
    assert source.count(40) == 2
    assert source.line(1, 40).text.strip() == "handled"


def test_a_kind_with_no_presenter_is_named_rather_than_guessed_at():
    nobody = Presenters(())

    with pytest.raises(ValueError, match="No presenter for a notice row"):
        nobody.lines(TextEntry(id=1, kind="notice", text="x"), 40, DARK, 0)


def test_an_announcement_is_centered_between_rules_and_clipped_on_small_screens():
    entry = TextEntry(id=1, kind="announcement", text="Model changed from GPT6-Sol to DeepSeek-Flash.")
    for width in (1, 2, 3, 8, 60):
        rows = render_entry(entry, width, DARK, 0)
        assert len(rows) == 3
        assert all(row.width <= width for row in rows)
        if width == 60:
            left, icon, text, right = rows[1].spans
            assert left.style.foreground == right.style.foreground == DARK.border
            assert icon.style.foreground == DARK.accent
            assert text.style.foreground == DARK.subtle
            assert "Model changed from GPT6-Sol to DeepSeek-Flash." in rows[1].text
            assert abs(left.width - right.width) <= 1
            # The gutter insets the left edge; the rule leaves the same two
            # cells free on the right, matching the header and status bar.
            assert rows[1].width == width - 2


def test_agent_components_keep_every_line_within_narrow_bounds():
    entries = (
        TextEntry(id=1, kind="notice", text="中文后面还有更多文字"),
        TextEntry(id=2, kind="user", text="中文后面还有更多文字"),
        WaitEntry(id=3, started_at=0.0, duration=12.3),
        ThinkingEntry(id=4, text="中文后面还有更多文字", expanded=True, duration=12.3),
        ToolEntry(
            id=5,
            call_id="call-5",
            tool="read_file",
            title="Read a very long file name",
            text="中文后面还有更多文字",
            duration=12.3,
        ),
    )
    for entry in entries:
        for width in (1, 2, 3, 8, 12, 20):
            rows = render_entry(entry, width, DARK, 0)
            assert all(display_width(row.text) <= width for row in rows), (entry.kind, width)


def test_blocks_use_theme_styles_and_preserve_user_surface():
    user = TextEntry(id=1, kind="user", text="hello")
    side = TextEntry(id=3, kind="user", text="what does parse() do?", side=True)
    notice = TextEntry(id=2, kind="notice", text="done")

    dark_user = render_entry(user, 20, DARK, 0)
    light_user = render_entry(user, 20, LIGHT, 0)
    dark_side = render_entry(side, 40, DARK, 0)
    light_side = render_entry(side, 40, LIGHT, 0)
    dark_notice = render_entry(notice, 20, DARK, 0)

    # The arrow sits flush left, in the column the composer's prompt is drawn in,
    # so the message lines up under the draft the reader is typing.
    assert dark_user[2].text.startswith("› hello")
    assert dark_user[2].spans[0].style.background == DARK.surface_alt
    assert light_user[2].spans[0].style.background == LIGHT.surface_alt
    # A side question keeps a surface of its own, so the row reads as a note
    # beside the conversation rather than as one of its turns.
    assert dark_side[2].text.startswith("btw › what does parse() do?")
    assert dark_side[2].spans[0].style.background == DARK.surface_side
    assert light_side[2].spans[0].style.background == LIGHT.surface_side
    assert dark_side[2].spans[0].style.foreground == DARK.subtle
    assert light_side[2].spans[0].style.foreground == LIGHT.subtle
    assert DARK.surface_side != DARK.surface_alt and LIGHT.surface_side != LIGHT.surface_alt
    assert dark_notice[1].spans[0].style.foreground == DARK.muted


def test_a_compaction_row_carries_its_own_label_and_timer():
    """The summarizer's row is a reasoning row under the label it was given."""
    running = ThinkingEntry(id=1, title=COMPACTING_LABEL, text="checkpoint", started_at=0.0)
    done = ThinkingEntry(id=2, title=COMPACTING_LABEL, text="checkpoint", expanded=True, duration=1.5)

    heading = render_entry(running, 40, DARK, 5)[1].text
    collapsed = render_entry(done, 40, DARK, 0)[1].text

    assert "Compacting" in heading and "working" in heading
    assert "Compacting" in collapsed and "1.5 s" in collapsed
    assert "Thinking" not in heading

    # A reasoning row is painted flat, like every row but the waiting one: the
    # same row at another frame is lit the same way.
    def brightness(frame: int) -> list[str | None]:
        return [span.style.foreground for span in render_entry(running, 40, DARK, frame)[1].spans]

    assert brightness(5) == brightness(9)


def test_the_waiting_row_puts_its_clock_and_the_stop_key_beside_the_word():
    """The aside is quiet ink the highlight never crosses, counted in whole seconds."""
    entry = WaitEntry(id=1, started_at=0.0, duration=3.4)

    line = render_entry(entry, 46, DARK, 0)[1]

    assert line.text.strip() == f"✦ Processing (3s {SEPARATOR} {STOP_HINT})"
    assert line.spans[-1].text == f" (3s {SEPARATOR} {STOP_HINT})"
    # Quiet ink, the same a notice uses, and no tenths of a second.
    assert line.spans[-1].style.foreground == DARK.muted
    for frame in range(PULSE_FRAMES):
        spans = render_entry(entry, 46, DARK, frame)[1].spans
        assert spans[-1] == line.spans[-1]
        assert all(span.style.foreground != DARK.text for span in spans[-1:])

    # Past a minute the same clock reads in minutes.
    later = WaitEntry(id=2, started_at=0.0, duration=100.4)
    assert render_entry(later, 46, DARK, 0)[1].text.strip().endswith(f"(1m 40s {SEPARATOR} {STOP_HINT})")


def test_every_row_draws_its_marker_in_the_gutter_and_its_content_beside_it():
    """Leading glyphs share one column, and every line of content shares the next.

    The user's arrow, the waiting row's sparkle, a tool's outcome, and the
    composer's prompt all sit in the gutter's first column, while a notice or an
    answer starts in the second — the column the text after those markers uses.
    """
    cases = {
        "user": (TextEntry(id=1, kind="user", text="hello"), True, "hello"),
        "waiting": (WaitEntry(id=2, started_at=0.0, duration=1.0), True, "Processing"),
        "settled": (
            WaitEntry(
                id=6,
                started_at=0.0,
                duration=1.0,
                status=EntryStatus.COMPLETED,
                text="Processed for 12s \u00b7 09:41",
            ),
            False,
            "Processed",
        ),
        "thinking": (ThinkingEntry(id=3, text="weighing", started_at=0.0, duration=1.0), True, "Thinking"),
        "tool": (
            ToolEntry(id=4, call_id="c", tool="read_file", title="Read app.py", started_at=0.0),
            True,
            "Read",
        ),
        "notice": (TextEntry(id=5, kind="notice", text="done"), False, "done"),
    }

    for name, (entry, opens_with_a_marker, content) in cases.items():
        source = block_for(entry, 40, DARK, 0)
        first = next(text for text in _rows(source) if text.strip())

        assert (first[0] != " ") is opens_with_a_marker, (name, first)
        assert first[1] == " ", (name, first)
        assert first.index(content) == 2, (name, first)


def test_a_settled_wait_row_is_a_muted_line():
    """Once the request is over the row stops sweeping and reads as a record."""
    settled = WaitEntry(id=1, started_at=0.0, duration=12.3, text="Processed for 12s · 09:41")
    settled.status = EntryStatus.COMPLETED

    (blank, line) = render_entry(settled, 40, DARK, 0)

    assert blank.spans == ()
    assert line.text.strip() == "Processed for 12s · 09:41"
    assert line.spans[0].style.foreground == DARK.muted

    # A row that was settled without a line still reports the time it measured.
    bare = WaitEntry(id=2, started_at=0.0, duration=12.3, status=EntryStatus.COMPLETED)
    assert render_entry(bare, 40, DARK, 0)[1].text.strip() == "Processed for 12s"


def test_only_the_waiting_row_moves():
    """The waiting row sweeps; a reasoning or running tool row paints flat.

    One moving row is what keeps the transcript readable while reasoning and
    tools are in flight at once, and it is also what keeps an animation step
    from rebuilding rows nothing has changed in.
    """
    thinking = ThinkingEntry(id=1, text="weighing the options", started_at=0.0)
    tool = ToolEntry(id=2, call_id="c1", tool="read_file", title="Read app.py", started_at=0.0)
    waiting = WaitEntry(id=3, started_at=0.0)

    def painted(entry, frame: int) -> list[tuple[str, tuple[object, ...]]]:
        return [
            (line.text, tuple((span.text, span.style) for span in line.spans))
            for line in render_entry(entry, 40, DARK, frame)
        ]

    assert painted(thinking, 0) == painted(thinking, 7)
    assert painted(tool, 0) == painted(tool, 7)
    assert painted(waiting, 0) != painted(waiting, 7)


def test_a_finished_row_without_a_recorded_duration_claims_no_time():
    """A restored row that lost its timing dropped the clock, not the run."""
    done = ThinkingEntry(id=1, title="Thinking", text="checked it", status=EntryStatus.COMPLETED)
    running = ThinkingEntry(id=2, title="Thinking", text="", started_at=0.0)

    heading = render_entry(done, 40, DARK, 0)[1].text

    assert "Thinking" in heading
    assert "working" not in heading and "0.0 s" not in heading
    assert "working" in render_entry(running, 40, DARK, 0)[1].text


def test_a_failure_notice_is_painted_as_an_error():
    """A notice is a remark; one the caller marked as an error is a failure."""
    failure = TextEntry(id=1, kind="notice", text="error: MCP unavailable (docs)", level="error")

    rows = render_entry(failure, 40, DARK, 0)

    assert rows[1].spans[0].style.foreground == DARK.error


def test_an_edit_row_paints_its_additions_and_deletions_in_their_own_colours():
    """A reader scans a list of edits for size; colour answers that faster than words.

    The counts sit outside the title for this reason: a row whose words are one
    string is painted in one colour, and `+12 -3` in the green and red a diff
    uses is the whole point of showing them.
    """
    entry = ToolEntry(
        id=1,
        call_id="call-1",
        tool="replace_in_file",
        title="Edited app.py (2 edits)",
        added=12,
        removed=3,
        status=EntryStatus.COMPLETED,
        text="Replaced 2 occurrences in app.py",
    )

    spans = [span for line in render_entry(entry, 80, DARK, 0) for span in line.spans]

    assert (next(span for span in spans if "12" in span.text).text).strip() == "+12"
    assert next(span for span in spans if "+12" in span.text).style.foreground == DARK.accent
    assert next(span for span in spans if "-3" in span.text).style.foreground == DARK.error
    # A row with nothing counted paints no fragment at all, in any colour.
    plain = replace(entry, added=0, removed=0)
    assert all(
        "12" not in span.text and "-3" not in span.text
        for line in render_entry(plain, 80, DARK, 0)
        for span in line.spans
    )


def test_tool_component_keeps_code_colours_and_bounded_preview():
    entry = ToolEntry(
        id=1,
        call_id="call-1",
        tool="read_file",
        title="Read app.py",
        language="python",
        text="def parse():\n    return 42\nthird\nfourth\nfifth\nsixth\nseventh",
        status=EntryStatus.COMPLETED,
    )

    preview = render_entry(entry, 40, DARK, 0)

    assert any(
        span.text == "def" and span.style.foreground == DARK.code.keyword for line in preview for span in line.spans
    )
    assert any("more rows" in line.text for line in preview)
    entry.expanded = True
    assert len(render_entry(entry, 40, DARK, 0)) > len(preview)


def _tool_entry(tool: str, *, status: EntryStatus = EntryStatus.COMPLETED) -> ToolEntry:
    """Build one completed or failed tool row with a title and a result."""
    return ToolEntry(id=1, call_id="call-1", tool=tool, title=f"Ran {tool}", text="output", status=status)


def test_tool_rows_share_one_hue_until_a_palette_separates_them():
    """The built-in palettes paint every tool the same; a theme may differ.

    The roles exist so a palette *can* pull reading and running apart, which is
    what the custom palette below checks, but the shipped look is one colour.
    """
    read = render_entry(_tool_entry("read_file"), 40, DARK, 0)
    shell = render_entry(_tool_entry("bash"), 40, DARK, 0)

    def hue(lines) -> set[str]:
        return {span.style.foreground for line in lines for span in line.spans if span.text.strip()}

    assert DARK.tools.read in hue(read)
    assert DARK.tools.shell in hue(shell)
    assert DARK.tools.read == DARK.tools.search == DARK.tools.shell == DARK.code.builtin
    # Roles stay separate so one of them can be overridden on its own.
    assert tool_color("write_file", DARK) == tool_color("replace_in_file", DARK) == DARK.tools.write
    # A delegated task is its own family, not a file operation.
    assert tool_color("task", DARK) == DARK.tools.subagent
    assert DARK.tools.subagent != DARK.tools.read
    # An unfamiliar tool still gets a colour rather than no style at all.
    assert tool_color("mcp__something", DARK) == DARK.accent


def test_a_palette_may_separate_the_tool_roles():
    separated = replace(DARK, tools=replace(DARK.tools, shell="#123456"))

    assert tool_color("bash", separated) == "#123456"
    assert tool_color("read_file", separated) == DARK.tools.read


def test_a_failed_tool_row_is_red_whatever_the_tool_was():
    failed = _tool_entry("read_file", status=EntryStatus.FAILED)

    lines = render_entry(failed, 40, DARK, 0)
    colours = {span.style.foreground for line in lines for span in line.spans if span.text.strip()}

    assert DARK.error in colours
    assert DARK.tools.read not in colours
