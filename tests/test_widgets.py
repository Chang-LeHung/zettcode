"""Tests for the M4 widget library."""

from zettcode.tui import (
    DARK,
    Canvas,
    Collapsible,
    Column,
    CompletionItem,
    CompletionPopup,
    Constraints,
    Dialog,
    DialogAction,
    ListItem,
    ListPage,
    ListView,
    Point,
    ProgressBar,
    Rect,
    Screen,
    Size,
    Spinner,
    StatusBar,
    Table,
    TextArea,
    Toast,
    TuiApp,
    Widget,
    centered,
)
from zettcode.tui.render import display_width
from zettcode.tui.testing import Harness
from zettcode.tui.widgets.progress import DEFAULT_FRAMES
from zettcode.tui.widgets.textarea import layout_input


class Label(Widget):
    """Widget with a measurable intrinsic size."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self.text = text

    def measure(self, constraints: Constraints) -> Size:
        return constraints.constrain(Size(display_width(self.text), 1))

    def render(self, canvas: Canvas) -> None:
        canvas.draw_text(self.rect.x, self.rect.y, self.text, max_width=self.rect.width)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def row_text(canvas: Canvas, y: int) -> str:
    return "".join(cell.character for cell in canvas.cells[y] if not cell.continuation)


def test_list_view_navigates_wraps_and_activates():
    chosen: list[object] = []
    highlighted: list[object] = []
    items = [ListItem(f"item-{index}", label=f"item-{index}") for index in range(4)]
    view = ListView(
        items, on_select=lambda item: chosen.append(item.value), on_highlight=lambda i: highlighted.append(i.value)
    )
    harness = Harness(view, width=20, height=2)

    assert harness.focused_widget() is view
    harness.press("down")
    harness.press("down")
    harness.press("down")

    assert view.selected == 3
    assert highlighted == ["item-1", "item-2", "item-3"]
    text = harness.render().text
    assert view.top == 2
    assert "item-2" in text and "item-3" in text

    harness.press("down")
    harness.press("enter")

    assert view.selected == 0
    assert chosen == ["item-0"]


def test_list_view_skips_disabled_rows_and_selects_on_click():
    items = [ListItem("a", label="a"), ListItem("b", label="b", disabled=True), ListItem("c", label="c")]
    view = ListView(items, wrap=False)
    harness = Harness(view, width=10, height=3)

    harness.press("down")

    assert view.selected == 2
    harness.press("down")
    assert view.selected == 2

    harness.click(0, 0)

    assert view.selected == 0


def test_status_bar_aligns_both_segments_and_clips_on_narrow_widths():
    wide = Canvas(20, 1)
    bar = StatusBar("left", "right")
    bar.layout(Rect(0, 0, 20, 1))
    bar.render(wide)

    assert row_text(wide, 0).startswith("left")
    assert row_text(wide, 0).endswith("right")

    narrow = Canvas(6, 1)
    small = StatusBar("left", "right")
    small.layout(Rect(0, 0, 6, 1))
    small.render(narrow)

    assert row_text(narrow, 0) == "\u2026right"


def test_table_renders_header_rule_and_aligned_cells():
    table = Table([Column("Name"), Column("Count", align="right")], [["alpha", "12"]])
    table.layout(Rect(0, 0, 20, 4))
    canvas = Canvas(20, 4)

    table.render(canvas)

    assert "Name" in row_text(canvas, 0)
    assert set(row_text(canvas, 1).strip()) == {"\u2500", " "}
    assert "\u2502" not in row_text(canvas, 1)
    assert "alpha" in row_text(canvas, 2)
    assert row_text(canvas, 2).rstrip().endswith("12")


def test_table_shrinks_columns_to_fit_the_rectangle():
    table = Table([Column("first"), Column("second"), Column("third")], [["a very long value", "another", "third"]])
    table.layout(Rect(0, 0, 14, 3))
    canvas = Canvas(14, 3)

    table.render(canvas)

    rendered = [row_text(canvas, row) for row in range(3)]
    assert all(display_width(row) <= 14 for row in rendered)
    assert "a very" in "\n".join(rendered)


def test_collapsible_toggles_body_and_reveals_it_to_the_tree():
    body = Label("body")
    block = Collapsible("title", body)
    harness = Harness(block, width=20, height=3)

    assert block.children == ()
    assert harness.render().text.startswith("\u25b8 title")

    harness.press("enter")

    assert block.expanded is True
    assert block.children == (body,)
    assert "body" in harness.render().text
    assert Rect(0, 1, 20, 2) == body.rect


def test_completion_popup_bands_the_selection_and_scrolls():
    items = [CompletionItem(f"/cmd{index}", description=f"about {index}") for index in range(4)]
    popup = CompletionPopup(items, max_height=3)
    popup.layout(Rect(0, 0, 24, 3))
    canvas = Canvas(24, 3)

    popup.render(canvas)

    # No frame: the menu is a list, and the selection is a band across the row
    # rather than a border drawn around the text.
    # The band pads the row to the full width, so compare the visible text.
    assert row_text(canvas, 0).rstrip() == " /cmd0  about 0"
    assert popup.preferred_size().height == 3
    assert {cell.style.background for cell in canvas.cells[0]} == {DARK.selection}
    assert canvas.cells[1][1].style.background is None

    popup.move(3)

    assert popup.current.value == "/cmd3"
    popup.render(canvas)
    assert "/cmd3" in row_text(canvas, 2)
    assert popup.top == 1


def test_list_page_shows_a_title_scrolls_and_keeps_a_bounded_list():
    page = ListPage(
        [ListItem(f"item-{index}", f"row {index}") for index in range(10)],
        title="Select Item",
        visible_rows=4,
    )
    harness = Harness(page, width=30, height=12)
    text = harness.render().text

    assert "Select Item" in text
    assert "row 0" in text
    assert "esc back" in text
    assert page.list.rect.height == 4

    for _ in range(6):
        harness.press("down")

    assert page.list.selected == 6
    text = harness.render().text
    assert page.list.top > 0
    assert "row 6" in text
    assert "row 0" not in text


def test_list_page_commits_a_row_and_cancels_on_escape():
    chosen: list[ListItem] = []
    cancelled: list[bool] = []
    page = ListPage(
        [ListItem("a", "alpha"), ListItem("b", "beta")],
        title="Pick",
        on_select=chosen.append,
        on_cancel=lambda: cancelled.append(True),
    )
    harness = Harness(page, width=30, height=12)

    harness.press("enter")

    assert [item.value for item in chosen] == ["a"]

    harness.press("escape")

    assert cancelled == [True]


def test_list_page_without_a_cancel_handler_ignores_escape():
    page = ListPage([ListItem("a", "alpha")], title="Pick")
    harness = Harness(page, width=30, height=12)

    assert harness.press("escape") is False


def test_spinner_advances_with_the_clock_and_holds_a_frame_budget():
    clock = FakeClock()
    spinner = Spinner("working", clock=clock)
    app = TuiApp(spinner, width=20, height=1, clock=clock)
    app.mount()

    spinner.start()

    assert app.scheduler.animating is True
    assert spinner.frame == DEFAULT_FRAMES[0]
    clock.now = 0.12
    assert spinner.frame == DEFAULT_FRAMES[1]

    spinner.stop()

    assert app.scheduler.animating is False
    assert spinner.frame == DEFAULT_FRAMES[0]


def test_reduced_motion_suppresses_decorative_animation():
    clock = FakeClock()
    spinner = Spinner("working", clock=clock)
    app = TuiApp(spinner, width=20, height=1, clock=clock, reduced_motion=True)
    app.mount()

    spinner.start()

    assert app.scheduler.animating is False
    clock.now = 5.0
    assert spinner.frame == DEFAULT_FRAMES[0]


def test_progress_bar_fills_proportionally():
    bar = ProgressBar(0.5, label="")
    bar.layout(Rect(0, 0, 10, 1))
    canvas = Canvas(10, 1)

    bar.render(canvas)

    assert row_text(canvas, 0) == "\u2588" * 5 + "\u2591" * 5


def test_toast_expires_on_the_clock_and_dismisses_its_screen():
    clock = FakeClock()
    calls: list[str] = []
    app = TuiApp(Label("base"), width=20, height=5, clock=clock)
    app.mount()
    toast = Toast("saved", duration=2.0, clock=clock)
    app.push_screen(Screen(centered(toast, vertical="end"), name="toast", modal=True))

    assert toast.expired is False
    clock.now = 1.0
    assert toast.expired is False
    assert toast.remaining == 1.0
    app.tick()
    assert len(app.screens) == 2
    clock.now = 2.0
    assert toast.expired is True
    app.tick()

    assert len(app.screens) == 1

    handled = Toast("again", duration=0.0, clock=clock, on_expire=lambda: calls.append("expired"))
    app.push_screen(Screen(centered(handled), modal=True))
    app.tick()

    assert calls == ["expired"]
    assert len(app.screens) == 2


def test_dialog_moves_between_actions_and_cancels():
    calls: list[str] = []
    dialog = Dialog(
        Label("body"),
        title="Confirm",
        actions=(DialogAction("Yes", lambda: calls.append("yes")), DialogAction("No", lambda: calls.append("no"))),
        on_cancel=lambda: calls.append("cancel"),
    )
    harness = Harness(dialog, width=30, height=8)
    app = harness.app
    app.push_screen(Screen(centered(dialog), name="dialog", modal=True))

    harness.press("right")
    harness.press("enter")

    assert calls == ["no"]
    assert dialog.action_index == 1

    harness.press("escape")

    assert calls == ["no", "cancel"]


def test_text_area_edits_wraps_and_reports_the_cursor():
    area = TextArea(prompt="\u203a ")
    harness = Harness(area, width=20, height=3)

    assert harness.focused_widget() is area
    harness.write("hi")

    assert area.text == "hi"
    assert harness.render().cursor == Point(4, 0)

    harness.press("alt_enter")
    harness.write("there")

    assert area.text == "hi\nthere"
    assert area.preferred_height(20) == 2


def test_text_area_surface_paints_a_padded_input_band():
    area = TextArea(prompt="\u203a ", placeholder="Ask anything", surface=True)
    harness = Harness(area, width=24, height=3)
    canvas = harness.app.render()

    assert area.preferred_height(24) == 3
    assert {cell.style.background for row in canvas.cells for cell in row} == {DARK.surface_alt}
    assert canvas.cells[1][2].character == "\u203a"
    assert area.cursor() == Point(4, 1)

    harness.write("hello")
    canvas = harness.app.render()
    assert "".join(cell.character for cell in canvas.cells[1]).strip() == "\u203a hello"


def test_text_area_keeps_word_editing_undo_and_yank():
    area = TextArea()
    harness = Harness(area, width=30, height=3)
    harness.write("alpha beta")

    harness.press("ctrl_w")
    assert area.text == "alpha "

    harness.press("ctrl_y")
    assert area.text == "alpha beta"

    harness.press("ctrl_z")
    assert area.text == "alpha "

    harness.press("ctrl_a")
    harness.press("ctrl_k")
    assert area.text == ""
    harness.press("ctrl_y")
    assert area.text == "alpha "

    harness.press("ctrl_end")
    harness.press("ctrl_left")
    assert area.position == 0


def test_text_area_submits_recalls_history_and_respects_rejection():
    submitted: list[str] = []
    area = TextArea(on_submit=lambda value: submitted.append(value))
    harness = Harness(area, width=30, height=3)

    harness.write("first task")
    harness.press("enter")

    assert submitted == ["first task"]
    assert area.text == ""
    assert area.history == ("first task",)

    harness.press("up")
    assert area.text == "first task"
    harness.press("down")
    assert area.text == ""

    rejecting = TextArea(on_submit=lambda value: False)
    rejecting_harness = Harness(rejecting, width=30, height=3)
    rejecting_harness.write("keep me")
    rejecting_harness.press("enter")

    assert rejecting.text == "keep me"
    assert rejecting.history == ()


def test_text_area_cycles_completions_and_layouts_wrapped_input():
    area = TextArea(completions=("/clear", "/close", "/quit"))
    harness = Harness(area, width=30, height=3)
    harness.write("/cl")

    assert len(area.completion_candidates()) == 2
    harness.press("tab")
    assert area.text == "/clear"
    harness.press("tab")
    assert area.text == "/close"
    harness.press("backtab")
    assert area.text == "/clear"

    assert layout_input("123", 3, 5, 2) == (["123", ""], (1, 0))
