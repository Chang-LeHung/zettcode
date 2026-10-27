"""Which front end a plugin's contribution is meant for.

A plugin says what it needs with :attr:`~zettcode.engine.plugins.plugin.Plugin.surfaces`; a host loads the plugins
whose surfaces intersect the ones it is running. The point is the difference between the three kinds of contribution:
an agent extension, an ``@`` provider or a model provider works wherever the agent runs, while a command, a theme, a
pet, a presenter or a header row belongs to one front end and would be refused — or worse, misread — in another.

Surfaces:

- ``AGENT``: every front end. This is the default, because it is the widest thing a plugin can mean without saying
  anything, and a plugin that only contributes extensions or providers should not have to think about us.
- ``TUI``: the terminal — commands, palettes, pets, presenters, rows, the status line.
- ``VSCODE``: the editor client, which reaches the agent through ``zettcode-server``.
- ``WEB``: a browser client through the same server.

A loader runs with the set its front end implies (:data:`TERMINAL_SURFACES`, :data:`SERVER_SURFACES`), so the same
distribution can ship a command for the terminal and, say, an HTTP endpoint's worth of behaviour for the server
without either host tripping over the other half.
"""

from __future__ import annotations

from zettcode._compat import StrEnum

__all__ = [
    "DEFAULT_SURFACES",
    "SERVER_SURFACES",
    "SURFACE_NAMES",
    "TERMINAL_SURFACES",
    "Surface",
]


class Surface(StrEnum):
    """One front end a plugin may target."""

    AGENT = "agent"
    TUI = "tui"
    VSCODE = "vscode"
    WEB = "web"


#: Where every front end gets a plugin: the agent's own extensions, providers and ``@`` resources.
DEFAULT_SURFACES: frozenset[Surface] = frozenset({Surface.AGENT})

#: What the terminal loads: the agent's side, and the shell's.
TERMINAL_SURFACES: frozenset[Surface] = frozenset({Surface.AGENT, Surface.TUI})

#: What ``zettcode-server`` loads on behalf of both of its clients.
SERVER_SURFACES: frozenset[Surface] = frozenset({Surface.AGENT, Surface.VSCODE, Surface.WEB})

#: Every spelling a surface has in a report, in the order a message lists them.
SURFACE_NAMES: tuple[str, ...] = tuple(surface.value for surface in Surface)
