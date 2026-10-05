"""Shared scaffolding for the perf probes: an offline app and a stage timer.

Every probe needs the same two things: the real application running against a
throwaway workspace and store, and a clock around each phase of a frame. This
module builds the first with :meth:`ZettCodeRuntime.preview` — the same seam the
shell uses to paint before the provider exists — and wraps the second in
:class:`Painter`, which mirrors ``TerminalRunner.paint`` stage for stage.

Nothing here imports the test suite or opens a socket. A run is deterministic
enough to compare before and after a change, which is the point.
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from time import perf_counter

from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.runtime import ZettCodeRuntime
from zettcode.app.agent.transcript import Transcript
from zettcode.app.ui import ZettCodeApp
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.tui import DifferentialRenderer, TextEvent
from zettcode.tui.core.app import TuiApp

#: A model nothing ever calls; the probes seed the transcript directly.
_FAKE_MODEL = ModelConfig(model="perf-model", token="perf-token")

#: Width and height of the synthetic terminal, in cells.
DEFAULT_WIDTH = 120
DEFAULT_HEIGHT = 40

#: Answer body written once per seeded turn, so Markdown has real work to do.
_ANSWER = (
    "Here is the change I made to `render_frame`:\n\n"
    "```python\n"
    "def render(self) -> Canvas:\n"
    "    ...\n"
    "```\n\n"
    "It keeps the previous frame and only rewrites the cells that moved.\n"
)


class Clock:
    """A hand-driven monotonic clock, so animation steps are reproducible."""

    def __init__(self, start: float = 0.0) -> None:
        """Start at ``start`` seconds, by default zero."""
        self.now = start

    def __call__(self) -> float:
        """Return the current fake time."""
        return self.now

    def advance(self, seconds: float) -> None:
        """Move the clock forward, as one terminal frame's worth of time would."""
        self.now += seconds


@dataclass(frozen=True, slots=True)
class StageTimings:
    """Wall time one frame spent in each stage, in seconds.

    Attributes:
        dispatch: Routing one input event through the widget tree.
        layout: Re-measuring geometry, paid only when the tree asked for it.
        tick: Letting every mounted widget react to the clock.
        paint: Building a fresh canvas from the widget tree.
        cursor: Asking the focused widget where the caret goes.
        diff: Diffing the canvas against the last frame and writing escapes.
    """

    dispatch: float = 0.0
    layout: float = 0.0
    tick: float = 0.0
    paint: float = 0.0
    cursor: float = 0.0
    diff: float = 0.0

    @property
    def total(self) -> float:
        """Return the summed stage time in seconds."""
        return self.dispatch + self.layout + self.tick + self.paint + self.cursor + self.diff

    def plus(self, other: StageTimings) -> StageTimings:
        """Return the element-wise sum, for averaging across frames."""
        return StageTimings(
            dispatch=self.dispatch + other.dispatch,
            layout=self.layout + other.layout,
            tick=self.tick + other.tick,
            paint=self.paint + other.paint,
            cursor=self.cursor + other.cursor,
            diff=self.diff + other.diff,
        )

    def divided(self, count: int) -> StageTimings:
        """Return the per-frame average over ``count`` frames."""
        return StageTimings(
            dispatch=self.dispatch / count,
            layout=self.layout / count,
            tick=self.tick / count,
            paint=self.paint / count,
            cursor=self.cursor / count,
            diff=self.diff / count,
        )

    def stages(self) -> tuple[tuple[str, float], ...]:
        """Return the non-zero stages in the order a frame runs them."""
        pairs = (
            ("dispatch", self.dispatch),
            ("layout", self.layout),
            ("tick", self.tick),
            ("paint", self.paint),
            ("cursor", self.cursor),
            ("diff", self.diff),
        )
        return tuple((name, seconds) for name, seconds in pairs if seconds > 0)


class Painter:
    """Paint frames through the real differential renderer, timed per stage.

    This is ``TerminalRunner.paint`` without the terminal and without the test
    harness's snapshot pass, so the numbers describe the application, not the
    measuring tool.
    """

    def __init__(self, app: TuiApp) -> None:
        """Bind a renderer to an in-memory sink."""
        self.app = app
        self.output = StringIO()
        self.renderer = DifferentialRenderer(self.output)

    def frame(self, *, text: str | None = None) -> StageTimings:
        """Paint one frame and return the time each stage took.

        Args:
            text: When given, dispatch this text as one input event first, which
                is what a keystroke does before the repaint it triggers.
        """
        app = self.app
        timings = StageTimings()
        if text is not None:
            start = perf_counter()
            app.dispatch(TextEvent(text=text))
            timings = timings.plus(StageTimings(dispatch=perf_counter() - start))
        if app.layout_pending:
            start = perf_counter()
            app.layout()
            timings = timings.plus(StageTimings(layout=perf_counter() - start))
        if app.refreshed:
            app.refreshed = False
            self.renderer.reset()
        start = perf_counter()
        app.tick()
        timings = timings.plus(StageTimings(tick=perf_counter() - start))
        start = perf_counter()
        canvas = app.render()
        timings = timings.plus(StageTimings(paint=perf_counter() - start))
        start = perf_counter()
        cursor = app.cursor()
        timings = timings.plus(StageTimings(cursor=perf_counter() - start))
        self.output.seek(0)
        self.output.truncate(0)
        start = perf_counter()
        self.renderer.render(canvas, cursor=None if cursor is None else (cursor.x, cursor.y))
        return timings.plus(StageTimings(diff=perf_counter() - start))


@dataclass(slots=True)
class PerfApp:
    """A real shell, a throwaway workspace, and a transcript to measure."""

    app: ZettCodeApp
    painter: Painter
    workspace: Path
    clock: Clock
    _temp: tempfile.TemporaryDirectory[str] = field(repr=False)

    @property
    def transcript(self) -> Transcript:
        """Return the transcript the probes seed and render."""
        return self.app.transcript

    def frame(self, *, text: str | None = None) -> StageTimings:
        """Paint one frame through the painter."""
        return self.painter.frame(text=text)

    def advance(self, seconds: float) -> None:
        """Move the fake clock forward before the next frame."""
        self.clock.advance(seconds)

    def close(self) -> None:
        """Drop the temporary workspace and store."""
        self._temp.cleanup()


def seed(transcript: Transcript, turns: int, *, busy: bool = False) -> None:
    """Fill a transcript with ``turns`` finished turns, like a long session.

    Each turn walks the same shape a real one does — user, reasoning, a tool
    call and its result, then a Markdown answer — so the block types and their
    sizes match what the shell actually measures. ``busy`` leaves a trailing
    running row, which is what keeps the animation ticking.
    """
    for index in range(turns):
        transcript.begin_turn(f"Question {index}: why is the frame slow?")
        transcript.start_thinking()
        transcript.append_thinking(f"Checking the render path for turn {index}.\n")
        transcript.complete_thinking()
        transcript.start_tool(f"call-{index}", "read_file", {"path": "src/zettcode/app/ui/app.py"})
        transcript.complete_tool(f"call-{index}", "def render(self) -> None:\n    ...")
        transcript.append_answer(f"{_ANSWER}\n")
    if busy:
        transcript.begin_turn("A live question, still waiting for the model")


def build(
    turns: int,
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    busy: bool = False,
    seed_transcript: bool = True,
) -> PerfApp:
    """Build an offline application with ``turns`` seeded turns.

    Args:
        turns: Finished turns to seed; ignored when ``seed_transcript`` is off.
        width: Synthetic terminal width in cells.
        height: Synthetic terminal height in cells.
        busy: Leave a running row so the activity animation keeps ticking.
        seed_transcript: Fill the transcript; off leaves the welcome banner only.
    """
    temp = tempfile.TemporaryDirectory(prefix="zettcode-perf-")
    workspace = Path(temp.name)
    config = ZettCodeConfig(
        workspace=workspace,
        store=workspace / "sessions",
        models=(_FAKE_MODEL,),
        plugins_enabled=False,
        skills_enabled=False,
        mcp_enabled=False,
    )
    app = ZettCodeApp(ZettCodeAgent(ZettCodeRuntime.preview(config)))
    clock = Clock()
    app.app.clock = clock
    app.transcript.clock = clock
    app.app.resize(width, height)
    app.app.mount()
    app.app.focus(app.composer)
    if seed_transcript:
        seed(app.transcript, turns, busy=busy)
    painter = Painter(app.app)
    painter.frame()  # Warm every cache and settle the first frame.
    return PerfApp(app=app, painter=painter, workspace=workspace, clock=clock, _temp=temp)


def table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """Return a left-aligned text table, sized to its widest cells."""
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    lines = ["  ".join(header.ljust(widths[index]) for index, header in enumerate(headers))]
    lines.append("  ".join("-" * width for width in widths))
    lines.extend("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)) for row in rows)
    return "\n".join(lines)
