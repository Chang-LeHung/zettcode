"""The skills of ZettCode: the ``@`` provider that offers them to the composer, and the extension that lists them for
the model and lets it read one.

A part of the program that lives in a distribution of its own, found through the ``zettcode.agent`` entry point and
activated with the agent's other parts. ``[skills] enabled`` in the configuration is what turns it off.
"""

from __future__ import annotations

from .mentions import SkillMentions
from .plugin import SkillResources, SkillTool

__all__ = ["SkillMentions", "SkillResources", "SkillTool"]
