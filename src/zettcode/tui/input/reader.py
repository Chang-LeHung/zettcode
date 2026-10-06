"""Asynchronous bridge from the TTY file descriptor into decoded events."""

from __future__ import annotations

import asyncio
import signal
import threading
from collections.abc import Callable
from typing import Any

from ..terminal import Terminal
from .decoder import InputDecoder
from .events import EventType, InputEvent

#: How often a platform without a resize signal asks the console for its size.
RESIZE_POLL_SECONDS = 0.25

#: How long the reader thread waits for input before checking whether to stop.
POLL_SECONDS = 0.1


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
        self._previous_resize_handler: Any = None
        self._escape_handle: asyncio.TimerHandle | None = None
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._resize_handle: asyncio.TimerHandle | None = None
        self._size: tuple[int, int] | None = None

    def start(self) -> None:
        """Attach the reader and the resize handler to the running loop."""
        self.loop = asyncio.get_running_loop()
        if self.terminal.console.watches_descriptor:
            self.loop.add_reader(self.terminal.input_fd, self._read_ready)
            if hasattr(signal, "SIGWINCH"):
                self._previous_resize_handler = signal.getsignal(signal.SIGWINCH)
                self.loop.add_signal_handler(signal.SIGWINCH, self._resize)
            return
        # A Windows console handle is not something the loop can watch, so a
        # thread does the blocking read and hands chunks back to the loop; with
        # no SIGWINCH either, the size is polled on the same loop.
        self._stopping.clear()
        self._thread = threading.Thread(target=self._pump, name="zettcode-input", daemon=True)
        self._thread.start()
        self._size = self.terminal.size
        self._resize_handle = self.loop.call_later(RESIZE_POLL_SECONDS, self._poll_resize)

    def close(self) -> None:
        """Detach every loop hook and restore the previous resize handler."""
        if self.loop is None:
            return
        if self.terminal.console.watches_descriptor:
            self.loop.remove_reader(self.terminal.input_fd)
        if self._thread is not None:
            self._stopping.set()
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._resize_handle is not None:
            self._resize_handle.cancel()
            self._resize_handle = None
        if hasattr(signal, "SIGWINCH") and self.terminal.console.watches_descriptor:
            self.loop.remove_signal_handler(signal.SIGWINCH)
        if self._escape_handle is not None:
            self._escape_handle.cancel()
            self._escape_handle = None
        if (
            self.terminal.console.watches_descriptor
            and hasattr(signal, "SIGWINCH")
            and callable(self._previous_resize_handler)
        ):
            signal.signal(signal.SIGWINCH, self._previous_resize_handler)
        self.loop = None

    def _read_ready(self) -> None:
        """Read one chunk on the loop thread, when the loop watches the descriptor."""
        try:
            data = self.terminal.console.read()
        except OSError:
            return
        self._feed(data)

    def _feed(self, data: bytes) -> None:
        """Publish whatever one chunk decodes, and arm the escape timer."""
        if self._escape_handle is not None:
            self._escape_handle.cancel()
            self._escape_handle = None
        for event in self.decoder.feed(data):
            self.publish(event)
        # A trailing ESC may still be growing into a control sequence, so give
        # it a moment (30 ms, the usual terminal timeout) before reporting the
        # Escape key itself.
        if self.decoder.buffer.startswith(b"\x1b") and self.loop is not None:
            self._escape_handle = self.loop.call_later(0.03, self._flush_escape)

    def _pump(self) -> None:
        """Read the console from a thread and hand each chunk to the loop."""
        while not self._stopping.is_set():
            try:
                if not self.terminal.console.wait_readable(POLL_SECONDS):
                    continue
                data = self.terminal.console.read()
            except OSError:
                return
            if not data:
                continue
            loop = self.loop
            if loop is not None:
                loop.call_soon_threadsafe(self._feed, data)

    def _poll_resize(self) -> None:
        """Publish a resize when the console's size changed.

        Windows raises no SIGWINCH, so the loop asks instead of being told; the
        probe is one console call, cheap enough for the frame interval.
        """
        self._resize_handle = None
        size = self.terminal.size
        if self._size is not None and size != self._size:
            self._size = size
            self.publish(InputEvent(EventType.RESIZE))
        if self.loop is not None:
            self._resize_handle = self.loop.call_later(RESIZE_POLL_SECONDS, self._poll_resize)

    def _resize(self) -> None:
        """Publish the resize the terminal raised through SIGWINCH."""
        self.publish(InputEvent(EventType.RESIZE))

    def _flush_escape(self) -> None:
        """Resolve a lone escape that never grew into a control sequence."""
        self._escape_handle = None
        event = self.decoder.flush_escape()
        if event is not None:
            self.publish(event)
