"""The platform console seam, and the Windows console behind it."""

from __future__ import annotations

from io import StringIO

import pytest

from zettcode.tui.console import WindowsConsole
from zettcode.tui.input import AsyncInput
from zettcode.tui.input.events import EventType
from zettcode.tui.terminal import title_sequence


def test_terminal_title_preserves_the_marker_and_session_without_control_injection():
    assert title_sequence("◈ zettcode · 修复解析器") == "\x1b]0;◈ zettcode · 修复解析器\x07"
    assert title_sequence("\x1b\x07\n\r\t\x00Session") == "\x1b]0;Session\x07"
    assert title_sequence("") == "\x1b]0;\x07"


class _FakeKernel32:
    """Stand in for ``kernel32`` so the Windows path runs on any platform."""

    def __init__(
        self,
        *,
        input_mode: int = 0x0007,
        output_mode: int = 0x0003,
        readable: bool = True,
        window: tuple[int, int, int, int] = (0, 0, 79, 23),
    ) -> None:
        self.input_mode = input_mode
        self.output_mode = output_mode
        self.readable = readable
        self.window = window
        self.input_modes: list[int] = []
        self.output_modes: list[int] = []

    def GetStdHandle(self, which: int) -> int:
        return which

    def GetConsoleMode(self, handle: int, pointer) -> int:
        if not self.readable:
            return 0
        pointer._obj.value = self.input_mode if handle == WindowsConsole.STD_INPUT_HANDLE else self.output_mode
        return 1

    def SetConsoleMode(self, handle: int, mode: int) -> int:
        if handle == WindowsConsole.STD_INPUT_HANDLE:
            self.input_modes.append(mode)
        else:
            self.output_modes.append(mode)
        return 1

    def WaitForSingleObject(self, handle: int, milliseconds: int) -> int:
        return WindowsConsole.WAIT_OBJECT_0 if milliseconds >= 0 else 1

    def GetConsoleScreenBufferInfo(self, handle: int, pointer) -> int:
        left, top, right, bottom = self.window
        window = pointer._obj.srWindow
        window.Left, window.Top, window.Right, window.Bottom = left, top, right, bottom
        return 1


def _console(monkeypatch, fake: _FakeKernel32) -> WindowsConsole:
    """Return a console whose Win32 calls are ``fake``."""
    monkeypatch.setattr(WindowsConsole, "_kernel32", staticmethod(lambda: fake))
    return WindowsConsole(0, StringIO())


def test_the_windows_console_switches_virtual_terminal_mode_on_and_restores_it(monkeypatch):
    """ANS is what lets the rest of the layer stay platform-free."""
    fake = _FakeKernel32()
    console = _console(monkeypatch, fake)

    console.enter()

    (raw,) = fake.input_modes
    assert raw & WindowsConsole.ENABLE_VIRTUAL_TERMINAL_INPUT
    assert raw & WindowsConsole.ENABLE_MOUSE_INPUT
    assert not raw & WindowsConsole.ENABLE_LINE_INPUT
    assert not raw & WindowsConsole.ENABLE_ECHO_INPUT
    assert not raw & WindowsConsole.ENABLE_PROCESSED_INPUT
    (out,) = fake.output_modes
    assert out & WindowsConsole.ENABLE_VIRTUAL_TERMINAL_PROCESSING

    console.leave()

    assert fake.input_modes[-1] == fake.input_mode
    assert fake.output_modes[-1] == fake.output_mode


def test_the_windows_console_refuses_a_handle_it_cannot_put_in_raw_mode(monkeypatch):
    fake = _FakeKernel32(readable=False)
    console = _console(monkeypatch, fake)

    with pytest.raises(RuntimeError, match="Windows console"):
        console.enter()


def test_the_windows_console_reports_the_visible_window(monkeypatch):
    fake = _FakeKernel32(window=(5, 2, 124, 31))
    console = _console(monkeypatch, fake)

    assert console.size == (120, 30)


class _FakeTerminal:
    """A terminal whose size walks a script, for the resize poll."""

    def __init__(self, sizes: list[tuple[int, int]]) -> None:
        self.sizes = sizes
        self.console = self
        self.input_fd = 0

    @property
    def watches_descriptor(self) -> bool:
        return False

    @property
    def size(self) -> tuple[int, int]:
        return self.sizes.pop(0) if self.sizes else (80, 24)


def test_a_platform_without_a_resize_signal_publishes_one_event_per_change():
    """Windows raises no SIGWINCH, so the reader asks; a quiet size must stay quiet."""
    published: list[object] = []
    terminal = _FakeTerminal([(80, 24), (100, 30)])
    reader = AsyncInput(terminal, published.append)
    reader._size = (80, 24)

    reader._poll_resize()
    assert published == []

    reader._poll_resize()
    assert [event.type for event in published] == [EventType.RESIZE]
