"""End-to-end test of the terminal loop, driven through a real pipe."""

from __future__ import annotations

import asyncio
import os
from io import StringIO

import pytest

from zettcode.tui import (
    AnyEvent,
    ColorDepth,
    Host,
    KeyEvent,
    Terminal,
    TerminalCapabilities,
    TextEvent,
    TuiApp,
    Widget,
    title_sequence,
)
from zettcode.tui.runner import TerminalRunner, run_app

#: The loop is driven through a POSIX pipe the event loop can watch with
#: ``add_reader``. Windows has no such reader for a pipe, and its real path — a
#: console handle read from a thread, with the size polled — is covered by
#: ``test_console.py`` instead.
pytestmark = pytest.mark.skipif(os.name != "posix", reason="the runner tests drive a POSIX pipe")


class StubTerminal(Terminal):
    """Stand-in for a TTY that reads from a pipe and writes to a buffer.

    It inherits the real terminal's control sequences, so the parts that talk to
    the terminal — asking for its background, naming its title — are exercised
    as written instead of being faked.
    """

    def __init__(self, input_fd: int, *, width: int = 40, height: int = 6) -> None:
        super().__init__(
            input_fd=input_fd,
            output=StringIO(),
            capabilities=TerminalCapabilities(color_depth=ColorDepth.ANSI256, width=width, height=height),
        )
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
    """Spin until the predicate holds, or fail the test once the wait expires."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() >= deadline:
            raise AssertionError(f"{predicate} did not become true within {timeout}s")
        await asyncio.sleep(0.01)


async def test_runner_decodes_pipe_bytes_and_paints_until_exit():
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    editor = Editor()
    app = TuiApp(editor, width=24, height=3)
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
    app = TuiApp(painter, width=24, height=3)
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


async def test_the_first_frame_lands_before_the_terminal_is_asked_for_its_background():
    """A terminal that never answers the OSC 11 query must not delay the frame.

    Multiplexers and editors commonly do not implement it, so the runner would
    otherwise hold a blank screen for the whole timeout before painting
    anything. The stub's ``__enter__`` writes nothing, so every byte before the
    query is a frame the reader can already see.
    """
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd)
    app = TuiApp(Editor(), width=40, height=6, auto_theme=True)
    runner = TerminalRunner(app, terminal=terminal)
    query = "\x1b]11;?\x07"

    task = asyncio.create_task(runner.run())
    try:
        await _wait_for(lambda: query in terminal.output.getvalue())
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        os.close(read_fd)
        os.close(write_fd)

    output = terminal.output.getvalue()
    assert output[: output.index(query)].strip(), "the interface was not painted before the query"


async def test_the_runner_class_owns_the_loop_and_releases_it():
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    editor = Editor()
    app = TuiApp(editor, width=24, height=3)
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


def test_the_runner_names_the_terminal_after_the_app_and_hands_it_back():
    """A tab or window title follows the app, and is released on shutdown."""
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd)
    app = TuiApp(Editor(), width=40, height=6, title="zettcode · first")
    runner = TerminalRunner(app, terminal=terminal)

    try:
        runner.paint()
        assert terminal.output.getvalue().startswith(title_sequence("zettcode · first"))

        # An unchanged title is not written again on the next frame.
        terminal.output.seek(0)
        terminal.output.truncate(0)
        runner.paint()
        assert title_sequence("zettcode · first") not in terminal.output.getvalue()

        app.title = lambda: "Fix the parser crash"
        runner.paint()

        assert title_sequence("Fix the parser crash") in terminal.output.getvalue()
    finally:
        os.close(read_fd)
        os.close(write_fd)


async def test_shutdown_hands_the_terminal_title_back():
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd)
    app = TuiApp(Editor(), width=40, height=6, title="zettcode · first")
    runner = TerminalRunner(app, terminal=terminal)

    try:
        runner.paint()
        await runner._shutdown()

        assert terminal.output.getvalue().endswith(title_sequence(""))
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_the_runner_adopts_the_scheme_the_terminal_reports():
    """A terminal's answer arrives as input and picks the palette."""
    from zettcode.tui import LIGHT
    from zettcode.tui.input import EventType, InputDecoder

    replies = (
        (b"\x1b]11;rgb:ffff/ffff/ffff\x07", LIGHT),
        (b"\x1b]11;rgb:0000/0000/0000\x1b\\", LIGHT),
    )
    for reply, _ in replies:
        read_fd = os.open(os.devnull, os.O_RDONLY)
        terminal = StubTerminal(read_fd)
        app = TuiApp(Editor(), width=40, height=6, auto_theme=True)
        runner = TerminalRunner(app, terminal=terminal)
        try:
            events = InputDecoder().feed(reply)
            assert [event.type for event in events] == [EventType.REPLY]
            runner.deliver(events[0])
            # The white answer in the first case is the one that changes it.
            assert (app.theme is LIGHT) is reply.endswith(b"\x07")
        finally:
            os.close(read_fd)


def test_the_background_query_does_not_wait_for_an_answer():
    """The runner asks and moves on, so a quiet terminal holds nothing up."""
    from zettcode.tui.terminal import BACKGROUND_QUERY

    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd)
    app = TuiApp(Editor(), width=40, height=6, auto_theme=True)
    runner = TerminalRunner(app, terminal=terminal)
    original = app.theme

    try:
        runner._ask_terminal_scheme()  # nothing is written to the pipe, so nothing comes back

        assert terminal.output.getvalue() == BACKGROUND_QUERY
        assert app.theme is original
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_parse_background_reads_the_two_spellings_terminals_use():
    from zettcode.tui import parse_background, scheme_named

    assert parse_background("\x1b]11;rgb:1e1e/1e1e/1e1e\x1b\\") == "#1e1e1e"  # iTerm2, four digits
    assert parse_background("\x1b]11;rgb:ff/ff/ff\x07") == "#ffffff"  # xterm, two digits
    assert parse_background("") is None
    assert parse_background("\x1b]11;?\x07") is None

    assert scheme_named("#f7f8f7") == "light"
    assert scheme_named("#101214") == "dark"
    assert scheme_named(None) is None
