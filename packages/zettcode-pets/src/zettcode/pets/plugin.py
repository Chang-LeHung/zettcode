"""The plugin that offers the pets that ship to ``/pet``.

An ordinary plugin found through the ``zettcode.plugin`` entry point. The terminal does not require it: without it
``/pet`` lists nothing and the companion is not drawn, and ``[plugins] disable = ["pets"]`` is how a reader gets there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.pets import bundled_pets
from zettcode.plugin_api.plugin import TuiPlugin

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.plugin_api import PluginContext


class PetsPlugin(TuiPlugin):
    """The pets that ship with the program, offered the way any plugin offers one.

    They are registered before the installed plugins', so they are listed first in the ``/pet`` menu, and a plugin
    cannot register a name they hold. Adding a pet is adding a module beside the others and its name to ``BUNDLED``;
    nothing here knows what a pet looks like.
    """

    name = "pets"
    description = "The companion pets"

    def activate(self, ctx: PluginContext) -> None:
        """Offer each pet by name. Nothing is built until one is asked for."""
        if ctx.tui is None:
            return
        for source in bundled_pets():
            ctx.tui.register_pet(source.name, source.load, description=source.description)
