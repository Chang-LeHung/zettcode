"""Contract tests for the standalone TUI framework core and its test harness."""

import pytest

from zettcode.tui_framework import (
    AnyEvent,
    Completer,
    Constraints,
    EdgeInsets,
    EventKind,
    Host,
    KeyEvent,
    LineSource,
    MarkdownSource,
    PasteEvent,
    Point,
    Rect,
    Size,
    StaticLines,
    Style,
    TextEvent,
    TuiApp,
    Widget,
)
from zettcode.tui_framework.testing import Harness


class Demo(Widget):
    """Minimal editable widget exercising every part of the contract."""

    def __init__(self) -> None:
        super().__init__()
        self.typed = ""
        self.keys: list[str] = []
        self.resizes: list[Rect] = []
        self.focused = False

    def render(self, canvas) -> None:
        canvas.draw_text(self.rect.x, self.rect.y, f"demo:{self.typed}", max_width=self.rect.width)

    def handle(self, event: AnyEvent, host: Host) -> bool:
        if isinstance(event, (TextEvent, PasteEvent)):
            self.typed += event.text
            return True
        if isinstance(event, KeyEvent):
            self.keys.append(event.key)
            if event.key == "backspace" and self.typed:
                self.typed = self.typed[:-1]
                return True
            if event.key == "ctrl_c":
                host.copy(self.typed)
                return True
            if event.key == "escape":
                host.exit()
                return True
        return False

    def cursor(self) -> Point | None:
        return Point(self.rect.x + 5 + len(self.typed), self.rect.y)

    def on_resize(self, rect: Rect) -> None:
        self.resizes.append(rect)

    def on_focus(self) -> None:
        self.focused = True

    def on_blur(self) -> None:
        self.focused = False


class Tracked(Widget):
    """Widget that counts lifecycle calls and exposes explicit children."""

    def __init__(self, kids: tuple[Widget, ...] = ()) -> None:
        super().__init__()
        self.kids = kids
        self.mounts = 0
        self.unmounts = 0

    @property
    def children(self) -> tuple[Widget, ...]:
        return self.kids

    def on_mount(self) -> None:
        self.mounts += 1

    def on_unmount(self) -> None:
        self.unmounts += 1


class Badge(Widget):
    """Widget painting one styled run."""

    def render(self, canvas) -> None:
        canvas.draw_text(0, 0, "hi", Style(foreground="#ff0000", bold=True))


def test_rect_geometry_is_clipped_and_absolute():
    rect = Rect(1, 2, 3, 4)

    assert (rect.right, rect.bottom) == (4, 6)
    assert rect.contains(1, 2)
    assert not rect.contains(4, 2)
    assert rect.inset(EdgeInsets.symmetric(vertical=1, horizontal=1)) == Rect(2, 3, 1, 2)
    assert rect.translate(2, -1) == Rect(3, 1, 3, 4)
    assert rect.intersection(Rect(3, 3, 5, 5)) == Rect(3, 3, 1, 3)
    assert Rect(0, 0, 0, 0).union(rect) == rect


def test_host_is_abstract_and_tui_app_implements_all_of_it():
    """The contract is enforced by inheritance, not by looking compatible."""

    class Partial(Host):
        def focus(self, widget) -> None:
            return None

    assert issubclass(TuiApp, Host)

    with pytest.raises(TypeError, match="abstract"):
        Host()
    with pytest.raises(TypeError, match="abstract"):
        Partial()

    # TuiApp answers every method, so it is the one class that can be built.
    assert TuiApp(Widget(), width=4, height=1).focused_widget() is None


def test_line_source_and_completer_are_abstract_too():
    """Every framework contract is a base class, and its users subclass it."""

    assert issubclass(StaticLines, LineSource)
    assert issubclass(MarkdownSource, LineSource)

    with pytest.raises(TypeError, match="abstract"):
        LineSource()
    with pytest.raises(TypeError, match="abstract"):
        Completer()


def test_constraints_clamp_measurements_and_deflate():
    assert Constraints.tight(Size(10, 5)).constrain(Size(3, 3)) == Size(10, 5)
    assert Constraints.loose(Size(10, 5)).constrain(Size(100, 100)) == Size(10, 5)
    assert Constraints.unbounded().constrain(Size(7, 9)) == Size(7, 9)
    assert Constraints(min_width=2, max_width=8).constrain(Size(1, 1)) == Size(2, 1)
    deflated = Constraints.loose(Size(10, 10)).deflate(EdgeInsets.all(2))
    assert deflated.constrain(Size(99, 99)) == Size(6, 6)


def test_events_carry_kind_and_modifiers():
    key = KeyEvent(key="a", control=True, repeat=True)
    text = TextEvent(text="é")

    assert key.kind is EventKind.KEY
    assert text.kind is EventKind.TEXT
    assert (key.control, key.repeat) == (True, True)
    assert key.alt is False
    assert isinstance(key, KeyEvent)
    assert not isinstance(text, KeyEvent)


def test_widget_mount_runs_once_and_links_children():
    child = Tracked()
    root = Tracked((child,))

    root.mount()
    root.mount()

    assert (root.mounts, child.mounts) == (1, 1)
    assert child.parent is root

    root.unmount()

    assert (root.unmounts, child.unmounts) == (1, 1)


def test_widget_reports_resize_only_when_the_rectangle_changes():
    demo = Demo()

    demo.layout(Rect(0, 0, 10, 4))
    demo.layout(Rect(0, 0, 10, 4))
    demo.layout(Rect(0, 0, 20, 4))

    assert demo.resizes == [Rect(0, 0, 10, 4), Rect(0, 0, 20, 4)]


def test_harness_paints_a_snapshot_through_the_real_renderer():
    harness = Harness(Badge(), width=6, height=2)

    snapshot = harness.render()

    assert snapshot.lines[0] == "hi    "
    assert snapshot.text.splitlines()[0] == "hi"
    assert snapshot.styled[0][0].text == "hi"
    assert snapshot.styled[0][0].style.bold is True
    assert "\x1b[" in harness.last_frame


def test_harness_delivers_text_keys_and_paste():
    harness = Harness(Demo(), width=40, height=2)

    assert harness.write("hey") is True
    assert harness.press("backspace") is True
    assert harness.paste("!!") is True

    assert harness.text().splitlines()[0] == "demo:he!!"
    assert harness.root.keys == ["backspace"]


def test_harness_focus_hooks_and_cursor_follow_the_focused_widget():
    demo = Demo()
    harness = Harness(demo, width=20, height=2)

    harness.focus(demo)
    harness.write("ab")

    assert demo.focused is True
    assert harness.render().cursor == Point(7, 0)

    harness.focus(None)

    assert demo.focused is False


def test_harness_resize_and_host_services_reach_the_widget():
    demo = Demo()
    harness = Harness(demo, width=20, height=2)
    harness.write("abc")

    harness.resize(30, 5)
    harness.render()

    assert demo.resizes[-1] == Rect(0, 0, 30, 5)

    harness.press("ctrl_c")
    assert harness.clipboard == "abc"

    harness.press("escape")
    assert harness.exited is True
