"""The plugin that offers the program's own row drawing to the terminal.

It is an ordinary plugin, found through the ``zettcode.plugin`` entry point like any other, and the terminal lists it
as required: the program does not start without it, and ``[plugins] disable`` does not reach it. It needs nothing
else, and the plugins that draw more kinds of row depend on it (``deps = ("presenters",)``) so theirs register after.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.presenters.presenters import BUILTIN_PRESENTERS

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext


class PresentersPlugin(TuiPlugin):
    """How the program draws its own rows, offered the way any plugin offers a presenter.

    They register at the priority their class declares, which is the lowest there is, so a plugin that draws the same
    kind or family wins without having to outrank them. Adding a built-in kind of row is adding a presenter to
    ``BUNDLED`` in the conversation and nothing here.
    """

    name = "presenters"
    description = "Draws the conversation: messages, tool calls, results and the rest"

    def activate(self, ctx: PluginContext) -> None:
        """Register every built-in presenter at the priority its class declares."""
        if ctx.tui is None:
            return
        for presenter in BUILTIN_PRESENTERS:
            ctx.tui.register_presenter(presenter)
