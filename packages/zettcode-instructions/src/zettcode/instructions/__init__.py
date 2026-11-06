"""The workspace's ``AGENTS.md`` instructions of ZettCode: the plugin that hands them to the agent.

A part of the program that lives in a distribution of its own, found through the ``zettcode.plugin`` entry point.
``[agents_md] enabled`` in the configuration is what turns it off. The extension is imported by the factory, so a launch
that never builds an agent does not pay for it.
"""

from __future__ import annotations

from .plugin import ProjectInstructions

__all__ = ["ProjectInstructions"]
