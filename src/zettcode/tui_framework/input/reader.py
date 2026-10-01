"""Asynchronous bridge from the TTY file descriptor into decoded events."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable

from ..terminal import Terminal
from .decoder import InputDecoder
from .events import EventType, InputEvent


class AsyncInput:
    """Publish decoded terminal input into one application queue."""

    def __init__(self, terminal: Terminal, publish: Callable[[InputEvent], None]) -> None:
        """Store the terminal, the publish sink, and a fresh decoder.

        Args:
            terminal: Owns the input file descriptor.
            publish: Called synchronously on the event loop for every decoded
                event, including the synthetic resize.
        """
        self.terminal = terminal
        self.publish = publish
        self.decoder = InputDecoder()
        self.loop: asyncio.AbstractEventLoop | None = None
        self._previous_resize_handler = None
        self._escape_handle: asyncio.TimerHandle | None = None

    def start(self) -> None:
        """Attach the reader and the resize handler to the running loop."""
        self.loop = asyncio.get_running_loop()
        self.loop.add_reader(self.terminal.input_fd, self._read_ready)
        if hasattr(signal, "SIGWINCH"):
            self._previous_resize_handler = signal.getsignal(signal.SIGWINCH)
            self.loop.add_signal_handler(signal.SIGWINCH, self._resize)

    def close(self) -> None:
        """Detach every loop hook and restore the previous resize handler."""
        if self.loop is None:
            return
        self.loop.remove_reader(self.terminal.input_fd)
        if hasattr(signal, "SIGWINCH"):
            self.loop.remove_signal_handler(signal.SIGWINCH)
        if self._escape_handle is not None:
            self._escape_handle.cancel()
            self._escape_handle = None
        if hasattr(signal, "SIGWINCH") and callable(self._previous_resize_handler):
            signal.signal(signal.SIGWINCH, self._previous_resize_handler)
        self.loop = None

    def _read_ready(self) -> None:
        """Read one chunk, publish what it decodes, and arm the escape timer."""
        try:
            data = os.read(self.terminal.input_fd, 65536)
        except OSError:
            return
        if self._escape_handle is not None:
            self._escape_handle.cancel()
            self._escape_handle = None
        for event in self.decoder.feed(data):
            self.publish(event)
        if self.decoder.buffer.startswith(b"\x1b") and self.loop is not None:
            self._escape_handle = self.loop.call_later(0.03, self._flush_escape)

    def _resize(self) -> None:
        """Publish the resize the terminal raised through SIGWINCH."""
        self.publish(InputEvent(EventType.RESIZE))

    def _flush_escape(self) -> None:
        """Resolve a lone escape that never grew into a control sequence."""
        self._escape_handle = None
        event = self.decoder.flush_escape()
        if event is not None:
            self.publish(event)
