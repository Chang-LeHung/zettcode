"""Named items merged from ordered providers.

The shell keeps two catalogs a plugin may extend: the composer's slash commands
and its ``@`` resources. Both merge the same way — providers in order, and the
first provider to claim a name owns it — so both are one :class:`Registry` over
one :class:`Provider` shape, and the builtins are providers like any other.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Generic, TypeVar

#: The kind of item a registry holds, such as a slash command.
Item = TypeVar("Item")


class Provider(Generic[Item], ABC):
    """One source of named items a registry merges."""

    @property
    @abstractmethod
    def items(self) -> Sequence[Item]:
        """Return the items this provider contributes, in display order."""


class Registry(Generic[Item]):
    """Merge providers in order; the first provider to claim a name owns it."""

    def __init__(self, providers: Sequence[Provider[Item]] = ()) -> None:
        """Start from the given providers, most trusted first."""
        self._providers = list(providers)

    def register(self, provider: Provider[Item]) -> Provider[Item]:
        """Append one provider and return it, for a caller that wants to keep it."""
        self._providers.append(provider)
        return provider

    @property
    def providers(self) -> tuple[Provider[Item], ...]:
        """Return the providers in order."""
        return tuple(self._providers)

    def items(self) -> tuple[Item, ...]:
        """Return the merged items, an earlier provider's name winning a clash."""
        seen: set[str] = set()
        merged: list[Item] = []
        for provider in self._providers:
            for item in provider.items:
                name = getattr(item, "name", None)
                if name is not None:
                    if name in seen:
                        continue
                    seen.add(name)
                merged.append(item)
        return tuple(merged)

    def find(self, name: str) -> Item | None:
        """Return the item with this name, or ``None`` when nothing claims it."""
        return next((item for item in self.items() if getattr(item, "name", None) == name), None)
