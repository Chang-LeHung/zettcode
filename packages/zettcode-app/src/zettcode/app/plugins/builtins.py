"""The palettes ZettCode ships with, written as an ordinary plugin.

The default header, status and turn-line rows moved to ``zettcode-presenters`` (``rows.py``), so this module holds
only the bundled palettes; the app has no built-in plugins, and the loader finds every terminal part through its
entry point.
"""

from __future__ import annotations

from zettcode.engine.plugins.context import PluginContext
from zettcode.plugin_api.plugin import TuiPlugin
from zettcode.tui import bundled_themes

from .groups import require_tui


class BuiltinThemes(TuiPlugin):
    """The palettes that ship with the program, offered the way any plugin offers one.

    They are TOML files beside the theme loader, so adding a built-in palette is adding a file and a name to
    ``BUNDLED``; nothing here knows what a palette looks like. They are registered first, so they are listed first
    in the ``/theme`` menu, and a plugin cannot register a name they hold.
    """

    name = "themes"

    def activate(self, ctx: PluginContext) -> None:
        """Offer each palette file by name. Nothing is read until one is asked for."""
        if ctx.tui is None:
            return  # loaded by a process with no screen (the server): there is nothing to offer a palette to
        tui = require_tui(ctx)
        for source in bundled_themes():
            tui.register_theme(source.name, source.load, description=source.description)
