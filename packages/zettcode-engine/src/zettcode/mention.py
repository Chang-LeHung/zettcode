"""What an ``@`` reference is, and the shape a provider of them has.

The runtime resolves references against providers a plugin hands it (:class:`zettcode.engine.plugins.PluginContext`),
so the type is the engine's: a plugin that offers resources implements this, and the engine reads it without knowing
whether the resources are files, skills or other sessions. The implementations and the registry over them are
:mod:`zettcode.mentions`, which ships with the SDK.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from zettcode.registry import Provider, Registry

#: One mention token: an ``@`` at a word boundary, then a name. A name is what a
#: skill is called (lowercase words) or where a file lives (``src/app.py``), so it
#: holds path punctuation as well; it starts with a letter, a digit, or an
#: underscore, which is what keeps ``@/`` and a trailing ``@`` out. The lookbehind
#: keeps an email address or a second ``@`` from matching.
MENTION = re.compile(r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_./-]*)")


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

    def rename(self, name: str) -> str | None:
        """Return the words the model reads in place of ``@name``, or ``None`` to leave the token as typed.

        Most references are meaningful to the model as they are (a path, a skill's name). One that is not —
        the name of another session — is replaced, so the model is not left holding a word it must guess at.
        """
        return None


class MentionRegistry(Registry[Mention]):
    """The providers a draft is resolved against, in registration order."""

    def __init__(self, providers: Sequence[MentionProvider] = ()) -> None:
        """Keep the providers; the first to claim a name wins a duplicate."""
        super().__init__(providers)

    def candidates(self, query: str) -> tuple[Mention, ...]:
        """Return every resource whose name matches ``query`` (which has no ``@``).

        Each provider is asked for the query rather than handed every item it has:
        a draft is completed on every keystroke, and the file provider holds
        thousands of names it would otherwise build a ``Mention`` for each time.
        An earlier provider still wins a duplicate name.
        """
        seen: set[str] = set()
        merged: list[Mention] = []
        for provider in self.mention_providers:
            for mention in provider.candidates(query):
                if mention.name in seen:
                    continue
                seen.add(mention.name)
                merged.append(mention)
        return tuple(merged)

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

    def rename_token(self, token: str) -> str | None:
        """Return the words the model reads in place of one typed token, from the provider that owns it.

        The owner is the first provider that knows the name, which is the one :meth:`expand_token` asks:
        a session and a file with one name are the session.
        """
        name = token[1:] if token.startswith("@") else token
        for provider in self.mention_providers:
            if provider.expand(name) is not None:
                return provider.rename(name)
        return None
