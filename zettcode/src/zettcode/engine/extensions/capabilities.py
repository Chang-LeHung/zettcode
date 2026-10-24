"""Keep one request's tools to what the model behind it can actually use."""

from __future__ import annotations

from collections.abc import Mapping

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.model import AgentModel, ServerToolDefinition

from zettcode.config import ModelConfig


def web_search_tool(model: ModelConfig) -> ServerToolDefinition:
    """Return the hosted search tool to declare for ``model``.

    The type is the model's own ``web_search_name`` or the default for its API. Anthropic's wire schema also
    wants the tool's ``name``, which for a search is always ``web_search`` whatever its dated type.
    """
    configuration = {"name": "web_search"} if model.anthropic else {}
    return ServerToolDefinition(model.search_name, configuration)


class ModelCapabilities(AgentExtension):
    """Register only the tools the selected model can use.

    ``read`` hands a picture to the provider as an image part, which a text-only model rejects: such a model is
    given ``read_file``, the same reader without pictures, in its place. The tool list is rebuilt for every
    request and ``on_tool`` finishes before any ``on_state``, so swapping it here also keeps prompt guidance from
    describing a tool the model does not have.

    A model configured with ``web_search`` is also given the hosted search tool of its API. It is declared, not
    emulated: the endpoint runs the search and the model answers from the results.

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

    def config_of(self, provider: AgentModel | None) -> ModelConfig | None:
        """Return the configured model a provider serves, or ``None`` for one this runtime did not build."""
        if provider is None:
            return None
        return next((entry for entry, built in self._models.items() if built is provider), None)

    async def on_tool(self, context: AgentRunContext) -> None:
        """Swap the reader for a text-only model, and declare the search of a model that has one."""
        model = self.config_of(context.model)
        if model is None:
            return
        # Imported here: the file tools pull in the schema library, which the first frame never needs.
        from ..tools.files import read, read_file

        if not model.multimodal and context.tools.pop(read.name, None) is not None:
            context.register_tool(read_file)
        if model.web_search:
            context.register_server_tool(web_search_tool(model))
