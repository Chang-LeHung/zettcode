"""The terminal's plugin support: what a plugin adds beyond the agent.

A plugin that adds a command, a palette, a pet, a presenter or a header or status segment::

    from zettcode.app.plugins import CommandResult, TerminalContainer, TerminalPlugin

    class Greeter(TerminalPlugin):
        name = "greeter"

        def activate(self, container: TerminalContainer) -> None:
            container.register_command("greet", "say hello", self.greet)

        async def greet(self, context) -> CommandResult:
            return CommandResult(notification=f"hello {context.argument}".strip())

It is built on :mod:`zettcode.engine.plugins`, which has what the agent uses. The pieces live in
:mod:`~zettcode.app.plugins.state` (the snapshot and segment types), :mod:`~zettcode.app.plugins.mixins` (the row
hooks), :mod:`~zettcode.app.plugins.container`, :mod:`~zettcode.app.plugins.plugin`, and
:mod:`~zettcode.app.plugins.loader`. Names load on first use, so importing one does not build the rest.
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
    "TerminalContainer": ".container",
    "UiSlots": ".container",
    "TerminalPlugin": ".plugin",
    "TerminalPlugins": ".plugin",
    "TerminalLoader": ".loader",
    "load_terminal_plugins": ".loader",
    "HOST_LINK": ".host",
    "HostLink": ".host",
}


if TYPE_CHECKING:  # pragma: no cover - for type checkers, not the runtime
    from .builtins import BUILTIN_PLUGINS
    from .container import TerminalContainer, UiSlots
    from .host import HOST_LINK, HostLink
    from .loader import TerminalLoader, load_terminal_plugins
    from .mixins import PluginUiMixin
    from .plugin import TerminalPlugin, TerminalPlugins
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
    "SessionState",
    "ShellContext",
    "TerminalContainer",
    "TerminalLoader",
    "TerminalPlugin",
    "TerminalPlugins",
    "UiBuilder",
    "UiRegion",
    "UiRow",
    "UiSegment",
    "UiSide",
    "UiSlots",
    "load_terminal_plugins",
]
