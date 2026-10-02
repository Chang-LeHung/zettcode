"""Tests for the layout containers, anchors, and the virtualized scroll view."""

import pytest

from zettcode.tui import Canvas, Constraints, Rect, Size, Span, TextLine, Widget
from zettcode.tui.layout import (
    Anchor,
    Border,
    HBox,
    LineSource,
    Overlay,
    OverlaySlot,
    Padding,
    ScrollView,
    Slot,
    Track,
    VBox,
    resolve_tracks,
)
from zettcode.tui.render import display_width
from zettcode.tui.testing import Harness


class Label(Widget):
    """Widget with a measurable intrinsic size."""

    def __init__(self, text: str = "", *, height: int = 1) -> None:
        super().__init__()
        self.text = text
        self.height = height

    def measure(self, constraints: Constraints) -> Size:
        return constraints.constrain(Size(display_width(self.text), self.height))

    def render(self, canvas: Canvas) -> None:
        canvas.draw_text(self.rect.x, self.rect.y, self.text, max_width=self.rect.width)


class RecordingSource(LineSource):
    """Line source that remembers exactly which lines were requested."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.requested: list[int] = []

    def count(self, width: int) -> int:
        return len(self.lines)

    def line(self, index: int, width: int) -> TextLine:
        self.requested.append(index)
        return TextLine((Span(self.lines[index]),))


def row_text(canvas: Canvas, y: int) -> str:
    return "".join(cell.character for cell in canvas.cells[y] if not cell.continuation)


def test_resolve_tracks_honours_fixed_minimum_and_flex():
    assert resolve_tracks(10, []) == []
    assert resolve_tracks(10, [Track(3), Track(5)]) == [3, 5]
    assert resolve_tracks(10, [Track(1, minimum=3)]) == [3]
    assert resolve_tracks(8, [Track(None, flex=1), Track(None, flex=1)]) == [4, 4]
    assert resolve_tracks(5, [Track(None, flex=1), Track(None, flex=1)]) == [3, 2]
    assert resolve_tracks(10, [Track(None, flex=1), Track(None, flex=3)]) == [3, 7]
    assert resolve_tracks(10, [Track(4, flex=1), Track(None, flex=1)]) == [7, 3]
    assert resolve_tracks(20, [Track(lambda available: available // 4)]) == [5]
    # A callable sizes the main axis from the cross axis, because that is the
    # extent a wrapping child actually depends on.
    assert resolve_tracks(20, [Track(lambda cross: cross // 4)], cross=40) == [10]


def test_resolve_tracks_shrinks_proportionally_when_fixed_sizes_overflow():
    assert resolve_tracks(4, [Track(3), Track(3)]) == [2, 2]
    assert sum(resolve_tracks(5, [Track(9), Track(1)])) == 5
    assert resolve_tracks(0, [Track(2), Track(2)]) == [0, 0]


def test_vbox_distributes_fixed_and_flexible_rows():
    header, body, footer = Label("head"), Label("body"), Label("foot")
    box = VBox([Slot(header, size=1), Slot(body, flex=1), Slot(footer, size=1)])

    box.layout(Rect(0, 0, 20, 10))

    assert header.rect == Rect(0, 0, 20, 1)
    assert body.rect == Rect(0, 1, 20, 8)
    assert footer.rect == Rect(0, 9, 20, 1)
    assert box.children == (header, body, footer)


def test_hbox_distributes_columns_and_boxes_report_intrinsic_size():
    left, right = Label("left"), Label("right")
    box = HBox([Slot(left, size=6), Slot(right, flex=1)])

    box.layout(Rect(0, 0, 20, 4))

    assert left.rect == Rect(0, 0, 6, 4)
    assert right.rect == Rect(6, 0, 14, 4)
    assert VBox([Slot(Label("abc"))]).measure(Constraints.loose(Size(20, 10))) == Size(3, 1)
    assert HBox([Slot(Label("ab")), Slot(Label("cde"))]).measure(Constraints.loose(Size(20, 10))) == Size(5, 1)


def test_a_box_hands_slot_callbacks_the_cross_axis_extent():
    """A VBox measures a slot's height from the width it has to work with."""
    widths: list[int] = []
    heights: list[int] = []
    vertical = VBox([Slot(Label("x"), size=lambda width: widths.append(width) or 1)])
    horizontal = HBox([Slot(Label("x"), size=lambda height: heights.append(height) or 1)])

    vertical.layout(Rect(0, 0, 30, 8))
    horizontal.layout(Rect(0, 0, 30, 8))

    assert widths == [30]
    assert heights == [8]
    assert vertical.children[0].rect.height == 1
    assert horizontal.children[0].rect.width == 1


def test_padding_insets_its_child_and_reserves_space():
    child = Label("x")
    padded = Padding(child, 1)

    padded.layout(Rect(0, 0, 10, 5))

    assert child.rect == Rect(1, 1, 8, 3)
    assert padded.measure(Constraints.loose(Size(10, 5))) == Size(3, 3)


def test_border_draws_a_frame_around_its_child():
    child = Label("x")
    border = Border(child)
    border.layout(Rect(0, 0, 6, 3))
    canvas = Canvas(6, 3)

    border.render(canvas)

    assert child.rect == Rect(1, 1, 4, 1)
    assert row_text(canvas, 0) == "\u250c\u2500\u2500\u2500\u2500\u2510"
    assert row_text(canvas, 1) == "\u2502x   \u2502"
    assert row_text(canvas, 2) == "\u2514\u2500\u2500\u2500\u2500\u2518"
    assert border.measure(Constraints.loose(Size(20, 10))) == Size(3, 3)


def test_anchor_resolves_alignment_offsets_and_clamps_to_bounds():
    bounds = Rect(0, 0, 10, 4)

    assert Anchor().resolve(bounds, Size(4, 2)) == Rect(0, 0, 4, 2)
    assert Anchor(horizontal="center", vertical="center").resolve(bounds, Size(4, 2)) == Rect(3, 1, 4, 2)
    assert Anchor(horizontal="end", vertical="end").resolve(bounds, Size(4, 2)) == Rect(6, 2, 4, 2)
    assert Anchor(horizontal="stretch", width=99).resolve(bounds, Size(4, 2)) == Rect(0, 0, 10, 2)
    # Stretch fills the parent on each axis, and an explicit pin still wins.
    assert Anchor(horizontal="stretch", vertical="stretch").resolve(bounds, Size(4, 2)) == Rect(0, 0, 10, 4)
    assert Anchor(horizontal="stretch", width=6).resolve(bounds, Size(4, 2)) == Rect(0, 0, 6, 2)
    assert Anchor(offset_x=1, offset_y=1).resolve(bounds, Size(4, 2)) == Rect(1, 1, 4, 2)

    with pytest.raises(ValueError, match="horizontal anchor"):
        Anchor(horizontal="middle")
    with pytest.raises(ValueError, match="vertical anchor"):
        Anchor(vertical="middle")


def test_overlay_places_children_at_anchored_rects():
    back, front = Label("back"), Label("f")
    overlay = Overlay([OverlaySlot(back), OverlaySlot(front, Anchor(horizontal="end", vertical="end"))])

    overlay.layout(Rect(0, 0, 10, 4))

    assert back.rect == Rect(0, 0, 4, 1)
    assert front.rect == Rect(9, 3, 1, 1)
    assert overlay.children == (back, front)


def test_scroll_view_only_builds_the_visible_window():
    source = RecordingSource([f"line {index}" for index in range(6)])
    view = ScrollView(source)
    view.layout(Rect(0, 0, 20, 3))

    canvas = Canvas(20, 3)
    view.render(canvas)

    assert source.requested == [3, 4, 5]
    assert row_text(canvas, 0).startswith("line 3")
    assert view.visible_range() == (3, 6)
    assert view.max_top == 3


def test_scroll_view_keeps_the_view_stable_when_content_is_appended():
    source = RecordingSource([f"line {index}" for index in range(6)])
    view = ScrollView(source)
    view.layout(Rect(0, 0, 20, 3))
    canvas = Canvas(20, 3)

    view.scroll_to(0)
    source.requested.clear()
    source.lines.append("line 6")
    view.render(canvas)

    assert source.requested == [0, 1, 2]
    assert view.follow_tail is False

    view.scroll_end()
    source.requested.clear()
    view.render(canvas)

    assert view.top == 4
    assert source.requested == [4, 5, 6]


def test_scroll_view_clamps_and_anchors_around_insertions():
    source = RecordingSource([f"line {index}" for index in range(10)])
    view = ScrollView(source)
    view.layout(Rect(0, 0, 20, 3))

    view.scroll_by(-100)
    assert view.top == 0
    view.scroll_to(999)
    assert view.top == 7
    assert view.follow_tail is True

    view.scroll_to(4)
    view.adjust_for_insertion(0, 2)
    assert view.top == 6
    view.adjust_for_insertion(9, 1)
    assert view.top == 6


def test_scroll_view_scrolls_with_the_mouse_wheel():
    source = RecordingSource([f"line {index}" for index in range(20)])
    view = ScrollView(source)
    harness = Harness(view, width=20, height=5)
    harness.render()

    assert view.follow_tail is True
    assert view.top == 15

    harness.scroll(2, 2, up=True)

    assert view.top == 12
    assert view.follow_tail is False

    harness.scroll(2, 2, up=False)

    assert view.top == 15
    assert view.follow_tail is True


def test_scroll_view_drag_selects_text_and_copies_it():
    source = RecordingSource(["alpha", "beta", "gamma"])
    view = ScrollView(source, selectable=True)
    harness = Harness(view, width=20, height=3)
    harness.render()

    harness.mouse_down(1, 0)
    harness.mouse_move(4, 1)
    harness.mouse_up(4, 1)

    assert view.selected_text() == "lpha\nbeta"
    assert harness.clipboard == "lpha\nbeta"


def test_scroll_view_double_click_selects_a_whole_line():
    ticks = iter([1.0, 1.1, 1.2, 1.3])
    source = RecordingSource(["alpha", "beta", "gamma"])
    view = ScrollView(source, selectable=True, clock=lambda: next(ticks))
    harness = Harness(view, width=20, height=3)
    harness.render()

    harness.mouse_down(2, 1)
    harness.mouse_up(2, 1)
    harness.mouse_down(2, 1)
    harness.mouse_up(2, 1)

    assert view.selected_text() == "beta"


def test_scroll_view_shift_click_extends_an_existing_selection():
    source = RecordingSource(["alpha", "beta", "gamma"])
    view = ScrollView(source, selectable=True)
    harness = Harness(view, width=20, height=3)
    harness.render()

    harness.mouse_down(0, 0)
    harness.mouse_up(2, 0)
    harness.mouse_down(3, 2, shift=True)
    harness.mouse_up(3, 2)

    assert view.selected_text() == "alpha\nbeta\ngam"


def test_a_view_that_is_not_selectable_ignores_drags():
    source = RecordingSource(["alpha", "beta"])
    view = ScrollView(source)
    harness = Harness(view, width=20, height=2)
    harness.render()

    harness.mouse_down(1, 0)
    harness.mouse_move(3, 1)
    harness.mouse_up(3, 1)

    assert view.selected_text() == ""
    assert harness.clipboard == ""
