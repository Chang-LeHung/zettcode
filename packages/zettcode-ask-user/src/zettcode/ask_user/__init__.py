"""The ``ask_user`` tool of ZettCode: the plugin that hands it to the agent.

A part of the program that lives in a distribution of its own, found through the ``zettcode.plugin`` entry point.
``[ask_user] enabled`` in the configuration is what turns it off. The extension is imported by the factory, so a launch
that never builds an agent does not pay for it.
"""

from __future__ import annotations

from .plugin import AskUser

__all__ = ["AskUser"]
