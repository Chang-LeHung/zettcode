"""``@`` references: resources a draft can pull into one message.

A mention is a token like ``@code-review`` typed in the composer. A provider
owns one kind of resource — the builtin one is skills — and both lists
candidates for the completion menu and expands a token into the text the model
should see. The draft the user typed stays the message that is stored and
shown; the expansion is carried as a message attribute, so a session loaded
later restores the original text instead of the injected resource.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from zett_agent.extensions.skill import SkillExtension

from ...config import ZettCodeConfig
from ..registry import Provider, Registry

#: One mention token: an ``@`` at a word boundary, then a lowercase name. The
#: lookbehind keeps an email address or a second ``@`` from matching.
MENTION = re.compile(r"(?<![\w@])@([a-z0-9][a-z0-9_-]*)")


@dataclass(frozen=True, slots=True)
class Mention:
    """One resource a draft can reference.

    Attributes:
        token: Text as typed, e.g. ``@code-review``.
        kind: Provider that owns the resource, e.g. ``"skill"``.
        name: Resource name without the ``@``.
        description: One line shown by the completion menu.
    """

    token: str
    kind: str
    name: str
    description: str


class MentionProvider(Provider[Mention], ABC):
    """One kind of ``@`` resource: what it offers and what it injects."""

    #: Short name shown in the completion menu's type column, e.g. ``"skill"``.
    kind: str

    @abstractmethod
    def candidates(self, query: str) -> Sequence[Mention]:
        """Return the resources whose name matches ``query`` (without the ``@``)."""

    @property
    def items(self) -> Sequence[Mention]:
        """Return every resource this provider offers."""
        return self.candidates("")

    @abstractmethod
    def expand(self, name: str) -> str | None:
        """Return the text one resource injects, or ``None`` when it is unknown."""


class MentionRegistry(Registry[Mention]):
    """The providers a draft is resolved against, in registration order."""

    def __init__(self, providers: Sequence[MentionProvider] = ()) -> None:
        """Keep the providers; the first to claim a name wins a duplicate."""
        super().__init__(providers)

    def candidates(self, query: str) -> tuple[Mention, ...]:
        """Return every resource whose token matches ``query`` (which has no ``@``)."""
        return tuple(mention for mention in self.items() if mention.name.startswith(query))

    @property
    def mention_providers(self) -> tuple[MentionProvider, ...]:
        """Return the providers as the ``@``-specific type that can expand tokens."""
        return tuple(provider for provider in self.providers if isinstance(provider, MentionProvider))

    def expand_token(self, token: str) -> str | None:
        """Resolve one typed ``@`` token into the text it contributes, if any.

        The shell gets the tokens from the composer's parts rather than scanning
        the draft, so this is handed ``"@name"`` exactly as it was written.
        """
        name = token[1:] if token.startswith("@") else token
        for provider in self.mention_providers:
            block = provider.expand(name)
            if block is not None:
                return block
        return None


class SkillMentions(MentionProvider):
    """Skills discovered from the configured roots, named for the model to load."""

    kind = "skill"

    def __init__(self, config: ZettCodeConfig) -> None:
        """Discover skills once, the same way the agent's skill extension does."""
        self._skills = {skill.name: skill for skill in SkillExtension(config.skill_search_roots()).skills}

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
