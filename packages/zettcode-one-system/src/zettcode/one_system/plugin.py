"""The plugin that hands the agent the one-system-message hook."""

from __future__ import annotations

from typing import TYPE_CHECKING

from zettcode.engine.plugins.context import PluginContext
from zettcode.engine.plugins.plugin import Plugin

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zett_agent.extensions.base import AgentExtension

    from zettcode.engine.plugins.state import AgentBuild


class OneSystem(Plugin[PluginContext]):
    """Every instruction in one system message, for the endpoints that take one and for the ones that take many.

    The merge runs once per request, at the point the provider would see the messages, so it covers the instructions a
    part added for that request as well as the ones the agent carries everywhere. It changes nothing a model reads — the
    same text, in the same order, separated by the blank line the Anthropic-compatible provider already used between
    them — and it is off for `[plugins] disable = ["one-system"]` like any other part.
    """

    name = "one-system"
    description = "All instructions the model is given in one system message"

    def activate(self, ctx: PluginContext) -> None:
        """Register the extension as a factory: it is built with the agent, not while the first frame is drawn."""

        # Imported in the factory: the extension imports the framework's message and hook types, which a launch that
        # never builds an agent does not need.
        def build(_: AgentBuild) -> AgentExtension:
            from .extension import OneSystemMessage

            return OneSystemMessage()

        ctx.agent.register_extension_factory("OneSystemMessage", build)
