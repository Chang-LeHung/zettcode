"""Where a copy goes: the system clipboard on the reader's machine, the terminal's over ssh."""

from __future__ import annotations

import base64

import pyperclip
import pytest

from zettcode.tui.clipboard import CLIPBOARD_ENV, SSH_VARIABLES, copy_route, is_remote, osc52
from zettcode.tui.runner import clipboard_writer


class FakeTerminal:
    """Records what the program printed, which is how an OSC 52 sequence travels."""

    def __init__(self) -> None:
        self.written: list[str] = []

    def write(self, text: str) -> None:
        self.written.append(text)


def _payload(sequence: str) -> str:
    """Return the text an OSC 52 sequence asks the terminal to copy."""
    encoded = sequence.split(";c;", 1)[1].split("\x07", 1)[0]
    return base64.b64decode(encoded).decode()


@pytest.mark.parametrize("name", SSH_VARIABLES)
def test_any_variable_the_ssh_server_sets_means_the_program_is_remote(name):
    assert is_remote({name: "10.0.0.2 51234 10.0.0.9 22"}) is True


def test_an_empty_variable_is_not_a_connection():
    """A shell that exported the name with nothing in it has not been through ssh."""
    assert is_remote({name: "" for name in SSH_VARIABLES}) is False
    assert is_remote({}) is False


def test_the_route_is_the_terminals_over_ssh_and_the_systems_otherwise():
    assert copy_route({}) == "system"
    assert copy_route({"SSH_CONNECTION": "a b c d"}) == "terminal"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({CLIPBOARD_ENV: "system", "SSH_TTY": "/dev/pts/1"}, "system"),
        ({CLIPBOARD_ENV: "terminal"}, "terminal"),
        ({CLIPBOARD_ENV: " Terminal "}, "terminal"),
        ({CLIPBOARD_ENV: "SYSTEM", "SSH_TTY": "/dev/pts/1"}, "system"),
        # Not a route: the detection stays in charge rather than a typo disabling copy.
        ({CLIPBOARD_ENV: "auto", "SSH_TTY": "/dev/pts/1"}, "terminal"),
        ({CLIPBOARD_ENV: "auto"}, "system"),
        ({CLIPBOARD_ENV: "sytem", "SSH_TTY": "/dev/pts/1"}, "terminal"),
        ({CLIPBOARD_ENV: ""}, "system"),
    ],
)
def test_the_reader_can_override_the_route_and_a_typo_is_ignored(environ, expected):
    assert copy_route(environ) == expected


def test_the_route_reads_the_real_environment_when_none_is_given(monkeypatch):
    assert copy_route() == "system"

    monkeypatch.setenv("SSH_CONNECTION", "a b c d")
    assert copy_route() == "terminal"
    assert is_remote() is True


def test_osc52_is_the_escape_sequence_xterm_defined_with_the_text_in_base64():
    assert osc52("hello", {}) == "\x1b]52;c;aGVsbG8=\x07"


def test_osc52_carries_any_text_as_utf8():
    sequence = osc52("你好 \U0001f642\nsecond line", {})

    assert _payload(sequence) == "你好 \U0001f642\nsecond line"
    assert sequence.isascii(), "base64 keeps the sequence plain ASCII, whatever the text is"


def test_inside_tmux_the_sequence_is_also_sent_through_tmuxs_passthrough():
    """tmux honours the bare one with `set-clipboard on` and forwards the wrapped one with
    `allow-passthrough on`; the program cannot see which, and both carry the same text."""
    bare = "\x1b]52;c;aGVsbG8=\x07"

    sequence = osc52("hello", {"TMUX": "/tmp/tmux-501/default,1234,0"})

    assert sequence.startswith(bare)
    wrapped = sequence[len(bare) :]
    assert wrapped == "\x1bPtmux;\x1b\x1b]52;c;aGVsbG8=\x07\x1b\\"
    assert wrapped.count("\x1b\x1b") == 1, "every escape inside a passthrough is doubled"
    assert wrapped.endswith("\x1b\\"), "and the one that ends it is not"


def test_outside_tmux_the_sequence_is_not_wrapped():
    assert "tmux" not in osc52("hello", {})


def test_over_ssh_the_copy_goes_to_the_terminal_and_never_to_the_servers_clipboard():
    """The bug: a clipboard tool on the server succeeds, so the OSC 52 fallback never ran and
    the text landed on a machine the reader was not sitting at."""
    terminal = FakeTerminal()
    copied: list[str] = []
    write = clipboard_writer(terminal, environ={"SSH_CONNECTION": "a b c d"}, system=copied.append)

    write("select me")

    assert copied == [], "the server's clipboard is not touched"
    assert [_payload(sequence) for sequence in terminal.written] == ["select me"]


def test_on_the_readers_own_machine_the_system_clipboard_is_used_and_the_terminal_is_not_asked():
    terminal = FakeTerminal()
    copied: list[str] = []
    write = clipboard_writer(terminal, environ={}, system=copied.append)

    write("select me")

    assert copied == ["select me"]
    assert terminal.written == [], "no permission prompt from a terminal that asks before writing"


def test_a_machine_with_no_clipboard_tool_falls_back_to_the_terminal():
    terminal = FakeTerminal()

    def missing(text: str) -> None:
        raise pyperclip.PyperclipException("no copy/paste mechanism")

    write = clipboard_writer(terminal, environ={}, system=missing)

    write("select me")

    assert [_payload(sequence) for sequence in terminal.written] == ["select me"]


def test_the_override_sends_a_remote_copy_to_the_system_clipboard_when_the_reader_says_so():
    """An X display forwarded over ssh makes the server's clipboard the right one."""
    terminal = FakeTerminal()
    copied: list[str] = []
    environ = {"SSH_CONNECTION": "a b c d", CLIPBOARD_ENV: "system"}
    write = clipboard_writer(terminal, environ=environ, system=copied.append)

    write("select me")

    assert copied == ["select me"] and terminal.written == []


def test_the_route_is_read_on_every_copy_not_once():
    terminal = FakeTerminal()
    copied: list[str] = []
    environ: dict[str, str] = {}
    write = clipboard_writer(terminal, environ=environ, system=copied.append)

    write("local")
    environ["SSH_CONNECTION"] = "a b c d"
    write("remote")

    assert copied == ["local"]
    assert [_payload(sequence) for sequence in terminal.written] == ["remote"]


def test_inside_tmux_over_ssh_both_sequences_are_written():
    terminal = FakeTerminal()
    write = clipboard_writer(terminal, environ={"SSH_TTY": "/dev/pts/2", "TMUX": "x,1,0"}, system=lambda text: None)

    write("select me")

    assert len(terminal.written) == 1 and "\x1bPtmux;" in terminal.written[0]
    assert terminal.written[0].startswith("\x1b]52;c;")


def test_a_clipboard_tool_that_cannot_be_run_falls_back_to_the_terminal():
    """``pyperclip`` shells out on Linux and can raise ``FileNotFoundError`` rather than its own
    error; a copy must not take the session down, and the terminal is a way out."""
    terminal = FakeTerminal()

    def cannot_run(text: str) -> None:
        raise FileNotFoundError(2, "No such file or directory", "xclip")

    write = clipboard_writer(terminal, environ={}, system=cannot_run)

    write("select me")  # does not raise

    assert [_payload(sequence) for sequence in terminal.written] == ["select me"]
