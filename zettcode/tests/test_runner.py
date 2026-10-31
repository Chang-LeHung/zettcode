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
from zettcode.tui.core import app as tui_app_module
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
    # The differential renderer writes only changed cells, so the frame holds the edit rather than
    # a copy of the row. Both keys were waiting when the loop looked, so they are one frame: "hi>".
    assert "\x1b[2J" in frame
    assert "hi>" in frame
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


async def test_a_callback_runs_once_after_the_next_frame_has_been_written():
    """Work that must not compete with a frame is started from the end of it, and only the next one."""
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    app = TuiApp(Editor(), width=24, height=3)
    runner = TerminalRunner(app, terminal=terminal)
    seen: list[tuple[str, int]] = []
    runner.after_next_paint(lambda: seen.append(("first", len(terminal.output.getvalue()))))
    runner.after_next_paint(lambda: seen.append(("second", len(terminal.output.getvalue()))))

    assert seen == [], "registering it runs nothing"
    runner.paint()
    written = len(terminal.output.getvalue())

    assert [name for name, _ in seen] == ["first", "second"], "in the order they were asked for"
    assert all(size == written for _, size in seen), "after the frame was in the terminal's output, not before"
    assert written > 0
    runner.paint()
    assert len(seen) == 2, "a callback is for the next frame only"
    os.close(read_fd)
    os.close(write_fd)


async def test_a_callback_asked_for_while_a_frame_is_painting_waits_for_the_one_after():
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    app = TuiApp(Editor(), width=24, height=3)
    runner = TerminalRunner(app, terminal=terminal)
    seen: list[str] = []

    def first() -> None:
        seen.append("first")
        runner.after_next_paint(lambda: seen.append("later"))

    runner.after_next_paint(first)
    runner.paint()
    assert seen == ["first"]
    runner.paint()
    assert seen == ["first", "later"]
    os.close(read_fd)
    os.close(write_fd)


async def test_waiting_for_a_frame_returns_only_after_it_is_written():
    """A command can let its row reach the screen before starting work with no await in it."""
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    app = TuiApp(Editor(), width=24, height=3)
    runner = TerminalRunner(app, terminal=terminal)
    app.begin_painting()

    waiting = asyncio.create_task(app.wait_for_frame())
    await asyncio.sleep(0)
    assert not waiting.done(), "nothing has painted yet"

    runner.paint()
    await asyncio.wait_for(waiting, 1.0)

    assert terminal.output.getvalue(), "the frame the wait released was written"
    app.end_painting()
    os.close(read_fd)
    os.close(write_fd)


async def test_a_wait_for_a_frame_releases_only_after_the_text_it_was_given_was_written():
    """The point of the wait: the next synchronous change must not be what the frame shows."""
    read_fd, write_fd = os.pipe()
    terminal = StubTerminal(read_fd, width=24, height=3)
    editor = Editor()
    app = TuiApp(editor, width=24, height=3)
    task = asyncio.create_task(run_app(app, terminal=terminal))
    try:
        await _wait_for(lambda: app.focused_widget() is not None)
        editor.text = "first"
        app.invalidate()
        await app.wait_for_frame()
        written = terminal.output.getvalue()
        editor.text = "second"
        app.invalidate()
        await _wait_for(lambda: "second" in terminal.output.getvalue())
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        os.close(read_fd)
        os.close(write_fd)

    assert "first" in written and "second" not in written, "the wait released before the next change was drawn"
    assert "second" in terminal.output.getvalue(), "a later frame still shows the change"


async def test_waiting_for_a_frame_without_a_runner_takes_one_scheduling_turn():
    """A headless tree has no runner to paint it, so a command must not wait forever."""
    app = TuiApp(Editor(), width=24, height=3)

    await asyncio.wait_for(app.wait_for_frame(), 1.0)


async def test_a_frame_that_never_arrives_is_a_missed_frame_not_a_wedged_command(monkeypatch):
    app = TuiApp(Editor(), width=24, height=3)
    app.begin_painting()
    monkeypatch.setattr(tui_app_module, "FRAME_WAIT", 0.01)

    started = asyncio.get_running_loop().time()
    await asyncio.wait_for(app.wait_for_frame(), 1.0)

    assert asyncio.get_running_loop().time() - started < 0.5
    assert not app.waiting_for_frame
    app.end_painting()


# -- a burst of input is one frame --------------------------------------------------------------------------


class _Counter(Widget):
    """Counts the events it is handed and the frames drawn for them."""

    def __init__(self) -> None:
        super().__init__()
        self.events = 0
        self.frames = 0

    @property
    def focusable(self) -> bool:
        return True

    def render(self, canvas) -> None:
        self.frames += 1
        canvas.draw_text(0, 0, f"events {self.events}", max_width=self.rect.width)

    def handle(self, event: AnyEvent, host: Host) -> bool:
        if isinstance(event, TextEvent):
            self.events += 1
            host.invalidate()
            return True
        if isinstance(event, KeyEvent) and event.key == "escape":
            host.exit()
            return True
        return False


async def _run_with_queued(count: int, *, batch: int | None = None):
    from zettcode.tui import runner as runner_module
    from zettcode.tui.input import EventType, InputEvent

    read_fd, write_fd = os.pipe()
    counter = _Counter()
    app = TuiApp(counter, width=30, height=3)
    runner = TerminalRunner(app, terminal=StubTerminal(read_fd, width=30, height=3))
    original = runner_module.MAX_BATCH
    if batch is not None:
        runner_module.MAX_BATCH = batch
    task = asyncio.create_task(runner.run())
    try:
        await _wait_for(lambda: app.focused_widget() is not None)
        await asyncio.sleep(0.05)
        frames_before = counter.frames
        for _ in range(count):  # all queued before the loop gets another turn
            runner.queue.put_nowait(InputEvent(type=EventType.TEXT, text="x"))
        await _wait_for(lambda: counter.events == count)
        await asyncio.sleep(0.05)
        return counter.events, counter.frames - frames_before
    finally:
        runner_module.MAX_BATCH = original
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        os.close(read_fd)
        os.close(write_fd)


async def test_a_burst_of_queued_events_is_drawn_once_not_once_per_event():
    """The bug: a wheel flick queued a hundred and twenty notches and the loop painted between each,
    three quarters of a second of crawl after the reader had stopped."""
    events, frames = await _run_with_queued(100)

    assert events == 100 and frames <= 2, f"{frames} frames for 100 queued events"


async def test_a_single_event_is_still_drawn_at_once():
    events, frames = await _run_with_queued(1)

    assert events == 1 and frames == 1


async def test_a_flood_larger_than_the_batch_is_still_all_delivered_and_painted_between_batches():
    events, frames = await _run_with_queued(40, batch=10)

    assert events == 40
    assert 2 <= frames <= 6, "bounded batches: several frames, never one per event and never a starved loop"


async def test_escape_in_the_middle_of_a_burst_stops_the_batch_where_the_app_stopped():
    from zettcode.tui.input import EventType, InputEvent

    read_fd, write_fd = os.pipe()
    counter = _Counter()
    app = TuiApp(counter, width=30, height=3)
    runner = TerminalRunner(app, terminal=StubTerminal(read_fd, width=30, height=3))
    task = asyncio.create_task(runner.run())
    try:
        await _wait_for(lambda: app.focused_widget() is not None)
        for index in range(20):
            runner.queue.put_nowait(InputEvent(type=EventType.TEXT, text="x"))
            if index == 4:
                runner.queue.put_nowait(InputEvent(type=EventType.KEY, key="escape"))
        await asyncio.wait_for(task, 3.0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        os.close(read_fd)
        os.close(write_fd)

    assert app.running is False and counter.events == 5, "nothing after the key that ended the app was applied"


async def test_a_flick_of_wheel_events_queued_together_moves_the_view_half_a_window_not_pages():
    """The bug, through the real loop: a trackpad's momentum arrives as a burst, the loop applies it as one
    batch and draws once, and the rows in between used to be skipped, ten at a time, for several pages."""
    from zettcode.tui import MouseAction, ScrollView, Span, TextLine
    from zettcode.tui.input import EventType, InputEvent
    from zettcode.tui.layout import LineSource

    class Rows(LineSource):
        """A thousand numbered rows."""

        def count(self, width: int) -> int:
            return 1000

        def line(self, index: int, width: int) -> TextLine:
            return TextLine((Span(f"row {index}"),))

    read_fd, write_fd = os.pipe()
    view = ScrollView(Rows(), follow_tail=False, focusable=True)
    app = TuiApp(view, width=30, height=20)
    runner = TerminalRunner(app, terminal=StubTerminal(read_fd, width=30, height=20))
    task = asyncio.create_task(runner.run())
    try:
        await _wait_for(lambda: app.focused_widget() is not None)
        view.scroll_to(500)
        app.invalidate()
        await asyncio.sleep(0.05)
        start = view.top
        for _ in range(100):  # all queued before the loop gets another turn
            runner.queue.put_nowait(
                InputEvent(type=EventType.MOUSE, x=1, y=1, action=MouseAction.SCROLL_DOWN, button=0)
            )
        await _wait_for(lambda: view.top != start)
        await asyncio.sleep(0.1)

        assert 0 < view.top - start <= 10, f"moved {view.top - start} rows for one burst in a window of 20"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        os.close(read_fd)
        os.close(write_fd)
