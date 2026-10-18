"""The platform's console: raw mode, byte input, and size.

Modern Windows consoles speak the same ANSI/VT protocol POSIX terminals do once
virtual-terminal mode is on, so the decoder, the renderer, and the widget layer
need no Windows branch at all. What differs is only how raw mode is entered, how
a read waits with a deadline, and how the size is asked for — which is what this
module isolates behind :class:`Console`.
"""

from __future__ import annotations

import os
import select
import shutil
from abc import ABC, abstractmethod
from typing import Any, TextIO

#: Smallest size a terminal may report, so a broken probe cannot shrink the app.
MIN_COLUMNS = 20
MIN_ROWS = 8


class Console(ABC):
    """Raw-mode ownership and byte input for one platform."""

    def __init__(self, input_fd: int, output: TextIO) -> None:
        """Bind the console to the file descriptor it reads and the stream it writes."""
        self.input_fd = input_fd
        self.output = output

    @abstractmethod
    def enter(self) -> None:
        """Put the terminal in raw mode, remembering what to restore."""

    @abstractmethod
    def leave(self) -> None:
        """Restore what :meth:`enter` changed, if anything."""

    @abstractmethod
    def wait_readable(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for input, and report whether any arrived."""

    @property
    def watches_descriptor(self) -> bool:
        """Whether the event loop itself can watch the descriptor.

        POSIX loops can (``add_reader``); a Windows console handle is not a
        socket the proactor loop can watch, so a thread does the blocking read
        there instead.
        """
        return os.name == "posix"

    def read(self, size: int = 65536) -> bytes:
        """Return one chunk of input bytes, blocking until some are ready."""
        return os.read(self.input_fd, size)

    @property
    def size(self) -> tuple[int, int]:
        """Return the current size, clamped to something usable."""
        found = shutil.get_terminal_size((80, 24))
        return max(MIN_COLUMNS, found.columns), max(MIN_ROWS, found.lines)


class PosixConsole(Console):
    """Raw mode through ``termios``, input through a descriptor the loop can watch."""

    def __init__(self, input_fd: int, output: TextIO) -> None:
        """Remember the descriptor and start with no saved attributes."""
        super().__init__(input_fd, output)
        self._attributes: list[Any] | None = None

    def enter(self) -> None:
        """Take the descriptor out of cooked mode and into raw mode."""
        import termios
        import tty

        if not os.isatty(self.input_fd) or not self.output.isatty():
            raise RuntimeError("ZettCode TUI requires an interactive terminal")
        self._attributes = termios.tcgetattr(self.input_fd)
        tty.setraw(self.input_fd)

    def leave(self) -> None:
        """Restore the attributes the terminal had before."""
        if self._attributes is None:
            return
        import termios

        termios.tcsetattr(self.input_fd, termios.TCSADRAIN, self._attributes)
        self._attributes = None

    def wait_readable(self, timeout: float) -> bool:
        """Wait on the descriptor with ``select``."""
        return bool(select.select([self.input_fd], [], [], timeout)[0])


class WindowsConsole(Console):
    """Raw mode through the Win32 console, with VT input and output switched on.

    A Windows console starts in cooked, non-ANSI mode. Clearing
    ``ENABLE_LINE_INPUT`` and ``ENABLE_ECHO_INPUT`` makes a key arrive as soon as
    it is pressed, and ``ENABLE_VIRTUAL_TERMINAL_INPUT`` turns the console's
    input into the same escape sequences a POSIX terminal sends, so the decoder
    needs no special case. ``ENABLE_VIRTUAL_TERMINAL_PROCESSING`` does the same
    for output, which is what lets the renderer write ANSI to it.

    Every handle is opened through ``ctypes`` on first use, so importing this
    module stays possible on a machine without a console (a service, a test).
    """

    #: Console mode bits, from ``wincon.h``.
    ENABLE_PROCESSED_INPUT = 0x0001
    ENABLE_LINE_INPUT = 0x0002
    ENABLE_ECHO_INPUT = 0x0004
    ENABLE_WINDOW_INPUT = 0x0008
    ENABLE_MOUSE_INPUT = 0x0010
    ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200
    ENABLE_PROCESSED_OUTPUT = 0x0001
    ENABLE_WRAP_AT_EOL_OUTPUT = 0x0002
    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004

    STD_INPUT_HANDLE = -10
    STD_OUTPUT_HANDLE = -11
    WAIT_OBJECT_0 = 0x00000000

    def __init__(self, input_fd: int, output: TextIO) -> None:
        """Remember the descriptor and start with nothing saved."""
        super().__init__(input_fd, output)
        self._input_mode: int | None = None
        self._output_mode: int | None = None

    # -- the Win32 calls, in one place so a test can stand in for them --------

    @staticmethod
    def _kernel32():
        """Return ``kernel32``, importing ctypes only where it exists."""
        import ctypes

        return ctypes.windll.kernel32

    def _handle(self, which: int) -> int:
        """Return one standard handle."""
        return self._kernel32().GetStdHandle(which)

    def enter(self) -> None:
        """Clear the cooked input flags and turn on VT for input and output."""
        import ctypes

        kernel32 = self._kernel32()
        stdin = self._handle(self.STD_INPUT_HANDLE)
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(stdin, ctypes.byref(mode)):
            raise RuntimeError("ZettCode TUI requires a Windows console")
        self._input_mode = mode.value
        raw = mode.value & ~self.ENABLE_LINE_INPUT & ~self.ENABLE_ECHO_INPUT & ~self.ENABLE_PROCESSED_INPUT
        raw |= self.ENABLE_VIRTUAL_TERMINAL_INPUT | self.ENABLE_MOUSE_INPUT | self.ENABLE_WINDOW_INPUT
        self._set_input_mode(raw)
        stdout = self._handle(self.STD_OUTPUT_HANDLE)
        out_mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(stdout, ctypes.byref(out_mode)):
            self._output_mode = out_mode.value
            self._set_output_mode(
                out_mode.value
                | self.ENABLE_PROCESSED_OUTPUT
                | self.ENABLE_WRAP_AT_EOL_OUTPUT
                | self.ENABLE_VIRTUAL_TERMINAL_PROCESSING
            )

    def _set_input_mode(self, mode: int) -> None:
        """Apply one input mode, reporting a console that refuses it."""
        if not self._kernel32().SetConsoleMode(self._handle(self.STD_INPUT_HANDLE), mode):
            raise RuntimeError("ZettCode TUI requires a Windows console")

    def _set_output_mode(self, mode: int) -> None:
        """Apply one output mode."""
        self._kernel32().SetConsoleMode(self._handle(self.STD_OUTPUT_HANDLE), mode)

    def leave(self) -> None:
        """Give the console back the modes it had."""
        if self._input_mode is not None:
            self._set_input_mode(self._input_mode)
            self._input_mode = None
        if self._output_mode is not None:
            self._set_output_mode(self._output_mode)
            self._output_mode = None

    def wait_readable(self, timeout: float) -> bool:
        """Wait on the console handle itself, in milliseconds."""
        handle = self._handle(self.STD_INPUT_HANDLE)
        milliseconds = max(0, int(timeout * 1000))
        return self._kernel32().WaitForSingleObject(handle, milliseconds) == self.WAIT_OBJECT_0

    @property
    def size(self) -> tuple[int, int]:
        """Return the visible window size the console reports."""
        import ctypes

        class Coord(ctypes.Structure):
            _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

        class SmallRect(ctypes.Structure):
            _fields_ = [
                ("Left", ctypes.c_short),
                ("Top", ctypes.c_short),
                ("Right", ctypes.c_short),
                ("Bottom", ctypes.c_short),
            ]

        class Info(ctypes.Structure):
            _fields_ = [
                ("dwSize", Coord),
                ("dwCursorPosition", Coord),
                ("wAttributes", ctypes.c_ushort),
                ("srWindow", SmallRect),
                ("dwMaximumWindowSize", Coord),
            ]

        info = Info()
        if not self._kernel32().GetConsoleScreenBufferInfo(self._handle(self.STD_OUTPUT_HANDLE), ctypes.byref(info)):
            return super().size
        columns = info.srWindow.Right - info.srWindow.Left + 1
        rows = info.srWindow.Bottom - info.srWindow.Top + 1
        return max(MIN_COLUMNS, columns), max(MIN_ROWS, rows)


def console_for(input_fd: int, output: TextIO) -> Console:
    """Return the console this platform offers."""
    if os.name == "nt":
        return WindowsConsole(input_fd, output)
    return PosixConsole(input_fd, output)
