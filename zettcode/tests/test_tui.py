"""Tests for the terminal, input, and render layers that stayed in the framework."""

import builtins
import importlib
import os
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
from zettcode.tui.input import translate  # noqa: E402 - the bridge the runner uses


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


def test_terminal_requires_an_interactive_descriptor() -> None:
    """A console that is not a terminal cannot be put in raw mode on any platform.

    POSIX says so through the descriptor check; Windows discovers it when the
    console mode cannot be read, which is the same refusal worded for that API.
    """
    from zettcode.tui import terminal as terminal_module

    with pytest.raises(RuntimeError, match="interactive terminal|Windows console"):
        with terminal_module.Terminal(input_fd=0, output=StringIO()):
            pass


def test_terminal_modes_follow_the_declared_capabilities() -> None:
    from zettcode.tui import terminal as terminal_module
    from zettcode.tui.capabilities import TerminalCapabilities

    full = terminal_module.Terminal(input_fd=0, output=StringIO())
    # The default terminal keeps the exact sequence the runner has always sent, plus
    # the keyboard protocol flags that make Shift-Enter reachable, pushed and popped.
    assert full._enter_sequences() == (
        "\x1b[?1004h\x1b[?1049h\x1b[?7l\x1b[?25l\x1b[?2004h\x1b[>1u\x1b[?1000h\x1b[?1002h\x1b[?1006h"
    )
    assert full._exit_sequences() == (
        "\x1b[?1004l\x1b[0m\x1b[?25h\x1b[?7h\x1b[?1000l\x1b[?1002l\x1b[?1006l\x1b[?2004l\x1b[<u\x1b[?1049l"
    )

    plain = terminal_module.Terminal(
        input_fd=0,
        output=StringIO(),
        capabilities=TerminalCapabilities(mouse=False, bracketed_paste=False),
    )
    assert plain._enter_sequences() == "\x1b[?1004h\x1b[?1049h\x1b[?7l\x1b[?25l\x1b[>1u"
    assert plain._exit_sequences() == "\x1b[?1004l\x1b[0m\x1b[?25h\x1b[?7h\x1b[<u\x1b[?1049l"


def test_the_terminal_keeps_stderr_out_of_the_frame(tmp_path) -> None:
    """A child process printing a banner must not paint over the conversation."""
    from zettcode.tui import terminal as terminal_module

    log = tmp_path / "log" / "tui.log"
    terminal = terminal_module.Terminal(input_fd=0, output=StringIO(), diagnostics=log)

    terminal._capture_stderr()
    try:
        os.write(2, b"chrome-devtools-mcp banner\n")
    finally:
        terminal._release_stderr()

    assert log.read_text() == "chrome-devtools-mcp banner\n"


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


def test_input_decoder_normalises_a_paste_into_editable_text():
    """A terminal hands back the clipboard's own line endings and control bytes.

    xterm.js — VS Code's terminal — spells every newline inside a paste as a
    carriage return, so pasted code arrived as one long line with CRs in it.
    """
    decoder = InputDecoder()

    paste_event = decoder.feed(b"\x1b[200~def f():\r\n\treturn 1\r\n\x1b[201~")[0]
    noisy = InputDecoder().feed(b"\x1b[200~a\x07b\x1bc\x1b[201~")[0]

    assert paste_event.text == "def f():\n\treturn 1\n"
    assert noisy.text == "abc"


def test_input_decoder_reports_ctrl_v_to_the_keymap():
    """Ctrl-V is an image binding, and an unmapped control byte never arrives."""
    event = InputDecoder().feed(b"\x16")[0]

    assert event.key == "ctrl_v"


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


def test_the_input_decoder_reads_focus_reports_as_their_own_event():
    """DECSET 1004 reports the window gaining and losing focus; neither may be typed into the draft."""
    from zettcode.tui.input.decoder import InputDecoder
    from zettcode.tui.input.events import EventType

    decoder = InputDecoder()

    gained = decoder.feed(b"\x1b[I")
    lost = decoder.feed(b"\x1b[O")

    assert [(event.type, event.focused) for event in gained] == [(EventType.FOCUS, True)]
    assert [(event.type, event.focused) for event in lost] == [(EventType.FOCUS, False)]


def test_the_input_decoder_reads_a_terminal_reply_without_typing_it():
    """An OSC answer is input, but it is never the reader's keystrokes."""
    from zettcode.tui.input import EventType, InputDecoder, InputEvent

    assert InputDecoder().feed(b"\x1b]11;rgb:1e1e/1e1e/1e1e\x07") == [
        InputEvent(EventType.REPLY, text="11;rgb:1e1e/1e1e/1e1e")
    ]

    # A read may split the answer anywhere, and either terminator ends it.
    split = InputDecoder()
    assert split.feed(b"\x1b]11;rgb:1e") == []
    assert [event.type for event in split.feed(b"1e/1e1e/1e1e\x1b\\")] == [EventType.REPLY]

    # An answer that stops mid-sequence is a terminal that stopped talking; it
    # must not come back as Escape and Alt-] typed into the draft.
    truncated = InputDecoder()
    assert truncated.feed(b"\x1b]11;rgb:") == []
    assert truncated.flush_escape() is None


# -- the modified encoding: keys a terminal can only report after being asked -------


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        # The codes a terminal reports once the keyboard protocol's disambiguation flag
        # is pushed: the keys the legacy encoding cannot tell apart.
        (b"\x1b[13;2u", "shift_enter"),
        (b"\x1b[13;3u", "alt_enter"),
        (b"\x1b[13u", "enter"),
        (b"\x1b[13;5u", "ctrl_enter"),
        (b"\x1b[27;2;13~", "shift_enter"),
        (b"\x1b[27;3;13~", "alt_enter"),
        (b"\x1b[9;2u", "backtab"),
        (b"\x1b[9u", "tab"),
        (b"\x1b[27u", "escape"),
        (b"\x1b[127;3u", "alt_backspace"),
        (b"\x1b[127u", "backspace"),
        (b"\x1b[99;5u", "ctrl_c"),
        (b"\x1b[118;5u", "ctrl_v"),
        (b"\x1b[108;5u", "ctrl_l"),
        (b"\x1b[116;5u", "ctrl_t"),
        (b"\x1b[27;5;99~", "ctrl_c"),
        (b"\x1b[1;5A", "ctrl_up"),
        (b"\x1b[1;2B", "shift_down"),
        (b"\x1b[1;3C", "alt_right"),
        (b"\x1b[1;5D", "ctrl_left"),
        (b"\x1b[1;5H", "ctrl_home"),
        (b"\x1b[1;5F", "ctrl_end"),
        (b"\x1b[3;5~", "ctrl_delete"),
        (b"\x1b[5;2~", "shift_page_up"),
    ],
)
def test_the_modified_encoding_names_a_key_the_way_its_binding_spells_it(sequence, expected):
    """Every key this program binds has to come back under the name its binding uses.

    A terminal that has been asked for the modified encoding stops sending the byte a
    binding was written for — Ctrl-C arrives as ``CSI 99;5u``, not as 0x03 — so a name
    that drifts by one letter is a key that silently stops working.
    """
    assert [event.key for event in InputDecoder().feed(sequence)] == [expected]


@pytest.mark.parametrize(
    ("character", "name"),
    [
        ("a", "ctrl_a"),
        ("c", "ctrl_c"),
        ("d", "ctrl_d"),
        ("e", "ctrl_e"),
        ("g", "ctrl_g"),
        ("k", "ctrl_k"),
        ("l", "ctrl_l"),
        ("n", "ctrl_n"),
        ("p", "ctrl_p"),
        ("r", "ctrl_r"),
        ("t", "ctrl_t"),
        ("u", "ctrl_u"),
        ("v", "ctrl_v"),
        ("w", "ctrl_w"),
        ("y", "ctrl_y"),
        ("z", "ctrl_z"),
        ("_", "ctrl_underscore"),
    ],
)
def test_a_control_key_with_the_encoding_is_named_what_its_byte_used_to_be(character, name):
    """Ctrl-I is Tab and Ctrl-M is Enter in a terminal, and here: the encoding names the
    letter that was pressed, and it has to land on the name the old byte produced."""
    encoded = f"\x1b[{ord(character)};5u".encode()

    assert [event.key for event in InputDecoder().feed(encoded)] == [name]
    assert [event.key for event in InputDecoder().feed(bytes([ord(character.upper()) & 0x1F]))] == [name]


def test_a_sequence_the_program_does_not_model_is_swallowed_rather_than_typed():
    """Its bytes are consumed, so an unmodelled sequence is not typed one character at a time."""
    assert InputDecoder().feed(b"\x1b[1;5q") == []
    assert InputDecoder().feed(b"\x1b[20013;5u") == [], "Ctrl with a character no terminal reports"


def test_an_incomplete_sequence_waits_for_the_rest_of_itself():
    decoder = InputDecoder()

    assert decoder.feed(b"\x1b[13;2") == [], "the final byte is still on its way"
    assert [event.key for event in decoder.feed(b"u")] == ["shift_enter"]


def test_a_sequence_split_across_reads_is_reassembled():
    decoder = InputDecoder()
    assert decoder.feed(b"\x1b[27;5;") == []
    assert [event.key for event in decoder.feed(b"118~")] == ["ctrl_v"]


def test_a_shifted_printable_key_is_still_the_text_it_spells():
    """Uppercase typing has to survive the encoding: a character, not a name."""
    events = InputDecoder().feed(b"\x1b[65;2u")

    assert [(event.type, event.text) for event in events] == [(EventType.TEXT, "A")]


def test_alt_with_a_printable_key_is_named_rather_than_typed():
    """ESC then a letter is how Alt-<letter> was spelled; the encoding spells it a name."""
    assert [event.key for event in InputDecoder().feed(b"\x1b[120;3u")] == ["alt_x"]


def test_the_decoded_names_are_the_ones_the_editor_waits_for():
    """Decoder and bridge together: Shift-Enter arrives as one name, Enter as another.

    What the editor does with each name is its own test; this is the half that was
    missing, because until the terminal was asked for the encoding the name
    ``shift_enter`` could not be produced at all, and every Shift-Enter was a submit.
    """
    decoder = InputDecoder()

    shifted = [translate(event) for event in decoder.feed(b"\x1b[13;2u")]
    plain = [translate(event) for event in decoder.feed(b"\r")]

    assert [getattr(event, "key", None) for event in shifted] == ["shift_enter"]
    assert [getattr(event, "key", None) for event in plain] == ["enter"]


# -- Alt on a cursor key: the spellings terminals actually send ---------------------


@pytest.mark.parametrize(
    ("sequence", "expected"),
    [
        (b"\x1b[1;3A", "alt_up"),  # xterm and every terminal that reports modifiers
        (b"\x1b[1;3B", "alt_down"),
        (b"\x1b[1;2A", "shift_up"),
        (b"\x1b[1;2B", "shift_down"),
        # "Option sends Esc+": the key is ESC [ A and Alt is one more ESC in front.
        (b"\x1b\x1b[A", "alt_up"),
        (b"\x1b\x1b[B", "alt_down"),
        (b"\x1b\x1b[D", "alt_left"),
        (b"\x1b\x1b[5~", "alt_page_up"),
        # A terminal that reports event types writes "mods:event"; only the mods count.
        (b"\x1b[1;3:1A", "alt_up"),
        (b"\x1b[1;2:1B", "shift_down"),
    ],
)
def test_alt_and_shift_on_a_cursor_key_arrive_under_one_name_however_they_are_spelled(sequence, expected):
    """The shell binds ``alt_up`` once; every terminal's spelling has to land on it."""
    assert [event.key for event in InputDecoder().feed(sequence)] == [expected]


def test_alt_up_is_never_read_as_escape_followed_by_up():
    """Escape stops a running request, so a mis-read Alt-Up would cancel the work it was pressed over."""
    keys = [event.key for event in InputDecoder().feed(b"\x1b\x1b[A")]

    assert "escape" not in keys


def test_two_escape_presses_wait_for_what_follows_and_are_still_two_presses():
    """``ESC ESC`` may be the start of Alt on a cursor key, so it waits; if nothing follows it is
    still two Escape presses, each its own event, not one."""
    decoder = InputDecoder()

    assert decoder.feed(b"\x1b\x1b") == [], "undecided until the next byte, or the timeout"
    flushed = [decoder.flush_escape(), decoder.flush_escape(), decoder.flush_escape()]
    assert [event.key if event else None for event in flushed] == ["escape", "escape", None]


def test_escape_then_a_letter_still_reads_as_it_did():
    assert [event.key for event in InputDecoder().feed(b"\x1b\x1bx")] == ["escape", "x"]


def test_a_meta_sequence_split_across_reads_waits_for_its_final_byte():
    decoder = InputDecoder()

    assert decoder.feed(b"\x1b\x1b[") == []
    assert [event.key for event in decoder.feed(b"A")] == ["alt_up"]
