"""Agent output components turn entries into styled, width-bound lines."""

from zettcode.app.agent.blocks import (
    DEFAULT_PROCESSORS,
    EntryProcessor,
    EntryProcessors,
    ModelChangeProcessor,
    NoticeProcessor,
    PlainProcessor,
    ProcessingProcessor,
    ThinkingProcessor,
    ToolProcessor,
    UserProcessor,
    WelcomeProcessor,
    render_entry,
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
        (TextEntry(id=8, kind="model_change", text="Model changed from A to B."), ModelChangeProcessor),
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


def test_model_change_is_centered_between_rules_and_clipped_on_small_screens():
    entry = TextEntry(id=1, kind="model_change", text="Model changed from GPT6-Sol to DeepSeek-Flash.")
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
