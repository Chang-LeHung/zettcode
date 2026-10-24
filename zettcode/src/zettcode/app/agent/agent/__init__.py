"""The terminal's agent: the engine's agent, plus the commands and preferences only a terminal has.

The engine's agent (:class:`zettcode.engine.agent.ZettCodeAgent`) does the work. This subclass adds what the shell
asks of it that is not work: the slash commands and what plugins contributed (``commands``), and the theme, the pet
and the status line the reader can change (``settings``). Its engine is built with the terminal's plugin loader, so
the commands, palettes, pets, presenters and rows of the plugins are there to be read.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.agent import ZettCodeAgent
from zettcode.engine.core import PluginLoader, ZettCodeEngine

from .commands import CommandsMixin

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ZettCodeConfig
    from zettcode.sdk.client import Client

__all__ = ["TerminalAgent"]


def _terminal_loader() -> PluginLoader:
    """Return the terminal's plugin loader, imported when an agent is built and not before."""
    from zettcode.app.plugins.loader import terminal_plugins

    return terminal_plugins


class TerminalAgent(CommandsMixin, ZettCodeAgent):
    """The agent the terminal application drives."""

    _client: Client | None = None

    @property
    def client(self) -> Client:
        """Return the SDK client over this agent, which is how the shell reaches everything the SDK offers.

        Made on first use and then kept, so the shell and the commands it runs read the same client. The agent still
        owns closing: the client is a view of it.
        """
        if self._client is None:
            from zettcode.sdk.client import Client

            self._client = Client._around(self)
        return self._client

    @classmethod
    async def create(cls, config: ZettCodeConfig) -> TerminalAgent:
        """Build the engine with the terminal's plugins and start it."""
        return cls(await ZettCodeEngine.create(config, _terminal_loader()))

    @classmethod
    def preview(cls, config: ZettCodeConfig) -> TerminalAgent:
        """Wrap an engine that still has to start, built with the terminal's plugins, so the shell can paint first."""
        return cls(ZettCodeEngine.preview(config, _terminal_loader()))
