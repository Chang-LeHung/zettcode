"""The full-screen model picker opened by ``/model``."""

from __future__ import annotations

from collections.abc import Callable

from ....config import ModelConfig
from ....tui import ListItem, ListPage
from ...agent.agent import ZettCodeAgent


class ModelPage(ListPage):
    """The configured models as a selectable :class:`ListPage`.

    Shape::

        Select Model
          > 1. GPT-4o (current)   gpt-4o \u00b7 multimodal
            2. DeepSeek Chat      deepseek-chat \u00b7 text
        enter select \u00b7 esc back

    The page only maps models to rows; the title, background, bounded scrolling,
    and Escape handling come from the base class. Each row carries the
    :class:`ModelConfig` itself, because the same model id can be configured
    twice against different endpoints and the chosen entry, not its name, is
    what the shell applies. It asks for a bottom panel rather than the whole
    screen, so the conversation stays visible while the model is chosen.
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
        super().__init__(
            [
                ListItem(
                    entry,
                    f"{index}. {entry.shown_name}{' (current)' if entry is agent.active_model else ''}",
                    f"{entry.model} \u00b7 {'multimodal' if entry.multimodal else 'text'}",
                )
                for index, entry in enumerate(agent.models, start=1)
            ],
            title="Select Model",
            on_select=lambda item: on_select(item.value),
            on_cancel=on_cancel,
            selected=agent.models.index(agent.active_model),
            overlay_rows=14,
        )
