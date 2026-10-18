"""Presenters turn entries into styled, width-bound lines."""

from dataclasses import replace

import pytest

from zettcode.app.agent.conversation.entries import (
    EditEntry,
    EntryKind,
    EntryStatus,
    MarkdownEntry,
    ReadEntry,
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
from zettcode.app.agent.conversation.pulse import PULSE_FRAMES, RUNNING_GLYPHS, move_frames
from zettcode.app.agent.conversation.text import COMPACTING_LABEL, STOP_HINT
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
    whole = [presenter.kind for presenter in DEFAULT_PRESENTERS.presenters if presenter.entry_type is None]

    assert sorted(whole) == sorted(EntryKind), "every kind has a presenter, and no kind has two"
    assert all(isinstance(presenter, Presenter) for presenter in DEFAULT_PRESENTERS.presenters)
    families = [presenter for presenter in DEFAULT_PRESENTERS.presenters if presenter.entry_type is not None]
    assert all(presenter.kind in whole for presenter in families), "a family belongs to a kind that has its own"


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

    halfway = move_frames() // 2
    assert painted(thinking, 0) == painted(thinking, halfway)
    assert painted(tool, 0) == painted(tool, halfway)
    assert painted(waiting, 0) != painted(waiting, halfway)


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
    entry = EditEntry(
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
    assert next(span for span in spans if "+12" in span.text).style.foreground == DARK.addition
    assert next(span for span in spans if "-3" in span.text).style.foreground == DARK.deletion
    # A row with nothing counted paints no fragment at all, in any colour.
    plain = replace(entry, added=0, removed=0)
    assert all(
        "12" not in span.text and "-3" not in span.text
        for line in render_entry(plain, 80, DARK, 0)
        for span in line.spans
    )


def test_tool_component_keeps_code_colours_and_bounded_preview():
    entry = ReadEntry(
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


def test_tool_rows_are_painted_by_what_the_tool_did():
    """Five hues, not seven: what is looked at or run is lavender, what is written green, what is deleted
    red, a delegated agent teal, and another session mauve.

    A transcript is mostly tool rows, and a rainbow of them reads as noise. Tools that do the same thing
    share a hue, and the roles stay separate so a palette can override one of them on its own.
    """
    read = render_entry(_tool_entry("read_file"), 40, DARK, 0)
    shell = render_entry(_tool_entry("bash"), 40, DARK, 0)

    def hue(lines) -> set[str]:
        return {span.style.foreground for line in lines for span in line.spans if span.text.strip()}

    assert DARK.tools.read in hue(read)
    assert DARK.tools.shell in hue(shell)
    assert DARK.tools.read == DARK.tools.search
    for theme in (DARK, LIGHT):
        looking = {theme.tools.read, theme.tools.search, theme.tools.image, theme.tools.shell, theme.tools.plan}
        assert len(looking) == 1, "everything the agent looks at or runs is one hue"
        assert len({*looking, theme.tools.write, theme.tools.delete, theme.tools.subagent, theme.tools.message}) == 5
    assert DARK.tools.delete == DARK.error, "a deletion is the colour of a failure, on purpose"
    assert tool_color("grep", DARK) == tool_color("read_file", DARK)
    assert tool_color("bash", DARK) == DARK.tools.shell != tool_color("write_file", DARK)
    # Roles stay separate so one of them can be overridden on its own.
    assert tool_color("write_file", DARK) == tool_color("replace_in_file", DARK) == DARK.tools.write
    # A delegated task is its own family, not a file operation.
    assert tool_color("task", DARK) == DARK.tools.subagent
    assert DARK.tools.subagent != DARK.tools.read
    # Talking to another session is its own colour, the one the header of a message from one is drawn in.
    assert tool_color("send_message", DARK) == tool_color("list_sessions", DARK) == DARK.tools.message
    assert DARK.tools.message != DARK.tools.subagent and LIGHT.tools.message != LIGHT.tools.subagent
    # An unfamiliar tool still gets a colour rather than no style at all.
    assert tool_color("mcp__something", DARK) == DARK.accent


@pytest.mark.parametrize("theme", [DARK, LIGHT], ids=lambda theme: theme.name)
def test_the_heading_of_an_edit_is_not_the_colour_of_the_added_lines_under_it(theme):
    """The heading sits on the line above its diff; in the same green it read as one more added line."""
    transcript = Transcript()
    transcript.start_tool(
        "e", "replace_in_file", {"path": "a.py", "edits": [{"old_text": "x = 1", "new_text": "x = 2\ny = 3"}]}
    )
    transcript.complete_tool("e", "ok", wait=False)
    (entry,) = transcript.entries

    lines = render_entry(entry, 60, theme, 0)
    heading = next(line for line in lines if "Edited" in line.text)
    added = next(line for line in lines if line.text.strip().startswith("+ x = 2"))
    heading_colour = next(span.style.foreground for span in heading.spans if "Edited" in span.text)
    added_colour = next(span.style.foreground for span in added.spans if span.text.strip())

    assert added_colour == theme.addition
    assert heading_colour == theme.tools.write != theme.addition
    assert theme.tools.write not in (theme.accent, theme.addition, theme.deletion, theme.error)
    for other in ("read", "search", "image", "delete", "shell", "plan", "subagent", "message"):
        if other in ("read", "search", "image", "shell", "plan"):
            continue  # one hue by design, tested above
        assert getattr(theme.tools, other) != theme.tools.write, other
    assert theme.tools.write not in {theme.tools.read, theme.tools.subagent, theme.tools.message}


def test_writing_is_a_hue_of_its_own_among_the_tool_colours_in_both_palettes():
    for theme in (DARK, LIGHT):
        hues = {theme.tools.read, theme.tools.write, theme.tools.delete, theme.tools.subagent, theme.tools.message}
        assert len(hues) == 5, theme.name


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


# -- a tool's row is drawn by the presenter for its entry ------------------------------------------------------


def _bare(cls, **extra):
    fields = {"id": 1, "call_id": "c", "tool": "t", "title": "Ran t", "text": "out", "status": EntryStatus.COMPLETED}
    return cls(**{**fields, **extra})


def test_each_family_of_tool_entry_has_its_own_presenter_and_the_rest_share_the_general_one():
    from zettcode.app.agent.conversation.entries import WriteEntry
    from zettcode.app.agent.conversation.presenters import EditPresenter, ReadPresenter, WritePresenter

    cases = [
        (_bare(ToolEntry), ToolPresenter),
        (_bare(ReadEntry), ReadPresenter),
        (_bare(WriteEntry), WritePresenter),
        (_bare(EditEntry), EditPresenter),
    ]
    for entry, presenter in cases:
        assert type(DEFAULT_PRESENTERS.for_entry(entry)) is presenter, type(entry).__name__
        assert entry.kind is EntryKind.TOOL, "they are all tool rows"


def test_an_entry_class_nobody_wrote_a_presenter_for_is_drawn_by_the_nearest_one_above_it():
    """A host's own subclass of an edit entry is drawn as an edit, not as a bare tool and not as an error."""
    from dataclasses import dataclass

    from zettcode.app.agent.conversation.presenters import EditPresenter

    @dataclass(slots=True, kw_only=True)
    class AuditedEdit(EditEntry):
        reviewer: str = "me"

    entry = AuditedEdit(id=1, call_id="c", tool="t", title="x", added=2, status=EntryStatus.COMPLETED)

    assert type(DEFAULT_PRESENTERS.for_entry(entry)) is EditPresenter
    assert any("+2" in line.text for line in render_entry(entry, 60, DARK, 0))


def test_a_tool_entry_that_is_none_of_the_families_falls_back_to_the_kind():
    from dataclasses import dataclass

    @dataclass(slots=True, kw_only=True)
    class Odd(ToolEntry):
        pass

    assert type(DEFAULT_PRESENTERS.for_entry(Odd(id=1, call_id="c", tool="t", title="x"))) is ToolPresenter


def test_a_presenter_given_for_the_whole_kind_replaces_the_families_too():
    """It was asked to draw every tool row; a family left behind would go on drawing its own."""

    class Everything(Presenter):
        kind = EntryKind.TOOL

        def lines(self, entry, width, theme, frame):
            return [TextLine()]

    presenters = DEFAULT_PRESENTERS.replacing(Everything())

    for cls in (ToolEntry, ReadEntry, EditEntry):
        assert presenters.lines(_bare(cls), 40, DARK, 0) == [TextLine()], cls.__name__
    assert [p for p in presenters.presenters if p.kind is EntryKind.TOOL and p.entry_type is not None] == []


def test_a_family_given_after_the_kind_is_a_refinement_of_it_and_stays():
    from zettcode.app.agent.conversation.presenters import EditPresenter

    class Everything(Presenter):
        kind = EntryKind.TOOL

        def lines(self, entry, width, theme, frame):
            return [TextLine()]

    presenters = Presenters((Everything(), EditPresenter()))

    assert presenters.lines(_bare(ToolEntry), 40, DARK, 0) == [TextLine()]
    assert type(presenters.for_entry(_bare(EditEntry))) is EditPresenter


def test_a_family_can_be_replaced_without_touching_the_others():
    from zettcode.app.agent.conversation.presenters import EditPresenter

    class Quiet(EditPresenter):
        def after_title(self, entry, theme):
            return []

    presenters = DEFAULT_PRESENTERS.replacing(Quiet())
    edit = _bare(EditEntry, added=9)

    assert not any("+9" in line.text for line in presenters.lines(edit, 60, DARK, 0))
    assert any("+9" in line.text for line in DEFAULT_PRESENTERS.lines(edit, 60, DARK, 0))
    assert len(presenters.presenters) == len(DEFAULT_PRESENTERS.presenters)


def test_the_rows_every_tool_shares_are_drawn_the_same_whatever_the_entry():
    """The symbol, timer and body are the base's: the families add after the title and under it, nothing else."""
    from zettcode.app.agent.conversation.entries import WriteEntry

    plain = [line.text for line in render_entry(_bare(ToolEntry, duration=1.5), 60, DARK, 0)]
    for cls in (ReadEntry, WriteEntry, EditEntry):
        assert [line.text for line in render_entry(_bare(cls, duration=1.5), 60, DARK, 0)] == plain, cls.__name__


def test_a_write_entry_paints_only_what_it_has_a_count_of():
    from zettcode.app.agent.conversation.entries import WriteEntry

    spans = [s for line in render_entry(_bare(WriteEntry, added=40), 60, DARK, 0) for s in line.spans]

    assert next(s for s in spans if "+40" in s.text).style.foreground == DARK.addition
    assert not any("-" == s.text.strip()[:1] and s.text.strip()[1:].isdigit() for s in spans)


def test_a_read_entry_without_a_language_is_drawn_plain():
    plain = [s for line in render_entry(_bare(ReadEntry, language=None), 60, DARK, 0) for s in line.spans]
    code = [
        s
        for line in render_entry(_bare(ReadEntry, language="python", text="def f(): pass"), 60, DARK, 0)
        for s in line.spans
    ]

    assert not any(s.style.foreground == DARK.code.keyword for s in plain)
    assert any(s.style.foreground == DARK.code.keyword for s in code)


def test_an_entry_has_only_the_fields_its_tool_shows():
    from zettcode.app.agent.conversation.entries import WriteEntry

    assert not hasattr(_bare(ToolEntry), "language") and not hasattr(_bare(ToolEntry), "diff")
    assert not hasattr(_bare(ReadEntry), "added") and not hasattr(_bare(ReadEntry), "diff")
    assert not hasattr(_bare(WriteEntry), "removed"), "a write takes nothing away"
    assert hasattr(_bare(WriteEntry), "diff") and hasattr(_bare(WriteEntry), "added")
    assert hasattr(_bare(EditEntry), "diff") and hasattr(_bare(EditEntry), "removed")


def test_a_write_and_an_edit_are_drawn_by_the_same_file_change_code_and_differ_only_in_what_they_remove():
    from zettcode.app.agent.conversation.entries import FileChangeEntry, WriteEntry
    from zettcode.app.agent.conversation.presenters import EditPresenter, FileChangePresenter, WritePresenter

    assert issubclass(WriteEntry, FileChangeEntry) and issubclass(EditEntry, FileChangeEntry)
    assert issubclass(WritePresenter, FileChangePresenter) and issubclass(EditPresenter, FileChangePresenter)
    diff = (("+", "x"),)
    write = _bare(WriteEntry, added=1, diff=diff)
    edit = _bare(EditEntry, added=1, removed=0, diff=diff)

    assert [row.text for row in render_entry(write, 60, DARK, 0)] == [
        row.text for row in render_entry(edit, 60, DARK, 0)
    ]


def test_a_write_never_draws_a_removal_count_whatever_it_holds():
    from zettcode.app.agent.conversation.entries import WriteEntry

    spans = [s for line in render_entry(_bare(WriteEntry, added=5), 60, DARK, 0) for s in line.spans]

    assert not any(s.style.foreground == DARK.deletion for s in spans)


# -- a message the agent sent to another session ---------------------------------------------------------------


SESSION = "01a10b75-aaaa-7000-8000-00000000f00d"


def _sent(message: str, *, to: str = "work", output: str = "Delivered to work (id abc); it started a turn.", **fields):
    """Run a ``send_message`` call through the real transcript, as a request would, and return the row."""
    transcript = Transcript()
    transcript.start_tool("call-1", "send_message", {"to": to, "message": message})
    if output is not None:
        transcript.complete_tool("call-1", output, wait=False, **fields)
    (entry,) = transcript.entries
    return transcript, entry


def _plain(lines) -> list[str]:
    return [line.text for line in lines]


def test_a_sent_message_opens_as_its_own_row_that_holds_every_word():
    from zettcode.app.agent.conversation.entries import MessageEntry

    long = "\n".join(f"line {number}" for number in range(30))
    transcript, entry = _sent(long)

    assert isinstance(entry, MessageEntry)
    assert (entry.to, entry.message, entry.title) == ("work", long, "Message to work")


def test_a_message_to_a_session_id_is_titled_by_the_end_of_the_id_and_a_name_as_it_is():
    assert _sent("hi", to=SESSION)[1].title == "Message to session 00f00d"
    assert _sent("hi", to="fix-the-parser")[1].title == "Message to fix-the-parser"
    assert _sent("hi", to="")[1].title == "Message to (unknown)"


def test_a_message_that_is_not_text_is_an_empty_one_and_does_not_break_the_row():
    transcript = Transcript()
    transcript.start_tool("c", "send_message", {"to": "work", "message": 12})
    transcript.complete_tool("c", "Delivered.", wait=False)

    assert _plain(render_entry(transcript.entries[0], 60, DARK, 0))[-1].strip() == "\u2192 Delivered."


def test_a_running_send_shows_only_its_heading():
    transcript, entry = _sent("hello there", output=None)

    rows = _plain(render_entry(entry, 60, DARK, 0))

    assert [row.strip() for row in rows if row.strip()] == [f"{RUNNING_GLYPHS[0]} Message to work"]
    assert transcript.toggle(entry.id) is False, "a running row has nothing to expand yet"


def test_a_sent_message_is_folded_to_a_few_lines_and_expands_to_all_of_them():
    body = "\n".join(f"line {number}" for number in range(30))
    transcript, entry = _sent(body)

    folded = _plain(render_entry(entry, 60, DARK, 0))
    assert "▸" in folded[1] and "line 0" in "".join(folded) and "line 4" in "".join(folded)
    assert "line 5" not in "".join(folded)
    assert any("25 more rows" in row for row in folded)
    assert folded[-1].strip().startswith("\u2192 Delivered to work"), "the answer is told from the message by an arrow"

    assert transcript.toggle(entry.id) is True
    opened = _plain(render_entry(entry, 60, DARK, 0))
    assert "▾" in opened[1] and "line 29" in "".join(opened)
    assert not any("more rows" in row for row in opened)

    assert transcript.toggle(entry.id) is True
    assert _plain(render_entry(entry, 60, DARK, 0)) == folded


def test_a_message_longer_than_the_row_wraps_instead_of_running_off_it():
    transcript, entry = _sent("word " * 60)
    transcript.toggle(entry.id)

    rows = _plain(render_entry(entry, 40, DARK, 0))

    assert max(display_width(row) for row in rows) <= 40
    assert len([row for row in rows if "word" in row]) > 3


def test_the_outcome_is_one_muted_line_folded_and_whole_when_expanded():
    output = "Not delivered: the session is busy. " + "x " * 80
    transcript, entry = _sent("hi", output=output, status=EntryStatus.FAILED)

    folded = _plain(render_entry(entry, 50, DARK, 0))
    assert folded[-1].rstrip().endswith("\u2026") and len(folded) == 4
    transcript.toggle(entry.id)
    assert len(_plain(render_entry(entry, 50, DARK, 0))) > len(folded)


def test_a_failed_send_is_drawn_in_the_error_colour_with_its_reason_in_the_same_colour():
    transcript, entry = _sent("hi", output="No such session is active.", status=EntryStatus.FAILED)

    lines = render_entry(entry, 60, DARK, 0)
    colours = {span.style.foreground for line in lines for span in line.spans if span.text.strip()}

    assert DARK.error in colours and DARK.tools.message not in colours
    assert lines[-1].spans[0].style.foreground == DARK.error


def test_a_delivered_send_is_in_the_message_colour_and_its_outcome_muted():
    transcript, entry = _sent("hi")

    lines = render_entry(entry, 60, DARK, 0)

    assert lines[1].spans[1].style.foreground == DARK.tools.message
    assert lines[-1].spans[0].style.foreground == DARK.muted


def test_the_text_of_a_sent_message_cannot_move_the_cursor_or_retitle_the_window():
    transcript, entry = _sent("\x1b[2Jclear \x1b]0;owned\x07 done", output="ok")
    transcript.toggle(entry.id)

    rendered = "".join(_plain(render_entry(entry, 60, DARK, 0)))

    assert "\x1b" not in rendered and "\x07" not in rendered


def test_a_sent_message_with_nothing_to_say_still_shows_how_it_ended():
    transcript, entry = _sent("", output="Delivered.")

    assert entry.foldable and _plain(render_entry(entry, 60, DARK, 0))[-1].strip() == "\u2192 Delivered."
    assert transcript.toggle(entry.id) is True


def test_the_narrowest_row_does_not_fail():
    transcript, entry = _sent("a long message " * 5)
    transcript.toggle(entry.id)

    for width in (1, 2, 3, 8):
        assert render_entry(entry, width, DARK, 0)


def test_list_sessions_takes_the_message_colour_too_and_its_listing_expands_like_any_output():
    transcript = Transcript()
    transcript.start_tool("c", "list_sessions", {})
    transcript.complete_tool("c", "\n".join(f"@s{n}" for n in range(9)), wait=False)
    (entry,) = transcript.entries

    assert tool_color(entry.tool, DARK) == DARK.tools.message
    assert transcript.toggle(entry.id) is True


def test_a_message_with_no_answer_yet_recorded_is_still_something_to_expand():
    transcript, entry = _sent("sent but the tool said nothing", output="")

    assert entry.foldable and transcript.toggle(entry.id) is True
    assert "sent but the tool said nothing" in "".join(_plain(render_entry(entry, 60, DARK, 0)))


def test_an_enormous_message_is_kept_bounded_like_any_tool_output():
    from zettcode.app.agent.conversation.text import MAX_TOOL_OUTPUT

    transcript, entry = _sent("x" * (MAX_TOOL_OUTPUT * 3))

    assert len(entry.message) < MAX_TOOL_OUTPUT * 1.1 and "characters omitted" in entry.message


def test_every_tool_hue_can_be_read_on_the_surfaces_a_row_sits_on():
    """A hue that vanishes on a palette's own surface would hide the very rows it is meant to sort."""
    from test_theme_config import _contrast

    for theme in (DARK, LIGHT):
        for role in ("read", "search", "image", "write", "delete", "shell", "plan", "subagent", "message"):
            colour = getattr(theme.tools, role)
            assert _contrast(colour, theme.surface) >= 3.4, (theme.name, role, "on surface")
            assert _contrast(colour, theme.surface_alt) >= 3.4, (theme.name, role, "on the alternate surface")


# -- whose presenter draws a row: the built-ins are the default, at the lowest priority -----------------


def test_the_built_in_presenters_are_the_lowest_claim_so_a_plugin_replaces_one_by_registering():
    """Nothing has to outrank the program's own rows; registering the same kind is enough."""
    from zettcode.app.agent.conversation.presenters import BUILTIN_PRESENTERS

    assert {presenter.priority for presenter in BUILTIN_PRESENTERS} == {0}

    class Mine(NoticePresenter):
        def lines(self, entry, width, theme, frame):
            return [TextLine()]

    notice = TextEntry(id=1, kind="notice", text="handled")

    assert Presenters((*BUILTIN_PRESENTERS, Mine())).for_entry(notice).__class__ is Mine
    assert DEFAULT_PRESENTERS.for_entry(notice).__class__ is NoticePresenter


def test_a_stronger_claim_wins_wherever_it_was_registered():
    """Priority, then registration order: a higher number beats a later registration at a lower one."""
    notice = TextEntry(id=1, kind="notice", text="handled")

    class Strong(NoticePresenter):
        priority = 5

    class Late(NoticePresenter):
        pass

    assert Presenters((Strong(), Late())).for_entry(notice).__class__ is Strong
    assert Presenters((Late(), Strong())).for_entry(notice).__class__ is Strong


def test_a_presenter_for_the_whole_kind_outranks_the_families_it_was_registered_after():
    """A claim on every tool row is a claim on the edit row too, unless the family claims more."""
    from zettcode.app.agent.conversation.presenters import EditPresenter

    class Everything(ToolPresenter):
        priority = 4

    class StillMine(EditPresenter):
        priority = 6

    edit = EditEntry(id=1, call_id="c", tool="edit", title="Edited a.py", path="a.py")
    rows = Presenters((EditPresenter(), Everything(), StillMine()))

    assert rows.for_entry(ToolEntry(id=2, call_id="d", tool="read_file", title="Read a.py")).__class__ is Everything
    assert rows.for_entry(edit).__class__ is StillMine


def test_a_family_the_kinds_presenter_outranks_is_not_in_the_list_at_all():
    """It would never be asked for a row, so the registry does not hold it out as one of the drawers."""

    class Everything(ToolPresenter):
        priority = 4

    rows = Presenters((*DEFAULT_PRESENTERS.presenters, Everything()))

    families = [p for p in rows.presenters if p.kind is EntryKind.TOOL and p.entry_type is not None]
    assert families == [] and type(rows.for_entry(ToolEntry(id=1, call_id="c", tool="t", title="x"))) is Everything
