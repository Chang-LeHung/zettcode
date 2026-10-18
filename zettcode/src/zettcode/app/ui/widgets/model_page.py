"""The full-screen model picker opened by ``/model``."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.config import ModelConfig
from zettcode.tui import SEPARATOR, ListItem, ListPage


class ModelPage(ListPage):
    """The configured models as a selectable :class:`ListPage`.

    Shape::

        Select Model
          >  1. GPT-4o (current)    gpt-4o \u00b7 chat \u00b7 multimodal
             2. DeepSeek Chat       deepseek-chat \u00b7 chat \u00b7 text
            10. Claude Sonnet 4.5   claude-sonnet-4-5 \u00b7 anthropic \u00b7 text
        enter select \u00b7 esc back

    The page only maps models to rows; the title, background, bounded scrolling,
    and Escape handling come from the base class. Row numbers are right-aligned to
    the widest of them, as the session picker's are, so a name starts in the same
    column on the tenth row as on the first. Each row carries the
    :class:`ModelConfig` itself, because the same model id can be configured
    twice against different endpoints and the chosen entry, not its name, is
    what the shell applies. A row names the API its entry speaks as well,
    which is the one thing about a model a reader cannot infer from its name.
    The command wraps it in a bottom panel, so the conversation stays visible
    while the model is chosen.
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
        models = agent.models
        # As many columns as the largest number needs, so the names line up.
        digits = len(str(len(models))) if models else 1
        super().__init__(
            [
                ListItem(
                    entry,
                    f"{index:>{digits}}. {entry.shown_name}{' (current)' if entry is agent.active_model else ''}",
                    f"{entry.model} {SEPARATOR} {entry.api} {SEPARATOR} {'multimodal' if entry.multimodal else 'text'}",
                )
                for index, entry in enumerate(models, start=1)
            ],
            title="Select Model",
            on_select=lambda item: on_select(cast(ModelConfig, item.value)),
            on_cancel=on_cancel,
            selected=models.index(agent.active_model),
        )
