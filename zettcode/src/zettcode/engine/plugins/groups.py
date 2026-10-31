"""The group a plugin registers everything a front end shares into.

``ctx.agent`` is the one group every process has: an extension the model runs, a model provider, a kind of ``@``
resource, or an object other parts look up. The context keeps the registries; this is the name a plugin writes, and the
place a later addition lands — so the context does not grow a method per feature.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.providers import Provider

    from .context import PluginContext
    from .state import Contribution, ExtensionFactory

_T = TypeVar("_T")


class AgentGroups:
    """What every front end has: the agent's own extensions, providers, ``@`` resources and services.

    Args:
        context: The context these registrations accumulate in.
    """

    def __init__(self, context: PluginContext) -> None:
        self._context = context

    @property
    def extensions(self) -> tuple[Contribution, ...]:
        """Return the extensions registered so far, in registration order."""
        return self._context.extensions

    @property
    def mentions(self) -> tuple[object, ...]:
        """Return the ``@`` resource providers registered so far."""
        return tuple(self._context.mentions)

    @property
    def providers(self) -> tuple[object, ...]:
        """Return the model providers registered so far, in registration order."""
        return tuple(self._context.providers)

    def register_extension(self, extension: AgentExtension) -> AgentExtension:
        """Hand the agent one extension of the plugin's own."""
        return self._context.register_extension(extension)

    def register_extension_factory(self, name: str, factory: ExtensionFactory) -> None:
        """Hand the agent an extension built when the agent is built, not when the plugin activates."""
        return self._context.register_extension_factory(name, factory)

    def register_provider(self, provider: Provider) -> Provider:
        """Describe a host models can be reached at, so ``/config`` offers it."""
        return self._context.register_provider(provider)

    def register_mention(self, provider: object) -> object:
        """Register one kind of ``@`` resource the composer can offer."""
        return self._context.register_mention(provider)  # type: ignore[arg-type]

    def provide(self, name: str, service: object) -> object:
        """Make an object findable by name, for other parts of the application."""
        return self._context.provide(name, service)

    def service(self, name: str, kind: type[_T]) -> _T:
        """Return the object available under ``name``, checked to be a ``kind``."""
        return self._context.service(name, kind)

    def find(self, name: str, kind: type[_T]) -> _T | None:
        """Return the object under ``name``, or ``None`` when there is none."""
        return self._context.find(name, kind)
