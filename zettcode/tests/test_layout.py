"""Tests for the layout containers, anchors, and the virtualized scroll view."""

import pytest

from zettcode.tui import Canvas, Constraints, Rect, Size, Span, Text, TextLine, Widget
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

    assert view.top == 14
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


def test_a_selection_past_the_end_of_a_shrunken_source_is_clamped():
    source = RecordingSource(["alpha", "beta", "gamma"])
    view = ScrollView(source, selectable=True)
    harness = Harness(view, width=20, height=3)
    harness.render()
    harness.mouse_down(1, 0)
    harness.mouse_move(4, 2)
    harness.mouse_up(4, 2)

    source.lines = ["alpha"]

    assert view.has_selection() is True
    assert view.selected_text() == "lpha"


def test_a_selection_whose_last_line_disappears_covers_the_rest_of_the_last_row():
    source = RecordingSource(["alpha", "beta", "gamma"])
    view = ScrollView(source, selectable=True)
    harness = Harness(view, width=20, height=3)
    harness.render()
    harness.mouse_down(0, 0)
    harness.mouse_move(3, 2)
    harness.mouse_up(3, 2)

    source.lines = ["alpha", "beta"]

    assert view.selected_text() == "alpha\nbeta"


def test_a_selection_with_no_cells_left_is_not_a_selection():
    source = RecordingSource(["a long enough line"])
    view = ScrollView(source, selectable=True)
    harness = Harness(view, width=20, height=3)
    harness.render()
    harness.mouse_down(10, 0)
    harness.mouse_up(15, 0)

    source.lines = ["x"]

    assert view.has_selection() is False
    assert view.selected_text() == ""


def test_a_stale_selection_is_dropped_when_the_view_renders():
    source = RecordingSource(["alpha", "beta"])
    view = ScrollView(source, selectable=True)
    harness = Harness(view, width=20, height=3)
    harness.render()
    harness.mouse_down(0, 0)
    harness.mouse_move(3, 1)
    harness.mouse_up(3, 1)
    source.lines = []

    assert view.has_selection() is False
    assert view.selected_text() == ""

    harness.render()
    assert view.selection_bounds() is None


def test_a_double_click_that_keeps_moving_extends_the_selection():
    """The second press picks the line; dragging on from there keeps going."""
    ticks = iter([1.0, 1.1, 1.2, 1.3])
    source = RecordingSource(["alpha", "beta", "gamma"])
    view = ScrollView(source, selectable=True, clock=lambda: next(ticks))
    harness = Harness(view, width=20, height=3)
    harness.render()

    harness.mouse_down(2, 1)
    harness.mouse_up(2, 1)
    harness.mouse_down(2, 1)
    harness.mouse_move(3, 2)
    harness.mouse_up(3, 2)

    assert view.selected_text() == "beta\ngam"


def test_a_drag_that_leaves_the_view_still_extends_and_copies():
    """The press owns the drag: leaving the rectangle must not drop the release."""
    source = RecordingSource(["alpha", "beta", "gamma"])
    view = ScrollView(source, selectable=True)
    other = Text("elsewhere")
    page = VBox([Slot(view, flex=1), Slot(other, size=1)])
    harness = Harness(page, width=20, height=4)
    harness.render()

    harness.mouse_down(1, 0)
    harness.mouse_move(3, 3)  # over the other widget, below the view
    harness.mouse_up(3, 3)

    assert view.selected_text() == "lpha\nbeta\ngam"
    assert harness.clipboard == "lpha\nbeta\ngam"


def test_a_view_that_is_not_selectable_leaves_the_drag_to_the_frame():
    """The widget keeps no selection of its own; the application copies the cells."""
    source = RecordingSource(["alpha", "beta"])
    view = ScrollView(source)
    harness = Harness(view, width=20, height=2)
    harness.render()

    harness.mouse_down(1, 0)
    harness.mouse_move(3, 1)
    harness.mouse_up(3, 1)

    assert view.selected_text() == ""
    assert harness.clipboard == "lpha\nbet"


# -- the wheel: one row an event, as Codex does, and never far enough in a frame to skip anything ------------


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _long_view(clock: _Clock | None = None, lines: int = 2000, *, selectable: bool = False, **options) -> ScrollView:
    view = ScrollView(
        RecordingSource([f"line {index}" for index in range(lines)]),
        follow_tail=False,
        clock=clock or _Clock(),
        selectable=selectable,
        **options,
    )
    view.layout(Rect(0, 0, 20, 10))
    view.scroll_to(1000)
    return view


def _turn(view: ScrollView, count: int, *, up: bool = False, frame_each: bool = True) -> list[int]:
    """Turn the wheel ``count`` events; return how far each one moved the view.

    A frame is drawn after each unless ``frame_each`` is off, which is how a burst that was queued and
    applied together reaches the view.
    """
    from zettcode.tui import MouseAction, MouseEvent

    app = Harness(view, width=20, height=10).app
    moved = []
    for _ in range(count):
        before = view.top
        action = MouseAction.SCROLL_UP if up else MouseAction.SCROLL_DOWN
        assert view.handle(MouseEvent(x=1, y=0, action=action), app)
        moved.append(abs(view.top - before))
        if frame_each:
            view._frame_start = None  # what render does at the start of the next frame
    return moved


def test_every_wheel_event_is_one_row_however_long_or_fast_the_wheel_turns():
    """The bug: a turn that went on gained a row an event up to ten, and a trackpad's momentum — dozens of events
    in a flick — threw the view across several pages."""
    view = _long_view()

    assert _turn(view, 100) == [1] * 100
    assert view.top == 1100


def test_a_flick_of_events_that_pile_up_moves_the_view_by_less_than_a_window_in_one_frame():
    """Events that were queued are applied together and drawn once; rows past half a window are never painted."""
    view = _long_view()  # a window of ten rows

    moved = _turn(view, 100, frame_each=False)

    assert view.top - 1000 == 5, "half a window, however many events there were"
    assert sum(moved) == 5 and moved[:5] == [1] * 5 and moved[5:] == [0] * 95


def test_the_next_frame_may_move_it_again_so_a_long_flick_still_gets_there_a_frame_at_a_time():
    view = _long_view()

    for _ in range(4):
        _turn(view, 100, frame_each=False)
        view._frame_start = None

    assert view.top == 1020


def test_turning_back_within_a_frame_is_measured_from_where_the_frame_began():
    view = _long_view()

    _turn(view, 100, frame_each=False)
    assert view.top == 1005
    _turn(view, 100, up=True, frame_each=False)

    assert view.top == 995, "five rows the other side of where the frame began, and no more"


def test_a_window_one_row_high_still_moves_a_row_an_event():
    view = ScrollView(RecordingSource([f"l{n}" for n in range(50)]), follow_tail=False)
    view.layout(Rect(0, 0, 20, 1))
    view.scroll_to(10)

    _turn(view, 3, frame_each=False)

    assert view.top == 11, "at least one row a frame, or the wheel would do nothing"


def test_rendering_starts_a_new_frame():
    view = _long_view()
    _turn(view, 100, frame_each=False)
    assert view.top == 1005

    view.render(Canvas(20, 10))
    _turn(view, 100, frame_each=False)

    assert view.top == 1010


def test_the_speed_is_the_rows_an_event_moves_and_a_fraction_is_carried_to_the_next_event():
    view = _long_view(wheel_speed=0.5)

    assert _turn(view, 6) == [0, 1, 0, 1, 0, 1]


def test_a_speed_of_three_moves_three_rows_a_notch():
    view = _long_view(wheel_speed=3)

    assert _turn(view, 4) == [3, 3, 3, 3]


def test_a_speed_of_a_tenth_reaches_a_whole_row_after_ten_events_despite_rounding_in_the_sum():
    view = _long_view(wheel_speed=0.1)

    moved = _turn(view, 30)

    assert sum(moved) == 3 and moved.count(1) == 3


def test_the_carried_fraction_is_dropped_when_the_wheel_turns_the_other_way():
    view = _long_view(wheel_speed=0.4)
    _turn(view, 2)  # 0.8 owed, down

    moved = _turn(view, 3, up=True)  # starts again from nothing: 0.4, 0.8, 1.2

    assert moved == [0, 0, 1]


@pytest.mark.parametrize("speed", [0, -1, float("nan"), float("inf"), -0.0])
def test_a_speed_that_cannot_mean_anything_is_the_default(speed):
    from zettcode.tui.layout.scroll import WHEEL_SPEED

    view = _long_view(wheel_speed=speed)

    assert view.wheel_speed == WHEEL_SPEED
    assert _turn(view, 3) == [1, 1, 1]


def test_a_view_that_selects_text_scrolls_the_same_way_as_one_that_does_not():
    """The transcript is one: its wheel goes through the pointer handler, not the plain one."""
    view = _long_view(selectable=True)

    assert _turn(view, 20) == [1] * 20
    assert _turn(_long_view(selectable=True), 100, frame_each=False) == [1] * 5 + [0] * 95


def test_an_event_outside_the_view_neither_moves_it_nor_owes_it_anything():
    from zettcode.tui import MouseAction, MouseEvent

    view = _long_view(wheel_speed=0.5)
    app = Harness(view, width=20, height=10).app
    top = view.top

    handled = view.handle(MouseEvent(x=50, y=50, action=MouseAction.SCROLL_DOWN), app)

    assert handled is False and view.top == top and view._wheel_owed == 0.0


def test_scrolling_still_stops_at_both_ends_however_many_events_there_are():
    view = _long_view(lines=40)

    _turn(view, 60)
    assert view.top == view.max_top and view.follow_tail
    _turn(view, 80, up=True)
    assert view.top == 0 and not view.follow_tail


@pytest.mark.parametrize("selectable", [False, True])
def test_the_wheel_is_one_row_an_event_scrolling_up_as_well_as_down_in_both_kinds_of_view(selectable):
    view = _long_view(selectable=selectable)
    view.scroll_to(1800)

    assert _turn(view, 20, up=True) == [1] * 20
    assert view.top == 1780
