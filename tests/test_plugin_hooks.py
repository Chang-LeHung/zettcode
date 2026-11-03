"""The window's own events, and the plugin hooks they reach: focus, and the end of a turn."""

from __future__ import annotations

import asyncio
from dataclasses import replace

from test_zettcode_app import _harness, build_app, rows_and_commands
from zettcode.app.plugins.state import UiRow  # noqa: F401 - imported for the bundle's field order in one test
from zettcode.tui import FocusEvent, TuiApp, Widget
from zettcode.tui.core.events import KeyEvent
from zettcode.tui.input.bridge import translate
from zettcode.tui.input.decoder import InputDecoder


def test_a_listener_sees_an_event_before_any_widget_does():
    app = TuiApp(Widget(), width=20, height=4)
    seen: list[object] = []
    app.add_listener(seen.append)

    app.dispatch(FocusEvent(focused=False))
    app.dispatch(KeyEvent(key="a"))

    assert [type(event).__name__ for event in seen] == ["FocusEvent", "KeyEvent"]


def test_a_focus_report_from_the_terminal_becomes_a_focus_event():
    (input_event,) = InputDecoder().feed(b"\x1b[O")

    assert translate(input_event) == FocusEvent(focused=False)


async def test_a_plugin_hears_the_window_lose_focus_and_the_edges_of_a_turn():
    """The hooks a plugin that waits for the reader to stop asking is built on."""
    seen: list[tuple[str, object]] = []
    plugins = replace(
        rows_and_commands(),
        focus_handlers=(lambda focused: seen.append(("focus", focused)),),
        turn_start_handlers=(lambda: seen.append(("started", True)),),
        turn_end_handlers=(lambda completed: seen.append(("ended", completed)),),
    )
    app = build_app(plugins=plugins)
    harness = _harness(app)

    app.app.dispatch(FocusEvent(focused=False))
    app.app.dispatch(FocusEvent(focused=True))

    harness.write("hello")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert seen == [("focus", False), ("focus", True), ("started", True), ("ended", True)], (
        "a turn is announced at both ends"
    )


async def test_a_hook_that_raises_is_told_once_and_the_turn_still_ends():
    def broken(focused: bool) -> None:
        raise RuntimeError("the plugin is broken")

    app = build_app(plugins=replace(rows_and_commands(), focus_handlers=(broken,)))
    harness = _harness(app)

    app.app.dispatch(FocusEvent(focused=False))
    app.app.dispatch(FocusEvent(focused=True))

    said = [entry.text for entry in app.transcript.entries if entry.kind == "notice"]
    assert sum("a plugin hook failed" in text for text in said) == 1, "told once, not on every event"
    harness.write("hello")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)
    assert "Processed for" in harness.render().text
