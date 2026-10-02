"""Tests for the terminal, input, and render layers that stayed in the framework."""

import builtins
import importlib
import sys
from io import StringIO

import pytest

from zettcode.tui import (
    Canvas,
    DifferentialRenderer,
    EventType,
    InputDecoder,
    InputEvent,
    MouseAction,
    Span,
    Style,
    TextLine,
)


def test_tui_imports_where_termios_is_unavailable(monkeypatch) -> None:
    """ZettCode must load on platforms without raw-mode terminal modules."""
    real_import = builtins.__import__
    saved_modules = {name: sys.modules.get(name) for name in ("zettcode.tui.terminal", "zettcode.tui")}

    def blocked(name, *args, **kwargs):
        if name in {"termios", "tty"}:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    try:
        for module_name in saved_modules:
            sys.modules.pop(module_name, None)
        module = importlib.import_module("zettcode.tui")
        assert hasattr(module, "Terminal")
    finally:
        for module_name, saved in saved_modules.items():
            if saved is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = saved


def test_terminal_refuses_platforms_without_posix_raw_mode(monkeypatch) -> None:
    from zettcode.tui import terminal as terminal_module

    monkeypatch.setattr(terminal_module, "POSIX", False)

    with pytest.raises(RuntimeError, match="POSIX terminal"):
        with terminal_module.Terminal(input_fd=0, output=StringIO()):
            pass


def test_terminal_modes_follow_the_declared_capabilities() -> None:
    from zettcode.tui import terminal as terminal_module
    from zettcode.tui.capabilities import TerminalCapabilities

    full = terminal_module.Terminal(input_fd=0, output=StringIO())
    # The default terminal keeps the exact sequence the runner has always sent.
    assert full._enter_sequences() == "\x1b[?1049h\x1b[?7l\x1b[?25l\x1b[?2004h\x1b[?1000h\x1b[?1002h\x1b[?1006h"
    assert full._exit_sequences() == "\x1b[0m\x1b[?25h\x1b[?7h\x1b[?1000l\x1b[?1002l\x1b[?1006l\x1b[?2004l\x1b[?1049l"

    plain = terminal_module.Terminal(
        input_fd=0,
        output=StringIO(),
        capabilities=TerminalCapabilities(mouse=False, bracketed_paste=False),
    )
    assert plain._enter_sequences() == "\x1b[?1049h\x1b[?7l\x1b[?25l"
    assert plain._exit_sequences() == "\x1b[0m\x1b[?25h\x1b[?7h\x1b[?1049l"


def test_input_decoder_handles_fragmented_utf8_keys_mouse_and_paste():
    decoder = InputDecoder()

    assert decoder.feed("你".encode()[:2]) == []
    text_event = decoder.feed("你".encode()[2:])[0]
    key_event = decoder.feed(b"\x1b[5~")[0]
    mouse_event = decoder.feed(b"\x1b[<64;10;8M")[0]
    paste_event = decoder.feed(b"\x1b[200~one\ntwo\x1b[201~")[0]

    assert (text_event.type, text_event.text) == (EventType.TEXT, "你")
    assert key_event.key == "page_up"
    assert (mouse_event.action, mouse_event.x, mouse_event.y) == (MouseAction.SCROLL_UP, 9, 7)
    assert paste_event.text == "one\ntwo"


def test_input_decoder_resolves_standalone_escape_explicitly():
    decoder = InputDecoder()

    assert decoder.feed(b"\x1b") == []
    assert decoder.flush_escape() == InputEvent(EventType.KEY, key="escape")


def test_input_decoder_maps_readline_and_modified_navigation_keys():
    decoder = InputDecoder()

    events = decoder.feed(b"\x01\x05\x0b\x17\x1f\x1b[1;5D\x1b[1;3C\x1b\x7f\x1b[Z")

    assert [event.key for event in events] == [
        "ctrl_a",
        "ctrl_e",
        "ctrl_k",
        "ctrl_w",
        "ctrl_underscore",
        "ctrl_left",
        "alt_right",
        "alt_backspace",
        "backtab",
    ]


def test_differential_renderer_skips_unchanged_rows():
    output = StringIO()
    renderer = DifferentialRenderer(output)
    first = Canvas(8, 2)
    first.draw_text(0, 0, "hello", Style(foreground="#79b88b"))
    renderer.render(first)
    first_frame = output.getvalue()
    output.seek(0)
    output.truncate()

    second = Canvas(8, 2)
    second.draw_text(0, 0, "hello", Style(foreground="#79b88b"))
    second.draw_text(0, 1, "world")
    renderer.render(second)
    diff = output.getvalue()

    assert "\x1b[2J" in first_frame
    assert "\x1b[1;1H" not in diff
    assert "\x1b[2;1H" in diff
    assert "world" in diff


def test_canvas_never_emits_untrusted_terminal_control_characters():
    output = StringIO()
    canvas = Canvas(20, 1)
    canvas.draw_text(0, 0, "safe\x1b[31mred")

    DifferentialRenderer(output).render(canvas)

    rendered = output.getvalue()
    assert "safe\x1b[31mred" not in rendered
    assert "safe\ufffd[31mred" in rendered


def test_canvas_expands_tabs_without_replacement_glyphs():
    output = StringIO()
    direct = Canvas(20, 1)
    direct.draw_text(0, 0, "a\tb")

    DifferentialRenderer(output).render(direct)

    assert "a   b" in output.getvalue()
    assert "\ufffd" not in output.getvalue()
    assert TextLine((Span("\tx"),)).text == "\tx"
