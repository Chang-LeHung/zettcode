"""Per-tool guidance in each tool's description: the plugin that hands the extension to the agent.

A part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point. The
extension itself stays in the engine (`zettcode.engine.extensions.guidance`), because every child agent the engine's
``task`` tool builds carries it, so the runtime needs the factory whether or not this part is installed.
"""

from __future__ import annotations

from .plugin import ToolGuidance

__all__ = ["ToolGuidance"]
