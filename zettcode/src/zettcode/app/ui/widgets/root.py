"""The shell's root widget, which drives the activity animation tick."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.tui import VBox, Widget

if TYPE_CHECKING:  # pragma: no cover - the shell imports this module at runtime
    from ..app import ZettCodeApp
    from .pet import PetView


class ZettCodeRoot(Widget):
    """Thin root that advances the activity frame while a request runs.

    It holds the controller only to read ``busy`` and advance the transcript's
    frame on every tick; the type is imported under ``TYPE_CHECKING`` so the
    shell can import this module without a cycle. The pet stands on top of the
    body, so it is painted last and is the first thing a click on its cells finds.
    """

    def __init__(self, controller: ZettCodeApp, body: VBox, pet: PetView | None = None) -> None:
        """Keep the controller reachable from the tick hook."""
        super().__init__()
        self.controller = controller
        self.body = body
        self.pet = pet

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the body widget the root lays out, and the pet over it."""
        return (self.body,) if self.pet is None else (self.body, self.pet)

    def layout(self, rect) -> None:
        """Give the body the full application rectangle, then let the pet stand in the conversation it left."""
        super().layout(rect)
        self.body.layout(rect)
        if self.pet is not None:
            self.pet.layout(rect)

    def render(self, canvas) -> None:
        """Paint the body into the shared canvas, and the pet over it."""
        self.body.render(canvas)
        if self.pet is not None:
            self.pet.render(canvas)

    def cursor(self):
        """Forward the cursor request to the body."""
        return self.body.cursor()

    def on_tick(self) -> bool:
        """Advance the activity frame while a request is running.

        A flash in the row above the composer asks for the next frame too: it
        expires on the clock rather than on an event, so something has to keep
        painting until it does. The flash and the effort gauge ask by invalidating,
        which the loop sees for itself; what this reports is the animation.

        Returns:
            Whether the activity animation's picture is different from the last one
            drawn. ``False`` for most of the steps of a long wait: they repeat.
        """
        self.controller.settle_flash()
        self.controller.settle_effort_animation()
        if self.controller.busy and (self.app is None or not self.app.reduced_motion):
            return self.controller.transcript.advance_frame()
        return False
