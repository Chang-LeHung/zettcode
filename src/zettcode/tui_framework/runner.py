"""Own a real terminal and drive an App until it exits.

The loop has one job: paint when a frame is due, and sleep otherwise without
missing a repaint that a background task asked for while it slept. Two sources
wake it — terminal input and the scheduler's wake-up callback — plus a timeout
that bounds animation.

Lifecycle and steady state:

    streaming task      App / Scheduler       TerminalRunner        AsyncInput       TTY
         |                    |                     |                   |             |
    -----+--------------------+---------------------+-------------------+-------------+----- startup
         |                    |      with terminal: raw mode, alternate screen,
         |                    |      bracketed paste, button-event mouse tracking
         |                    |<-- resize(size) ----|------------------>|             |
         |                    |<-- set_copy_handler-|                   |             |
         |                    |<-- mount() ---------|  attach + focus first Tab stop  |
         |                    |<-- on_request = wakeup.set              |             |
         |                    |                     |-- start() ------->| add_reader  |
         |                    |                     |                   | (SIGWINCH)  |
    -----+--------------------+---------------------+-------------------+-------------+----- frame
         |                    |<-- poll(now) -------|                   |             |
         |                    |--- due ------------>|                   |             |
         |                    |<-- tick(), render() |                   |             |
         |                    |--- Canvas --------->|-- ANSI diff ------------------->|
         |                    |<-- delay() ---------|  (None when idle) |             |
         |                    |                     |                   |             |
    -----+--------------------+---------------------+-------------------+-------------+----- idle
         |                    |                     |== await wait {input, wakeup}, timeout
         |                    |                     |                   |             |
    key press ----------------|---------------------|<-- InputEvent ----|             |
         |                    |<-- dispatch(event) -|  (translated)     |             |
         |                    |                     |                   |             |
    append + invalidate ----->|-- request_repaint()>|                   |             |
         |                    |--- wakeup.set() --->|  wait returns     |             |
         |                    |<-- poll(now) -------|  back to frame    |             |
         |                    |                     |                   |             |
    -----+--------------------+---------------------+-------------------+-------------+----- shutdown
         |                    |<-- close() ---------|  cancel input task, clear on_request,
         |                    |                     |  reader.close(), app.close(),
         |                    |                     |  terminal restored

Without the wake-up callback the loop would park on an empty input queue with an
infinite timeout and stay there until the user pressed a key, so a streamed
answer would never appear. ``App.invalidate`` is therefore wired to the same
event the loop is already waiting on.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Callable

import pyperclip

from .core.app import App
from .core.events import ResizeEvent
from .input import AsyncInput, InputEvent, translate
from .render import DifferentialRenderer
from .terminal import Terminal


class TerminalRunner:
    """Drive one App from a real terminal, owning every resource it needs."""

    def __init__(self, app: App, *, terminal: Terminal | None = None) -> None:
        """Bind the app to a terminal renderer, an input queue, and a wake-up event.

        Args:
            app: The tree to drive; it is mounted inside ``run``.
            terminal: Terminal to own; a default one wraps stdin and stdout.
        """
        self.app = app
        self.terminal = terminal or Terminal()
        self.renderer = DifferentialRenderer(
            self.terminal.output,
            color_depth=self.terminal.capabilities.color_depth,
        )
        self.queue: asyncio.Queue[InputEvent] = asyncio.Queue()
        self.wakeup = asyncio.Event()
        self.reader: AsyncInput | None = None
        self._input: asyncio.Task[InputEvent] | None = None

    async def run(self) -> None:
        """Enter raw mode and loop until the application exits."""
        app = self.app
        with self.terminal:
            app.resize(*self.terminal.size)
            app.set_copy_handler(clipboard_writer(self.terminal))
            self.reader = AsyncInput(self.terminal, self.queue.put_nowait)
            self.reader.start()
            app.mount()
            app.scheduler.on_request = self.wakeup.set
            # One long-lived reader task: cancelling a pending queue.get() can
            # drop an item, so the loop keeps the same task and replaces it only
            # after it delivers.
            self._input = asyncio.ensure_future(self.queue.get())
            try:
                while app.running:
                    if app.scheduler.poll(now=app.clock()):
                        self.paint()
                    if not app.running:
                        break
                    await self.wait_for_work()
                    if self._input.done():
                        raw = self._input.result()
                        self._input = asyncio.ensure_future(self.queue.get())
                        self.deliver(raw)
            finally:
                await self._shutdown()

    def paint(self) -> None:
        """Draw one frame into the terminal."""
        if self.app.refreshed:
            self.app.refreshed = False
            self.renderer.reset()
        self.app.tick()
        canvas = self.app.render()
        cursor = self.app.cursor()
        self.renderer.render(canvas, cursor=None if cursor is None else (cursor.x, cursor.y))

    def deliver(self, raw: InputEvent) -> None:
        """Translate one decoded terminal event and hand it to the app."""
        event = translate(raw)
        if isinstance(event, ResizeEvent):
            width, height = self.terminal.size
            self.renderer.reset()
            self.app.dispatch(ResizeEvent(width=width, height=height))
            return
        if event is not None:
            self.app.dispatch(event)

    async def wait_for_work(self) -> None:
        """Sleep until input arrives, a repaint is requested, or a frame is due."""
        waker = asyncio.ensure_future(self.wakeup.wait())
        self.wakeup.clear()
        try:
            await asyncio.wait(
                {self._input, waker},
                timeout=self.app.scheduler.delay(now=self.app.clock()),
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            waker.cancel()
            await asyncio.gather(waker, return_exceptions=True)

    async def _shutdown(self) -> None:
        """Cancel the reader task and release the terminal and the widget tree."""
        if self._input is not None:
            self._input.cancel()
            await asyncio.gather(self._input, return_exceptions=True)
            self._input = None
        self.app.scheduler.on_request = None
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        self.app.close()


async def run_app(app: App, *, terminal: Terminal | None = None) -> None:
    """Convenience wrapper for the common case of running one app once.

    Args:
        app: The tree to drive.
        terminal: Terminal to own; a default one is built when omitted.
    """
    await TerminalRunner(app, terminal=terminal).run()


def clipboard_writer(terminal: Terminal) -> Callable[[str], None]:
    """Copy through the OS clipboard, falling back to the OSC 52 escape."""

    def write(text: str) -> None:
        """Handle one copy request from the app."""
        try:
            pyperclip.copy(text)
        except pyperclip.PyperclipException:
            encoded = base64.b64encode(text.encode()).decode()
            terminal.write(f"\x1b]52;c;{encoded}\x07")

    return write
