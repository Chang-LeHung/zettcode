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
    "BUILTIN_PLUGINS": ".builtins",
    "Activity": ".state",
    "ActivityState": ".state",
    "DisplayState": ".state",
    "ModelState": ".state",
    "SessionState": ".state",
    "ShellContext": ".state",
    "UiBuilder": ".state",
    "UiRegion": ".state",
    "UiRow": ".state",
    "UiSegment": ".state",
    "UiSide": ".state",
    "PluginUiMixin": ".mixins",
    "PluginContext": "zettcode.engine.plugins.context",
    "UiSlots": ".groups",
    "TuiGroups": ".groups",
    "TuiPlugin": ".plugin",
    "TuiPlugins": ".plugin",
    "TerminalLoader": ".loader",
    "load_terminal_plugins": ".loader",
    "HOST_LINK": ".host",
    "HostLink": ".host",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from zettcode.engine.plugins.context import PluginContext

    from .builtins import BUILTIN_PLUGINS
    from .groups import UiSlots
    from .host import HOST_LINK, HostLink
    from .loader import TerminalLoader, load_terminal_plugins
    from .mixins import PluginUiMixin
    from .plugin import TuiPlugin, TuiPlugins
    from .state import (
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
    "BUILTIN_PLUGINS",
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
