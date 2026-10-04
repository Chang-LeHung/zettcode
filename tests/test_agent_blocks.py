"""Agent output components turn entries into styled, width-bound lines."""

from dataclasses import replace

from zettcode.app.agent.blocks import (
    DEFAULT_PROCESSORS,
    AnnouncementProcessor,
    EntryProcessor,
    EntryProcessors,
    NoticeProcessor,
    PlainProcessor,
    ProcessingProcessor,
    ThinkingProcessor,
    ToolProcessor,
    UserProcessor,
    WelcomeProcessor,
    render_entry,
    tool_color,
)
from zettcode.app.agent.entries import (
    EntryStatus,
    PlainEntry,
    ProcessingEntry,
    TextEntry,
    ThinkingEntry,
    ToolEntry,
)
from zettcode.app.agent.transcript import Transcript
from zettcode.app.ui.widgets.transcript import TranscriptSource
from zettcode.tui import DARK, LIGHT, TextLine
from zettcode.tui.render import display_width


def test_every_agent_entry_has_a_presentation_component():
    entries = (
        (TextEntry(id=1, kind="welcome", text="hello"), WelcomeProcessor),
        (TextEntry(id=2, kind="notice", text="saved"), NoticeProcessor),
        (TextEntry(id=8, kind="announcement", text="Model changed from A to B."), AnnouncementProcessor),
        (TextEntry(id=3, kind="user", text="hello"), UserProcessor),
        (ProcessingEntry(id=4, started_at=0.0), ProcessingProcessor),
        (ThinkingEntry(id=5, text="reasoning", expanded=True), ThinkingProcessor),
        (ToolEntry(id=6, call_id="call-1", tool="read_file", title="Read app.py", text="content"), ToolProcessor),
        (PlainEntry(id=7, kind="other", text="fallback"), PlainProcessor),
    )
    for entry, component in entries:
        assert issubclass(component, EntryProcessor)
        assert component().supports(entry)
        assert render_entry(entry, 40, DARK, 0)


def test_the_first_supporting_processor_wins():
    class CustomNotice(EntryProcessor):
        def supports(self, entry) -> bool:
            return isinstance(entry, TextEntry) and entry.kind == "notice"

        def lines(self, entry, width, theme, frame):
            return [TextLine()]

    notice = TextEntry(id=1, kind="notice", text="handled")
    processors = EntryProcessors((CustomNotice(), *DEFAULT_PROCESSORS.processors))
    assert processors.lines(notice, 40, DARK, 0) == [TextLine()]

    transcript = Transcript(processors=processors)
    transcript.notice("handled")
    source = TranscriptSource(transcript, theme=DARK)
    assert source.count(40) == 1

    alternate = EntryProcessors((NoticeProcessor(), *DEFAULT_PROCESSORS.processors))
    transcript.processors = alternate
    assert source.count(40) == 2
    assert source.line(1, 40).text.strip() == "handled"


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
        ProcessingEntry(id=3, started_at=0.0, duration=12.3),
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
    notice = TextEntry(id=2, kind="notice", text="done")

    dark_user = render_entry(user, 20, DARK, 0)
    light_user = render_entry(user, 20, LIGHT, 0)
    dark_notice = render_entry(notice, 20, DARK, 0)

    assert dark_user[2].text.startswith("› hello")
    assert dark_user[2].spans[0].style.background == DARK.surface_alt
    assert light_user[2].spans[0].style.background == LIGHT.surface_alt
    assert dark_notice[1].spans[0].style.foreground == DARK.muted


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
    shell = render_entry(_tool_entry("run_shell"), 40, DARK, 0)

    def hue(lines) -> set[str]:
        return {span.style.foreground for line in lines for span in line.spans if span.text.strip()}

    assert DARK.tools.read in hue(read)
    assert DARK.tools.shell in hue(shell)
    assert DARK.tools.read == DARK.tools.search == DARK.tools.shell == DARK.code.builtin
    # Roles stay separate so one of them can be overridden on its own.
    assert tool_color("write_file", DARK) == tool_color("replace_in_file", DARK) == DARK.tools.write
    # An unfamiliar tool still gets a colour rather than no style at all.
    assert tool_color("mcp__something", DARK) == DARK.accent


def test_a_palette_may_separate_the_tool_roles():
    separated = replace(DARK, tools=replace(DARK.tools, shell="#123456"))

    assert tool_color("run_shell", separated) == "#123456"
    assert tool_color("read_file", separated) == DARK.tools.read


def test_a_failed_tool_row_is_red_whatever_the_tool_was():
    failed = _tool_entry("read_file", status=EntryStatus.FAILED)

    lines = render_entry(failed, 40, DARK, 0)
    colours = {span.style.foreground for line in lines for span in line.spans if span.text.strip()}

    assert DARK.error in colours
    assert DARK.tools.read not in colours
