"""The shell's root widget, which drives the activity animation tick."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....tui import VBox, Widget

if TYPE_CHECKING:  # pragma: no cover - the shell imports this module at runtime
    from ..app import ZettCodeApp


class ZettCodeRoot(Widget):
    """Thin root that advances the activity frame while a request runs.

    It holds the controller only to read ``busy`` and advance the transcript's
    frame on every tick; the type is imported under ``TYPE_CHECKING`` so the
    shell can import this module without a cycle.
    """

    def __init__(self, controller: ZettCodeApp, body: VBox) -> None:
        """Keep the controller reachable from the tick hook."""
        super().__init__()
        self.controller = controller
        self.body = body

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the single body widget the root lays out."""
        return (self.body,)

    def layout(self, rect) -> None:
        """Give the body the full application rectangle."""
        super().layout(rect)
        self.body.layout(rect)

    def render(self, canvas) -> None:
        """Paint the body into the shared canvas."""
        self.body.render(canvas)

    def cursor(self):
        """Forward the cursor request to the body."""
        return self.body.cursor()

    def on_tick(self) -> None:
        """Advance the activity frame while a request is running."""
        if self.controller.busy and (self.app is None or not self.app.reduced_motion):
            self.controller.transcript.advance_frame()
