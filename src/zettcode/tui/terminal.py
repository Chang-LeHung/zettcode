"""TTY ownership: raw mode, the alternate screen, and size reporting."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from time import monotonic
from types import TracebackType
from typing import TextIO

from .capabilities import TerminalCapabilities, detect_capabilities
from .console import Console, console_for

#: Whether this process is on a POSIX platform, for callers that branch on it.
#: The console itself is chosen by :func:`zettcode.tui.console.console_for`, which
#: owns the Windows path.
POSIX = os.name == "posix"


#: OSC 11 with a question mark asks the terminal for its background colour; it
#: answers on the input side with the same sequence carrying an ``rgb:`` value.
BACKGROUND_QUERY = "\x1b]11;?\x07"
_BACKGROUND_REPLY = re.compile(r"rgb:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})")


def parse_background(reply: str) -> str | None:
    """Return the ``#rrggbb`` colour in an OSC 11 reply, or None for anything else.

    Terminals answer with one to four hex digits per channel — ``rgb:1e/1e/1e``
    xterm-style, or ``rgb:1e1e/1e1e/1e1e`` from iTerm2 — so each channel is
    scaled down to eight bits before it is spelled as a hex colour.
    """
    match = _BACKGROUND_REPLY.search(reply)
    if match is None:
        return None

    def channel(digits: str) -> int:
        value = int(digits, 16)
        maximum = 16 ** len(digits) - 1
        return round(value / maximum * 255)

    return "#" + "".join(f"{channel(digits):02x}" for digits in match.groups())


def title_sequence(text: str) -> str:
    """Return the sequence that names the terminal window, and so its tab.

    OSC 0 sets the textual icon name and window title together, not an image
    icon or the operating system's process name. Tabbed terminals can show
    this as a tab or pane name; VS Code's tab template must use ``${sequence}``
    rather than its default ``${process}`` to include a session title.

    Args:
        text: Title to show. Control characters are dropped, so a title taken
            from a session name cannot smuggle a sequence of its own; an empty
            string clears this title so a shell can set its own again.
    """
    clean = "".join(character for character in text if character.isprintable())
    return f"\x1b]0;{clean}\x07"  # OSC 0 ; text BEL


class Terminal:
    """Own raw mode and restore the user's terminal on every exit path."""

    def __init__(
        self,
        *,
        input_fd: int | None = None,
        output: TextIO | None = None,
        capabilities: TerminalCapabilities | None = None,
        diagnostics: str | Path | None = None,
    ) -> None:
        """Adopt the input and output handles together with the detected capabilities.

        Args:
            input_fd: File descriptor to read keys from; defaults to stdin.
            output: Stream to write ANSI to; defaults to stdout.
            capabilities: What the terminal can render; probed from the
                environment when omitted.
            diagnostics: File that collects anything written to stderr while the
                app owns the screen; ``None`` discards it. A child process
                cannot know that the frame is the interface, so its banner or
                warning would otherwise land in the middle of it.
        """
        self.input_fd = sys.stdin.fileno() if input_fd is None else input_fd
        self.output = sys.stdout if output is None else output
        self.capabilities = capabilities or detect_capabilities()
        self.diagnostics = None if diagnostics is None else Path(diagnostics)
        self.console: Console = console_for(self.input_fd, self.output)
        self._stderr: int | None = None
        self._stderr_sink: int | None = None

    @property
    def size(self) -> tuple[int, int]:
        """Return the current terminal size, clamped to a usable minimum."""
        return self.console.size

    def __enter__(self) -> Terminal:
        """Enter raw mode on the alternate screen, remembering the old settings."""
        self.console.enter()
        self._capture_stderr()
        self.write(self._enter_sequences())
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Restore the screen, the mouse modes, and the saved termios attributes."""
        self._release_stderr()
        self.write(self._exit_sequences())
        self.console.leave()

    def _capture_stderr(self) -> None:
        """Point fd 2 at the diagnostics file for as long as the frame is the interface.

        A stdio MCP server prints its banner on every start, and a C library can
        warn at any moment; neither knows the screen belongs to the renderer,
        which only repaints cells it believes changed. Keeping the descriptor in
        a file means the noise is readable afterwards instead of painted over
        the conversation.
        """
        self._stderr = os.dup(2)
        try:
            if self.diagnostics is None:
                self._stderr_sink = os.open(os.devnull, os.O_WRONLY)
            else:
                self.diagnostics.parent.mkdir(parents=True, exist_ok=True)
                self._stderr_sink = os.open(self.diagnostics, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        except OSError:
            self._stderr_sink = os.open(os.devnull, os.O_WRONLY)
        os.dup2(self._stderr_sink, 2)

    def _release_stderr(self) -> None:
        """Give stderr back to the process, closing whatever held it."""
        if self._stderr is None:
            return
        os.dup2(self._stderr, 2)
        os.close(self._stderr)
        self._stderr = None
        if self._stderr_sink is not None:
            os.close(self._stderr_sink)
            self._stderr_sink = None

    def background(self, *, timeout: float = 0.25) -> str | None:
        """Ask the terminal for its background colour, or None when it stays quiet.

        The reply arrives on the input side, so this reads it here: call it while
        raw mode is on and before any other reader owns the descriptor. A
        terminal that does not implement OSC 11 sends nothing, and the deadline
        is what keeps that from being a wait.

        Args:
            timeout: Seconds to wait for a reply.
        """
        self.write(BACKGROUND_QUERY)
        deadline = monotonic() + timeout
        reply = ""
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0 or not self.console.wait_readable(remaining):
                return parse_background(reply)
            chunk = self.console.read(128)
            if not chunk:
                return parse_background(reply)
            reply += chunk.decode("utf-8", "replace")

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
