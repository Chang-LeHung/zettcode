"""Tests for the M2 runtime: themes, scheduling, keymaps, focus, and routing."""

import pytest

from zettcode.tui import (
    Anchor,
    CommandRegistry,
    Constraints,
    KeyEvent,
    Keymap,
    MouseAction,
    MouseEvent,
    Overlay,
    OverlaySlot,
    PasteEvent,
    Rect,
    ResizeEvent,
    Scheduler,
    Screen,
    Size,
    Style,
    Text,
    TextEvent,
    Theme,
    TuiApp,
    Widget,
    key_id,
    normalize_key,
    theme_named,
)
from zettcode.tui.core.theme import DARK, LIGHT


class Pane(Widget):
    """Test widget that records event phases and can split its rect."""

    def __init__(
        self,
        name: str,
        log: list[str],
        *,
        kids: tuple[Widget, ...] = (),
        focusable: bool = False,
        split: bool = False,
        consume: bool = False,
    ) -> None:
        super().__init__()
        self.name = name
        self.log = log
        self.kids = kids
        self._focusable = focusable
        self.split = split
        self.consume = consume

    @property
    def children(self) -> tuple[Widget, ...]:
        return self.kids

    @property
    def focusable(self) -> bool:
        return self._focusable

    def layout(self, rect: Rect) -> None:
        super().layout(rect)
        if self.split and self.kids:
            share = max(1, rect.height // len(self.kids))
            y = rect.y
            for index, child in enumerate(self.kids):
                height = rect.y + rect.height - y if index == len(self.kids) - 1 else share
                child.layout(Rect(rect.x, y, rect.width, max(0, height)))
                y += height
            return
        for child in self.kids:
            child.layout(rect)

    def capture_event(self, event, host) -> bool:
        self.log.append(f"capture:{self.name}")
        return False

    def handle(self, event, host) -> bool:
        self.log.append(f"handle:{self.name}")
        return self.consume

    def bubble_event(self, event, host) -> bool:
        self.log.append(f"bubble:{self.name}")
        return False


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Filler(Widget):
    """Paint one character across the whole rectangle."""

    def __init__(self, character: str = "A") -> None:
        super().__init__()
        self.character = character

    def measure(self, constraints: Constraints):
        return constraints.constrain(Size(constraints.max_width or 0, constraints.max_height or 0))

    def render(self, canvas) -> None:
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(), self.character)


def canvas_text(app: TuiApp) -> str:
    canvas = app.render()
    return "\n".join("".join(cell.character for cell in row if not cell.continuation) for row in canvas.cells)


def test_popping_a_screen_clears_what_the_overlay_covered():
    app = TuiApp(Filler("A"), width=12, height=4)
    app.mount()

    assert set(canvas_text(app).replace("\n", "")) == {"A"}

    app.push_screen(
        Screen(
            Overlay(
                [
                    OverlaySlot(
                        Filler("B"),
                        Anchor(horizontal="center", vertical="center", width=4, height=2),
                    )
                ]
            ),
            modal=True,
        )
    )
    covered = canvas_text(app)

    assert "B" in covered
    assert "A" in covered

    app.pop_screen()

    assert set(canvas_text(app).replace("\n", "")) == {"A"}


def test_a_framed_overlay_is_opaque():
    """An overlay panel must not let the screen behind it show through."""
    from zettcode.tui.layout import Border

    app = TuiApp(Filler("A"), width=20, height=6)
    app.mount()
    panel = Border()

    app.push_screen(
        Screen(
            Overlay(
                [
                    OverlaySlot(
                        panel,
                        Anchor(horizontal="center", vertical="center", width=10, height=3),
                    )
                ]
            ),
            modal=True,
        )
    )
    rows = canvas_text(app).split("\n")

    assert panel.rect == Rect(5, 1, 10, 3)
    assert rows[1][5] == "\u250c" and rows[1][14] == "\u2510"
    interior = "".join(row[6:14] for row in rows[2:4])
    assert "A" not in interior


def test_theme_tokens_are_semantic_and_named_lookup_works():
    assert DARK.accent != LIGHT.accent
    assert DARK.name == "dark"
    assert theme_named("light") is LIGHT
    assert Theme(name="custom").text

    with pytest.raises(ValueError, match="Unknown theme"):
        theme_named("solarized")


def test_switching_the_theme_repaints_the_whole_frame():
    """A palette switch drops the previous frame instead of diffing against it.

    Widgets read the theme while painting, but the differential renderer still
    holds the cells it wrote last; repainting the whole screen is what keeps a
    switch from leaving the parts that happen to match in the old palette.
    """
    from zettcode.tui.testing import Harness

    app = TuiApp(Text("hello"), width=20, height=3, theme=DARK)
    harness = Harness(app=app)
    harness.render()

    app.theme = LIGHT
    harness.render()

    assert harness.last_frame.startswith("\x1b[2J")


def test_scheduler_frames_repaints_and_animation_budget():
    clock = FakeClock()
    scheduler = Scheduler(max_fps=10, clock=clock)

    assert scheduler.poll() is True
    assert scheduler.poll() is False
    scheduler.request_repaint()
    assert scheduler.delay() == 0.0
    assert scheduler.poll() is True
    assert scheduler.delay() is None

    scheduler.animate("spin")
    assert scheduler.animating is True
    assert scheduler.animations == ("spin",)
    assert scheduler.poll() is False
    clock.now = 0.1
    assert scheduler.poll() is True

    scheduler.animate("spin", active=False)
    assert scheduler.animating is False
    assert scheduler.delay() is None

    with pytest.raises(ValueError, match="max_fps"):
        Scheduler(max_fps=0)
    with pytest.raises(ValueError, match="token"):
        scheduler.animate("")


def test_keymap_normalizes_spellings_and_modifiers():
    assert normalize_key("Ctrl-C") == "ctrl_c"
    assert normalize_key("alt+enter") == "alt_enter"
    assert normalize_key("page_up") == "page_up"
    assert key_id(KeyEvent(key="a", control=True)) == "ctrl_a"
    assert key_id(KeyEvent(key="ctrl_c")) == "ctrl_c"
    assert key_id(KeyEvent(key="a", alt=True, shift=True)) == "alt_shift_a"

    keymap = Keymap()
    keymap.bind("Ctrl+C", "quit", priority="capture")

    assert keymap.resolve(KeyEvent(key="ctrl_c"), priority="capture") == "quit"
    assert keymap.resolve(KeyEvent(key="ctrl_c"), priority="bubble") is None
    assert keymap.bindings_for("ctrl+c")[0].command == "quit"


def test_keymap_matches_a_typed_character_as_well_as_a_named_key():
    """A terminal reports a printable key as text, so bindings must see both."""
    keymap = Keymap()
    keymap.bind("q", "quit", priority="capture")

    assert keymap.resolve(TextEvent(text="q"), priority="capture") == "quit"
    assert keymap.resolve(KeyEvent(key="q"), priority="capture") == "quit"
    assert keymap.resolve(TextEvent(text="quit"), priority="capture") is None
    assert keymap.resolve(PasteEvent(text="q"), priority="capture") is None


def test_keymap_context_predicates_split_priorities_and_unbind():
    enabled = False
    keymap = Keymap()
    keymap.bind("x", "capture_action", priority="capture")
    keymap.bind("x", "context_action", when=lambda: enabled)

    assert keymap.resolve(KeyEvent(key="x"), priority="bubble") is None
    assert keymap.resolve(KeyEvent(key="x"), priority="capture") == "capture_action"

    enabled = True
    assert keymap.resolve(KeyEvent(key="x"), priority="bubble") == "context_action"
    assert keymap.unbind("x", "context_action") == 1
    assert keymap.resolve(KeyEvent(key="x"), priority="bubble") is None
    assert keymap.unbind("x") == 1
    assert keymap.unbind("x") == 0

    with pytest.raises(ValueError, match="priority"):
        keymap.bind("y", "action", priority="middle")
    with pytest.raises(ValueError, match="command"):
        keymap.bind("y", "")


def test_command_registry_runs_named_commands():
    registry = CommandRegistry()
    registry.add("ping", lambda event, host: True, description="respond")
    seen: list[str] = []
    registry.add("record", lambda event, host: seen.append("ran") or True)

    assert registry.names == ("ping", "record")
    assert registry.run("record", KeyEvent(key="a"), None) is True
    assert seen == ["ran"]
    assert registry.run("missing", KeyEvent(key="a"), None) is False
    assert registry.get("ping").description == "respond"

    with pytest.raises(ValueError, match="name"):
        registry.add("", lambda event, host: True)


def test_routing_runs_capture_target_then_bubble():
    log: list[str] = []
    leaf = Pane("leaf", log, focusable=True)
    mid = Pane("mid", log, kids=(leaf,))
    root = Pane("root", log, kids=(mid,))
    app = TuiApp(root, width=20, height=4)
    app.mount()
    app.focus(leaf)

    handled = app.dispatch(KeyEvent(key="a"))

    assert handled is False
    assert log == ["capture:root", "capture:mid", "capture:leaf", "handle:leaf", "bubble:mid", "bubble:root"]


def test_a_consuming_target_stops_the_bubble_phase():
    log: list[str] = []
    leaf = Pane("leaf", log, focusable=True, consume=True)
    root = Pane("root", log, kids=(leaf,))
    app = TuiApp(root, width=20, height=4)
    app.mount()
    app.focus(leaf)

    assert app.dispatch(KeyEvent(key="a")) is True
    assert log == ["capture:root", "capture:leaf", "handle:leaf"]


def test_capture_binding_wins_and_bubble_binding_runs_after_the_target():
    log: list[str] = []
    leaf = Pane("leaf", log, focusable=True)
    root = Pane("root", log, kids=(leaf,))
    app = TuiApp(root, width=20, height=4)
    app.mount()
    app.focus(leaf)
    app.commands.add("cap", lambda event, host: log.append("cap") or True)
    app.commands.add("bub", lambda event, host: log.append("bub") or True)
    app.keymap.bind("x", "cap", priority="capture")
    app.keymap.bind("x", "bub")

    assert app.dispatch(KeyEvent(key="x")) is True
    assert log == ["capture:root", "capture:leaf", "cap"]

    log.clear()
    app.keymap.unbind("x", "cap")

    assert app.dispatch(KeyEvent(key="x")) is True
    # The bubble binding runs before the bubble hooks, so consuming it there
    # means the tree never sees the event again on the way back up.
    assert log == ["capture:root", "capture:leaf", "handle:leaf", "bub"]


def test_focus_traversal_visits_focusable_widgets_in_tree_order():
    log: list[str] = []
    first = Pane("first", log, focusable=True)
    second = Pane("second", log, focusable=True)
    root = Pane("root", log, kids=(first, second))
    app = TuiApp(root, width=20, height=4)
    app.mount()

    # Mounting focuses the first Tab stop so a composer is ready immediately.
    assert app.focused_widget() is first
    assert app.focus_next() is second
    assert app.focus_next() is first
    assert app.focus_next(-1) is second
    assert app.focus_manager.focusables(root) == [first, second]


def test_modal_screen_traps_input_and_restores_focus_on_pop():
    log: list[str] = []
    base_leaf = Pane("base_leaf", log, focusable=True)
    base = Pane("base", log, kids=(base_leaf,))
    modal_leaf = Pane("modal_leaf", log, focusable=True)
    modal = Pane("modal", log, kids=(modal_leaf,))
    app = TuiApp(base, width=20, height=4)
    app.mount()
    app.focus(base_leaf)

    app.push_screen(Screen(modal, name="modal", modal=True))

    assert app.focused_widget() is modal_leaf
    log.clear()
    app.dispatch(KeyEvent(key="a"))
    assert log == ["capture:modal", "capture:modal_leaf", "handle:modal_leaf", "bubble:modal"]

    log.clear()
    app.dispatch(MouseEvent(x=1, y=1, action=MouseAction.DOWN))
    assert all("base" not in entry for entry in log)

    app.pop_screen()

    assert app.focused_widget() is base_leaf
    assert len(app.screens) == 1
    assert app.pop_screen() is None


def test_mouse_routing_uses_paint_order_and_resize_updates_geometry():
    log: list[str] = []
    top = Pane("top", log, focusable=True)
    bottom = Pane("bottom", log, focusable=True)
    root = Pane("root", log, kids=(top, bottom), split=True)
    app = TuiApp(root, width=20, height=4)
    app.mount()
    app.layout()

    log.clear()
    app.dispatch(MouseEvent(x=1, y=0, action=MouseAction.DOWN))
    assert log == ["capture:root", "capture:top", "handle:top", "bubble:root"]

    log.clear()
    app.dispatch(MouseEvent(x=1, y=2, action=MouseAction.DOWN))
    assert "handle:bottom" in log

    app.dispatch(ResizeEvent(width=30, height=8))
    assert (app.width, app.height) == (30, 8)
    app.layout()
    assert top.rect == Rect(0, 0, 30, 4)
    assert bottom.rect == Rect(0, 4, 30, 4)


def test_widgets_see_the_app_theme_and_unhandled_events_return_false():
    log: list[str] = []
    root = Pane("root", log)
    app = TuiApp(root, width=20, height=4, theme=LIGHT)
    app.mount()

    assert root.theme is LIGHT
    assert app.dispatch(KeyEvent(key="a")) is False
    assert app.running is True

    app.exit()

    assert app.running is False
