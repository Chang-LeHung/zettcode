"""The terminal's agent: the engine's agent, plus the commands and preferences only a terminal has.

The engine's agent (:class:`zettcode.engine.agent.ZettCodeAgent`) does the work. This subclass adds what the shell
asks of it that is not work: the slash commands and what plugins contributed (``commands``), and the theme, the pet
and the status line the reader can change (``settings``).
"""

from __future__ import annotations

from zettcode.engine.agent import ZettCodeAgent

from .commands import CommandsMixin

__all__ = ["TerminalAgent"]


class TerminalAgent(CommandsMixin, ZettCodeAgent):
    """The agent the terminal application drives."""
