"""Keep one request's tools to what the model behind it can actually use."""

from __future__ import annotations

from collections.abc import Mapping

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.model import AgentModel
from zett_agent.tools.images import view_image

from ...config import ModelConfig


class ModelCapabilities(AgentExtension):
    """Register only the tools the selected model can use.

    ``view_image`` reads a picture and hands it to the provider as an image
    part, which a text-only model rejects: offering it invites a call that
    cannot succeed. The tool list is rebuilt for every request and ``on_tool``
    finishes before any ``on_state``, so dropping it here also keeps prompt
    guidance from describing a tool the model does not have.

    The decision follows the model of the request being prepared, not the one
    selected when the runtime was built, so ``/model`` takes effect on the next
    turn without rebuilding the client.
    """

    #: After the coding bundle, which is what registers the tool being filtered.
    priority = 110

    def __init__(self, models: Mapping[ModelConfig, AgentModel]) -> None:
        """Remember the runtime's providers, keyed by the model each one serves.

        The mapping is the runtime's own and grows as models are selected, so
        this reads it rather than a copy taken at construction.
        """
        self._models = models

    async def on_tool(self, context: AgentRunContext) -> None:
        """Drop the image tool when this request's model does not take images."""
        model = next((entry for entry, provider in self._models.items() if provider is context.model), None)
        if model is not None and not model.multimodal:
            context.tools.pop(view_image.name, None)
