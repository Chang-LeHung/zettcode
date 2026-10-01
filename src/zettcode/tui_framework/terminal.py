"""TTY ownership: raw mode, the alternate screen, and size reporting."""

from __future__ import annotations

import os
import shutil
import sys
from types import TracebackType
from typing import TextIO

from .capabilities import TerminalCapabilities, detect_capabilities

# Raw-mode input, SIGWINCH, and add_reader on stdin are POSIX-only. Keep the
# import safe on Windows so the rest of ZettCode still loads, and fail with a
# clear message when a TUI is actually requested there.
POSIX = os.name == "posix"


class Terminal:
    """Own raw mode and restore the user's terminal on every exit path."""

    def __init__(
        self,
        *,
        input_fd: int | None = None,
        output: TextIO | None = None,
        capabilities: TerminalCapabilities | None = None,
    ) -> None:
        """Adopt the input and output handles together with the detected capabilities.

        Args:
            input_fd: File descriptor to read keys from; defaults to stdin.
            output: Stream to write ANSI to; defaults to stdout.
            capabilities: What the terminal can render; probed from the
                environment when omitted.
        """
        self.input_fd = sys.stdin.fileno() if input_fd is None else input_fd
        self.output = sys.stdout if output is None else output
        self.capabilities = capabilities or detect_capabilities()
        self._attributes: list | None = None

    @property
    def size(self) -> tuple[int, int]:
        """Return the current terminal size, clamped to a usable minimum."""
        size = shutil.get_terminal_size((80, 24))
        return max(20, size.columns), max(8, size.lines)

    def __enter__(self) -> Terminal:
        """Enter raw mode on the alternate screen, remembering the old settings."""
        if not POSIX:
            raise RuntimeError("ZettCode TUI requires a POSIX terminal")
        import termios
        import tty

        if not os.isatty(self.input_fd) or not self.output.isatty():
            raise RuntimeError("ZettCode TUI requires an interactive terminal")
        self._attributes = termios.tcgetattr(self.input_fd)
        tty.setraw(self.input_fd)
        self.write(self._enter_sequences())
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the screen, the mouse modes, and the saved termios attributes."""
        self.write(self._exit_sequences())
        if self._attributes is not None:
            import termios

            termios.tcsetattr(self.input_fd, termios.TCSADRAIN, self._attributes)
            self._attributes = None

    def write(self, value: str) -> None:
        """Write and flush one control sequence."""
        self.output.write(value)
        self.output.flush()

    def _enter_sequences(self) -> str:
        """Return the modes to enable, honoring the detected capabilities.

        Mouse reporting is only requested when the terminal claims to support
        it, and bracketed paste likewise, so a caller can describe a plainer
        terminal and have the layer speak only what it understands.

        Button-event tracking (1002) is used rather than any-event tracking
        (1003): drags are reported while idle pointer motion is not, so the
        input queue stays quiet and selection still works.
        """
        parts = [
            "\x1b[?1049h",  # DECSET 1049: switch to the alternate screen buffer
            "\x1b[?7l",  # DECRST 7: no auto-wrap, so the last column cannot scroll
            "\x1b[?25l",  # DECTCEM: hide the cursor until a widget positions it
        ]
        if self.capabilities.bracketed_paste:
            # DECSET 2004: wrap pastes in ESC[200~ .. ESC[201~ so a multiline
            # paste arrives as one event instead of a burst of Enter keys.
            parts.append("\x1b[?2004h")
        if self.capabilities.mouse:
            parts += [
                "\x1b[?1000h",  # DECSET 1000: report button presses and releases
                "\x1b[?1002h",  # DECSET 1002: also report drags, not idle motion
                "\x1b[?1006h",  # DECSET 1006: SGR coordinates, so wide terminals work
            ]
        return "".join(parts)

    def _exit_sequences(self) -> str:
        """Return the modes to restore, mirroring whatever was enabled."""
        parts = [
            "\x1b[0m",  # SGR 0: drop every attribute before the shell gets the tty
            "\x1b[?25h",  # DECTCEM: show the cursor again
            "\x1b[?7h",  # DECSET 7: restore auto-wrap
        ]
        if self.capabilities.mouse:
            parts += ["\x1b[?1000l", "\x1b[?1002l", "\x1b[?1006l"]  # stop mouse reports
        if self.capabilities.bracketed_paste:
            parts.append("\x1b[?2004l")  # stop wrapping pastes
        parts.append("\x1b[?1049l")  # switch back to the primary screen buffer
        return "".join(parts)
