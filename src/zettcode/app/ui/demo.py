"""Watch a turn's running rows blink: ``make demo-thinking``.

The pulse normally belongs to a live request, where it is easy to miss: the
first token can arrive before the eye reaches the row. This module mounts the
same machinery in a throwaway application and walks one turn after another —
wait, then thinking, then a tool call — so every running row can be watched on
its own.

It is a demo, not a second entry point: nothing here is imported by the shell.
"""

from __future__ import annotations

import asyncio

from ...tui import DARK, Slot, Text, TuiApp, VBox, Widget, run_app
from ...tui.widgets import Rule
from ..agent.transcript import Transcript
from .widgets import TranscriptView

HINT = "  q / Esc quit \u00b7 a highlight travels across each running row's wording"


class Blinking(Widget):
    """Root that keeps frames coming and moves the transcript's blink on.

    The real shell does this from its own root while a request runs; the demo
    needs it because no request ever ends here.
    """

    def __init__(self, transcript: Transcript, body: Widget) -> None:
        """Keep the transcript to advance and the tree to paint."""
        super().__init__()
        self.transcript = transcript
        self.body = body

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the body so it lays out and paints."""
        return (self.body,)

    def layout(self, rect) -> None:
        """Give the body the full rectangle."""
        super().layout(rect)
        self.body.layout(rect)

    def render(self, canvas) -> None:
        """Paint the body into the shared canvas."""
        self.body.render(canvas)

    def cursor(self):
        """Forward the cursor request to the body."""
        return self.body.cursor()

    def on_tick(self) -> None:
        """Ask for the next frame, then advance the blink.

        Re-registering the animation token on every tick is what keeps the loop
        alive: the scheduler stops waiting once nothing is animating, and unlike
        a request there is nothing here that would release it later.
        """
        if self.app is not None:
            self.app.scheduler.animate("blink")
        self.transcript.advance_frame()


def build(transcript: Transcript | None = None) -> TuiApp:
    """Build the demo application around an empty transcript."""
    transcript = Transcript() if transcript is None else transcript
    body = VBox(
        [
            Slot(Rule(), size=1),
            Slot(TranscriptView(transcript, theme=DARK), flex=1),
            Slot(Rule(), size=1),
            Slot(Text(HINT, muted=True), size=1),
        ]
    )
    app = TuiApp(Blinking(transcript, body), theme=DARK)
    app.commands.add("quit", lambda event, host: (host.exit(), True)[1])
    for key in ("q", "escape", "ctrl_c"):
        app.keymap.bind(key, "quit", priority="capture")
    return app


async def script(transcript: Transcript) -> None:
    """Walk one turn after another so each running row can be watched.

    The pauses are deliberately uneven: the wait is the shortest state, because
    a real model usually answers before a thinking block appears.
    """
    while True:
        transcript.begin_turn("演示：请求已发出，等模型开口")
        await asyncio.sleep(2.0)
        transcript.start_thinking()
        for line in ("先看清问题\u2026", "再看相关文件\u2026", "最后给出答案\u2026"):
            transcript.append_thinking(line)
            await asyncio.sleep(1.2)
        transcript.start_tool("call-1", "read_file", {"path": "src/zettcode/app/ui/app.py"})
        await asyncio.sleep(2.0)
        transcript.complete_tool("call-1", "def main() -> None:\n    ...")
        transcript.append_answer("演示到此结束，下一轮重新开始。\n")
        await asyncio.sleep(2.0)
        transcript.clear()


async def _main() -> None:
    """Run the application and the scripting task together."""
    transcript = Transcript()
    turn = asyncio.create_task(script(transcript))
    try:
        await run_app(build(transcript))
    finally:
        turn.cancel()
        await asyncio.gather(turn, return_exceptions=True)


def main() -> None:
    """Console entry point for ``make demo-thinking``."""
    asyncio.run(_main())


if __name__ == "__main__":
    main()
