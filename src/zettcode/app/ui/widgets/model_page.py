"""The full-screen model picker opened by ``/model``."""

from __future__ import annotations

from collections.abc import Callable

from ....config import ModelConfig
from ....tui import Host, KeyEvent, ListItem, ListView, Style, Widget
from ...agent.agent import ZettCodeAgent

#: Most model rows shown at once; the list scrolls when more are configured.
VISIBLE_ROWS = 6


class ModelPage(Widget):
    """An opaque, bounded list of the configured models.

    Shape::

        Select Model                       <- title, two cells in from the edge

          > 1. GPT-4o (current)  ...       <- selection bands the whole row
            2. DeepSeek Chat

        enter select · esc back            <- footer, on the bottom row

    It covers the composer while it is up and owns no state of its own: the
    list hands the chosen :class:`ModelConfig` to ``on_select``, and Escape or
    ``on_cancel`` returns to the shell, which pops this screen.
    """

    def __init__(
        self, agent: ZettCodeAgent, *, on_select: Callable[[ModelConfig], None], on_cancel: Callable[[], None]
    ) -> None:
        """List every configured model, starting on the active one.

        Args:
            agent: Supplies the models and marks which one is active.
            on_select: Receives the chosen entry; the same model id can appear
                twice with different endpoints, so the whole entry is passed.
            on_cancel: Called when the user presses Escape.
        """
        super().__init__()
        self.on_cancel = on_cancel
        self.list = ListView(
            [
                ListItem(
                    entry,
                    f"{index}. {entry.shown_name}{' (current)' if entry is agent.active_model else ''}",
                    f"{entry.model} · {'multimodal' if entry.multimodal else 'text'}",
                )
                for index, entry in enumerate(agent.models, start=1)
            ],
            on_select=lambda item: on_select(item.value),
            wrap=False,
            band=True,
        )
        self.list.select(agent.models.index(agent.active_model), notify=False)

    @property
    def children(self) -> tuple[Widget, ...]:
        """Expose the list so it participates in layout and focus."""
        return (self.list,)

    def layout(self, rect) -> None:
        """Inset the list under the title, capped to ``VISIBLE_ROWS`` rows."""
        super().layout(rect)
        self.list.layout(
            type(rect)(rect.x + 2, rect.y + 3, max(0, rect.width - 4), min(VISIBLE_ROWS, max(0, rect.height - 5)))
        )

    def render(self, canvas) -> None:
        """Fill the screen, then draw the title, the list, and the footer."""
        if self.rect.empty:
            return
        theme = self.theme
        canvas.fill(self.rect.x, self.rect.y, self.rect.width, self.rect.height, Style(background=theme.surface_alt))
        canvas.draw_text(
            self.rect.x + 2,
            self.rect.y + 1,
            "Select Model",
            Style(foreground=theme.text, background=theme.surface_alt, bold=True),
        )
        self.list.render(canvas)
        canvas.draw_text(
            self.rect.x + 2,
            self.rect.bottom - 1,
            "enter select \u00b7 esc back",
            Style(foreground=theme.muted, background=theme.surface_alt),
            max_width=max(0, self.rect.width - 2),
        )

    def capture_event(self, event, host: Host) -> bool:
        """Close on Escape before the focused list can see the key."""
        if isinstance(event, KeyEvent) and event.key == "escape":
            self.on_cancel()
            return True
        return False
