"""Host every application plugin inside one ``zett-agent`` extension.

Plugins are this application's own concept; the agent only knows extensions. A
single host is registered instead of one adapter per plugin, so the application
keeps one place to grow plugin-wide behaviour — ordering, shared state, loading
and unloading — without changing how the agent sees the bundle. The host
forwards every lifecycle hook to each plugin in priority order.
"""

from __future__ import annotations

from contextlib import aclosing
from typing import TYPE_CHECKING, cast

from zett_agent.extensions.base import AgentExtension

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from collections.abc import AsyncGenerator, AsyncIterator, Sequence

    from zett_agent.agent import AgentRunConfig, AgentRunContext
    from zett_agent.extensions.base import ModelRequestNext, ToolCallNext
    from zett_agent.extensions.events import ExtensionEvent
    from zett_agent.extensions.external import ExternalEvent
    from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage
    from zett_agent.model import ModelEvent, ModelRequest, ModelResponse
    from zett_agent.tools.base import ToolResult

    from .plugin import Plugin

#: Default priority of the host when it carries no plugins; the same band as the
#: built-in extensions, so an empty bundle changes nothing.
DEFAULT_PRIORITY = 100


class PluginExtension(AgentExtension):
    """One extension that drives every installed plugin.

    ``plugins`` holds the plugins in priority order: lower first, equal
    priorities in load order. The host fans each hook out in that order and
    nests the model and tool middleware with it — the first plugin is the
    outermost wrapper, exactly as if the plugins were separate extensions.

    The host takes the earliest priority any plugin asked for, so a plugin that
    needs to observe before a built-in still can. The whole bundle moves with
    it, and the plugins' order among themselves stays their own.
    """

    def __init__(self, plugins: Sequence[Plugin]) -> None:
        """Keep the plugins in hook order and adopt their earliest priority."""
        self.plugins = tuple(sorted(plugins, key=lambda plugin: plugin.priority))
        self.name = "plugins"
        self.priority = min((plugin.priority for plugin in self.plugins), default=DEFAULT_PRIORITY)

    # -- setup -------------------------------------------------------------

    async def on_tool(self, context: AgentRunContext) -> None:
        for plugin in self.plugins:
            await plugin.on_tool(context)

    async def on_state(self, context: AgentRunContext) -> None:
        for plugin in self.plugins:
            await plugin.on_state(context)

    async def on_message(self, context: AgentRunContext) -> None:
        for plugin in self.plugins:
            await plugin.on_message(context)

    # -- run ---------------------------------------------------------------

    async def before_run(self, context: AgentRunContext) -> None:
        for plugin in self.plugins:
            await plugin.before_run(context)

    async def after_run(self, context: AgentRunContext, result: AssistantMessage) -> None:
        for plugin in self.plugins:
            await plugin.after_run(context, result)

    async def on_success(self, context: AgentRunContext, result: AssistantMessage) -> None:
        for plugin in self.plugins:
            await plugin.on_success(context, result)

    async def on_error(self, context: AgentRunContext, error: Exception) -> None:
        for plugin in self.plugins:
            await plugin.on_error(context, error)

    # -- turn --------------------------------------------------------------

    async def before_turn(self, context: AgentRunContext) -> None:
        for plugin in self.plugins:
            await plugin.before_turn(context)

    async def after_turn(self, context: AgentRunContext, result: AssistantMessage) -> None:
        for plugin in self.plugins:
            await plugin.after_turn(context, result)

    # -- model -------------------------------------------------------------

    async def before_model(self, context: AgentRunContext, request: ModelRequest) -> None:
        for plugin in self.plugins:
            await plugin.before_model(context, request)

    async def after_model(self, context: AgentRunContext, response: ModelResponse) -> None:
        for plugin in self.plugins:
            await plugin.after_model(context, response)

    # -- tools -------------------------------------------------------------

    async def before_tool(self, context: AgentRunContext, call: ToolCall) -> None:
        for plugin in self.plugins:
            await plugin.before_tool(context, call)

    async def after_tool(
        self,
        context: AgentRunContext,
        call: ToolCall,
        result: ToolMessage,
        error: Exception | None,
    ) -> None:
        for plugin in self.plugins:
            await plugin.after_tool(context, call, result, error)

    # -- maintenance and events -------------------------------------------

    async def on_compact(self, context: AgentRunContext) -> None:
        for plugin in self.plugins:
            await plugin.on_compact(context)

    def accept(self, config: AgentRunConfig | None, event: ExternalEvent) -> bool:
        """Offer the event to every plugin; accepted when any of them claims it.

        Every plugin is asked even after one accepts — the agent broadcasts to
        all of them, and a plugin must not lose an event to another's answer.
        """
        answers = [plugin.accept(config, event) for plugin in self.plugins]
        return any(answers)

    async def on_event(self, context: AgentRunContext, event: ExtensionEvent) -> None:
        for plugin in self.plugins:
            await plugin.on_event(context, event)

    # -- middleware --------------------------------------------------------

    async def on_model_request(
        self,
        context: AgentRunContext,
        request: ModelRequest,
        call_next: ModelRequestNext,
    ) -> AsyncIterator[ModelEvent]:
        """Nest the plugins around the provider stream, first plugin outermost."""

        async def run(index: int, current: ModelRequest) -> AsyncIterator[ModelEvent]:
            if index >= len(self.plugins):
                # ``call_next`` is typed as AsyncIterator; only the provider
                # stream behind it can actually be closed, so cast for aclosing.
                stream = cast("AsyncGenerator[ModelEvent]", call_next(current))
                async with aclosing(stream) as events:
                    async for event in events:
                        yield event
                return
            plugin = self.plugins[index]
            async for event in plugin.on_model_request(context, current, lambda request: run(index + 1, request)):
                yield event

        async for event in run(0, request):
            yield event

    async def on_tool_call(
        self,
        context: AgentRunContext,
        call: ToolCall,
        call_next: ToolCallNext,
    ) -> ToolResult:
        """Nest the plugins around the tool handler, first plugin outermost."""

        async def run(index: int) -> ToolResult:
            if index >= len(self.plugins):
                return await call_next()
            return await self.plugins[index].on_tool_call(context, call, lambda: run(index + 1))

        return await run(0)
