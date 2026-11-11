"""The full-screen model picker opened by ``/model``."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from zettcode.sdk.client import Client
from zettcode.sdk.types import ModelInfo
from zettcode.tui import SEPARATOR, ListItem, ListPage


class ModelPage(ListPage):
    """The configured models as a selectable :class:`ListPage`.

    Shape::

        Select Model
          >  1. GPT-4o (current)    file \u00b7 chat \u00b7 multimodal
             2. Acme Large         plugin acme \u00b7 chat \u00b7 text
            10. Claude Sonnet 4.5   file \u00b7 anthropic \u00b7 text
        enter select \u00b7 esc back

    The page only maps models to rows; the title, background, bounded scrolling,
    and Escape handling come from the base class. Row numbers are right-aligned to
    the widest of them, as the session picker's are, so a name starts in the same
    column on the tenth row as on the first. Each row carries the
    :class:`ModelInfo` itself, because the same model id can be configured
    twice against different endpoints and the chosen entry, not its name, is
    what the shell applies. A row names where the entry came from and the API it speaks — ``file`` or
    ``plugin <host>`` — which a name cannot tell the reader.
    The command wraps it in a bottom panel, so the conversation stays visible
    while the model is chosen.
    """

    def __init__(
        self, client: Client, *, on_select: Callable[[ModelInfo], None], on_cancel: Callable[[], None]
    ) -> None:
        """List every configured model, starting on the active one.

        Args:
            client: Supplies the models and marks which one is active.
            on_select: Receives the chosen entry; the same model id can appear
                twice with different endpoints, so the whole entry is passed.
            on_cancel: Called when the user presses Escape.
        """
        models = client.models
        # As many columns as the largest number needs, so the names line up.
        digits = len(str(len(models))) if models else 1
        super().__init__(
            [
                ListItem(
                    entry,
                    f"{index:>{digits}}. {entry.name}{' (current)' if entry.active else ''}",
                    _subtitle(entry),
                )
                for index, entry in enumerate(models, start=1)
            ],
            title="Select Model",
            on_select=lambda item: on_select(cast(ModelInfo, item.value)),
            on_cancel=on_cancel,
            selected=next((i for i, entry in enumerate(models) if entry.active), 0),
        )


def _subtitle(entry: ModelInfo) -> str:
    """Return the line under a model's name: where it came from, then what it is and what it still needs."""
    source = f"plugin {entry.provider}" if entry.provider is not None else "file"
    parts = [source]
    if entry.token_env is not None:
        parts.append(f"needs ${entry.token_env}")
    parts.extend([entry.api, "multimodal" if entry.multimodal else "text"])
    return f" {SEPARATOR} ".join(parts)
