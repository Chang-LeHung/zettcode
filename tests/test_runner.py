"""End-to-end test of the terminal loop, driven through a real pipe."""

import asyncio
import os
from io import StringIO

from zettcode.tui_framework import (
    AnyEvent,
    App,
    ColorDepth,
    Host,
    KeyEvent,
    TerminalCapabilities,
    TextEvent,
    Widget,
)
from zettcode.tui_framework.runner import TerminalRunner, run_app


class StubTerminal:
    """Stand-in for a TTY that reads from a pipe and writes to a buffer."""

    def __init__(self, input_fd: int, *, width: int = 40, height: int = 6) -> None:
        self.input_fd = input_fd
        self.output = StringIO()
        self.capabilities = TerminalCapabilities(color_depth=ColorDepth.ANSI256, width=width, height=height)
        self._size = (width, height)

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def __enter__(self) -> StubTerminal:
        return self

    def __exit__(self, *exception: object) -> None:
        return None

    def write(self, value: str) -> None:
        self.output.write(value)


class Editor(Widget):
    """Widget that echoes typed text and exits on Escape."""

    def __init__(self) -> None:
        super().__init__()
        self.text = ""
        self.exited = False

    @property
    def focusable(self) -> bool:
        return True

    def render(self, canvas) -> None:
        canvas.draw_text(0, 0, f"<{self.text}>", max_width=self.rect.width)

    def handle(self, event: AnyEvent, host: Host) -> bool:
        if isinstance(event, TextEvent):
            self.text += event.text
            return True
        if isinstance(event, KeyEvent) and event.key == "escape":
            self.exited = True
            host.exit()
            return True
        return False


class LatePainter(Widget):
    """Repaints from a background task with no keystroke behind the request."""

    def __init__(self) -> None:
        super().__init__()
        self.text = "start"
        self.worker: asyncio.Task[None] | None = None

    def render(self, canvas) -> None:
        canvas.draw_text(0, 0, self.text, max_width=self.rect.width)

    def handle(self, event: AnyEvent, host: Host) -> bool:
        if isinstance(event, TextEvent) and event.text == " ":
            self.worker = asyncio.create_task(self._later(host))
            return True
        return False

    async def _later(self, host: Host) -> None:
        await asyncio.sleep(0.05)
        self.text = "painted"
        host.invalidate()


async def _wait_for(predicate, *, timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


async def test_runner_decodes_pipe_bytes_and_paints_until_exit():
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    editor = Editor()
    app = App(editor, width=24, height=3)
    task = asyncio.create_task(run_app(app, terminal=terminal))
    try:
        await _wait_for(lambda: app.focused_widget() is not None)
        os.write(write_fd, b"hi")
        await _wait_for(lambda: editor.text == "hi")
        os.write(write_fd, b"\x1b")
        await _wait_for(lambda: editor.exited)
        await asyncio.wait_for(task, 3.0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        os.close(read_fd)
        os.close(write_fd)

    frame = terminal.output.getvalue()
    # The differential renderer writes only changed cells, so the frame holds
    # the incremental edits rather than one contiguous copy of the row.
    assert "\x1b[2J" in frame
    assert "h>" in frame and "i>" in frame
    assert app.running is False
    # ANSI256 was requested, so the renderer must not emit truecolor SGR.
    assert "38;2;" not in frame

    painted = "".join(cell.character for cell in app.render().cells[0] if not cell.continuation)
    assert painted.startswith("<hi>")


async def test_runner_wakes_up_for_a_repaint_requested_while_idle():
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    painter = LatePainter()
    app = App(painter, width=24, height=3)
    task = asyncio.create_task(run_app(app, terminal=terminal))
    try:
        await _wait_for(lambda: "start" in terminal.output.getvalue())
        os.write(write_fd, b" ")
        await _wait_for(lambda: "painted" in terminal.output.getvalue())
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        os.close(read_fd)
        os.close(write_fd)

    assert painter.text == "painted"


async def test_the_runner_class_owns_the_loop_and_releases_it():
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    editor = Editor()
    app = App(editor, width=24, height=3)
    runner = TerminalRunner(app, terminal=terminal)

    assert runner.renderer.color_depth is terminal.capabilities.color_depth
    assert runner.queue is not None

    task = asyncio.create_task(runner.run())
    try:
        await _wait_for(lambda: app.focused_widget() is not None)
        os.write(write_fd, b"ok")
        await _wait_for(lambda: editor.text == "ok")
        os.write(write_fd, b"\x1b")
        await _wait_for(lambda: editor.exited)
        await asyncio.wait_for(task, 3.0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        os.close(read_fd)
        os.close(write_fd)

    assert "ok" in "".join(cell.character for cell in app.render().cells[0] if not cell.continuation)
    assert runner.reader is None
    assert app.scheduler.on_request is None
