"""The ``@`` provider for skills."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from zett_agent.extensions.skill import SkillExtension

from zettcode.mention import Mention, MentionProvider


class SkillMentions(MentionProvider):
    """Skills discovered from the configured roots, named for the model to load."""

    kind = "skill"
    #: A skill is the more specific thing to mean when a repository holds a file of the same name, so it is asked
    #: ahead of the files whatever order the plugins were registered in (a session still goes first).
    precedence = -10

    def __init__(self, roots: Sequence[Path]) -> None:
        """Discover skills once, the same way the agent's skill extension does."""
        self._skills = {skill.name: skill for skill in SkillExtension(roots).skills}

    def candidates(self, query: str) -> Sequence[Mention]:
        """List the discovered skills whose name starts with ``query``."""
        return tuple(
            Mention(token=f"@{skill.name}", kind=self.kind, name=skill.name, description=skill.description)
            for skill in self._skills.values()
            if skill.name.startswith(query)
        )

    def expand(self, name: str) -> str | None:
        """Name the skill and leave loading its instructions to the model.

        The system prompt already catalogs every skill, and ``read_skill`` loads
        the file, so the message only has to say which one the user meant;
        inlining the body would spend context on instructions that may not be
        needed.
        """
        skill = self._skills.get(name)
        if skill is None:
            return None
        return (
            f'Use the "{skill.name}" skill: call read_skill(name="{skill.name}") '
            "if its instructions are useful and not already in context."
        )
