"""The terminal's plugins: the row hooks, the groups a shell plugin registers into, and the bundle it produces.

A plugin subclasses :class:`~zettcode.engine.plugins.Plugin` (or :class:`TuiPlugin` to override a row hook) and
registers through ``ctx``::

    from zettcode.app.plugins import TuiPlugin
    from zettcode.engine.plugins import PluginContext

    class Greeter(TuiPlugin):
        name = "greeter"

        def activate(self, ctx: PluginContext) -> None:
            ctx.tui.register_command("greet", "say hello", self.greet)

:class:`TuiPlugin` is the engine's base class with :class:`PluginUiMixin`; the shell's commands, palettes, pets,
presenters and rows live in :class:`~zettcode.app.plugins.groups.TuiGroups`, which is ``ctx.tui`` — ``None`` in a
process without a terminal, which is why a shell-only plugin starts ``activate`` with ``if ctx.tui is None: return``.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

#: Where each public name lives; read by :func:`__getattr__` on first use.
_EXPORTS = {
    "Activity": "zettcode.plugin_api.state",
    "ActivityState": "zettcode.plugin_api.state",
    "DisplayState": "zettcode.plugin_api.state",
    "ModelState": "zettcode.plugin_api.state",
    "SessionState": "zettcode.plugin_api.state",
    "ShellContext": "zettcode.plugin_api.state",
    "UiBuilder": "zettcode.plugin_api.state",
    "UiRegion": "zettcode.plugin_api.state",
    "UiRow": "zettcode.plugin_api.state",
    "UiSegment": "zettcode.plugin_api.state",
    "UiSide": "zettcode.plugin_api.state",
    "PluginUiMixin": "zettcode.plugin_api.mixins",
    "PluginContext": "zettcode.engine.plugins.context",
    "UiSlots": ".groups",
    "TuiGroups": ".groups",
    "TuiPlugin": "zettcode.plugin_api.plugin",
    "TuiPlugins": "zettcode.plugin_api.plugin",
    "TerminalLoader": ".loader",
    "load_terminal_plugins": ".loader",
    "HOST_LINK": "zettcode.plugin_api.host",
    "HostLink": "zettcode.plugin_api.host",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from zettcode.engine.plugins.context import PluginContext
    from zettcode.plugin_api.host import HOST_LINK, HostLink
    from zettcode.plugin_api.mixins import PluginUiMixin
    from zettcode.plugin_api.plugin import TuiPlugin, TuiPlugins
    from zettcode.plugin_api.state import (
        Activity,
        ActivityState,
        DisplayState,
        ModelState,
        SessionState,
        ShellContext,
        UiBuilder,
        UiRegion,
        UiRow,
        UiSegment,
        UiSide,
    )

    from .groups import UiSlots
    from .loader import TerminalLoader, load_terminal_plugins


def __getattr__(name: str) -> object:
    """Import the module a public name lives in, the first time it is asked for."""
    try:
        module = _EXPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    return getattr(importlib.import_module(module, __name__), name)


def __dir__() -> list[str]:
    """Return the names this package publishes."""
    return sorted(__all__)


__all__ = [
    "HOST_LINK",
    "Activity",
    "ActivityState",
    "DisplayState",
    "HostLink",
    "ModelState",
    "PluginUiMixin",
    "TuiGroups",
    "SessionState",
    "ShellContext",
    "PluginContext",
    "TerminalLoader",
    "TuiPlugin",
    "TuiPlugins",
    "UiBuilder",
    "UiRegion",
    "UiRow",
    "UiSegment",
    "UiSide",
    "UiSlots",
    "load_terminal_plugins",
]
