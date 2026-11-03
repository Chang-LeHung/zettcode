"""What a plugin hands the agent: extensions, ready now or built when the agent is."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:  # pragma: no cover - annotations only, so the imports stay lazy
    from zett_agent.extensions.base import AgentExtension
    from zett_agent.model import AgentModel


@dataclass(frozen=True, slots=True)
class AgentBuild:
    """What exists when the agent is being built, and not before.

    A plugin activates while the shell is still being drawn, before any provider exists. An extension
    that needs one, or that is costly to import, is registered as a factory and called with this when
    the runtime builds the agent.

    Attributes:
        model: The provider the agent starts on.
    """

    model: AgentModel


#: Builds an extension once the agent is being built; ``None`` means this run has none to add.
ExtensionFactory: TypeAlias = Callable[[AgentBuild], "AgentExtension | None"]


@dataclass(frozen=True, slots=True)
class Contribution:
    """One ``zett-agent`` extension a plugin hands the agent: ready now, or built when the agent is.

    Attributes:
        name: The extension's name, known before it exists so that a clash is caught at load.
        extension: The extension itself, when it was registered whole.
        factory: What builds it, when it was registered as a factory.
    """

    name: str
    extension: AgentExtension | None = None
    factory: ExtensionFactory | None = None

    def build(self, build: AgentBuild | None) -> AgentExtension | None:
        """Return the extension, building it if it is a factory and the agent is being built.

        Args:
            build: What exists at build time; ``None`` outside a build, where a factory yields nothing.

        Raises:
            ValueError: When the factory built an extension under another name than it announced; the
                load-time clash check would have been checking the wrong name.
        """
        if self.extension is not None:
            return self.extension
        if build is None or self.factory is None:
            return None
        made = self.factory(build)
        if made is not None and made.name != self.name:
            raise ValueError(f"Extension registered as {self.name!r} was built as {made.name!r}")
        return made
