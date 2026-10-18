"""A scripted model, and a client wired to it, for driving the SDK through the real agent loop.

Nothing here fakes the agent: the runtime, the extensions, the tools, the session store and the permission policy are
the real ones. Only the provider is replaced, by a model that plays back what a test wrote down.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from zett_agent.messages import AssistantMessage, ToolCall
from zett_agent.model import ModelEvent, ModelRequest, ModelResponse, ModelUsage, RetryOptions
from zett_agent.stop import StopInfo, StopReason

from zettcode.app.agent import runtime as runtime_module
from zettcode.config import ModelConfig, ZettCodeConfig

Step = Union[  # noqa: UP007 - an alias evaluated at import time
    str,
    AssistantMessage,
    Exception,
    Callable[[ModelRequest], Union[str, AssistantMessage, Exception, Awaitable[object]]],  # noqa: UP007
]


def call(name: str, arguments: dict[str, object] | None = None, *, call_id: str | None = None) -> ToolCall:
    """Return a tool call the scripted model can ask for."""
    return ToolCall(
        id=call_id or f"call-{name}-{abs(hash((name, str(arguments)))) % 10_000}", name=name, arguments=arguments or {}
    )


def says(text: str) -> AssistantMessage:
    """Return a plain answer."""
    return AssistantMessage(content=text)


def asks_for(*calls: ToolCall, text: str = "") -> AssistantMessage:
    """Return a step in which the model calls tools."""
    return AssistantMessage(content=text, tool_calls=list(calls))


class ScriptedModel:
    """An ``AgentModel`` that answers each request with the next step it was given.

    A step is a string (an answer), an ``AssistantMessage`` (a tool call, say), an exception (raised from the
    stream), or a function of the request returning one of those, which may be async and may block on an event to
    hold a run open. The requests it saw are kept for the test to inspect.
    """

    retry = RetryOptions(max_retries=0)

    def __init__(self, *steps: Step, tokens: tuple[int, int] = (100, 20), chunk: int = 0) -> None:
        self.steps = list(steps)
        self.requests: list[ModelRequest] = []
        self.tokens = tokens
        self.chunk = chunk
        self.closed = False

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        step: object = self.steps.pop(0) if self.steps else "ok"
        if callable(step):
            step = step(request)
            if asyncio.iscoroutine(step):
                step = await step
        if isinstance(step, BaseException):
            raise step
        stop = None
        if isinstance(step, Stopped):
            step, stop = step.message, step.stop
        message = AssistantMessage(content=step) if isinstance(step, str) else step
        assert isinstance(message, AssistantMessage), message
        text = message.content if isinstance(message.content, str) else ""
        if text:
            size = self.chunk or len(text)
            for start in range(0, len(text), size):
                yield ModelEvent.text(text[start : start + size])
        usage = ModelUsage(input_tokens=self.tokens[0], output_tokens=self.tokens[1])
        yield ModelEvent.completed(ModelResponse(message, usage=usage, stop=stop))

    async def aclose(self) -> None:
        self.closed = True


@dataclass(frozen=True)
class Stopped:
    """A step the provider ended for a reason other than finishing; the stop rides on the response, not the message."""

    message: AssistantMessage
    stop: StopInfo


def refusal(text: str = "I can't help with that.") -> Stopped:
    """Return a step the provider ended with a refusal."""
    return Stopped(AssistantMessage(content=text), StopInfo(StopReason.REFUSAL, message="declined"))


def models(*names: str, multimodal: bool = False) -> tuple[ModelConfig, ...]:
    """Return model entries with throwaway tokens."""
    return tuple(ModelConfig(model=name, token="test-token", multimodal=multimodal) for name in names)


def wire(monkeypatch, model: ScriptedModel) -> ScriptedModel:
    """Make every provider the runtime builds this one scripted model."""
    monkeypatch.setattr(runtime_module, "_build_provider", lambda selected: model)
    return model


def config_for(tmp_path: Path, **changes: object) -> ZettCodeConfig:
    """Return a configuration that keeps everything inside ``tmp_path``."""
    workspace = tmp_path / "project"
    workspace.mkdir(exist_ok=True)
    values: dict[str, object] = {
        "workspace": workspace,
        "models": models("scripted"),
        "store": tmp_path / "sessions",
        "mcp_config": tmp_path / "absent-mcp.json",
        "mcp_enabled": False,
        "skills_enabled": False,
        "subagent_enabled": False,
        "sessions_enabled": False,
        "update_enabled": False,
        "agents_md_enabled": False,
    }
    values.update(changes)
    return ZettCodeConfig(**values)  # type: ignore[arg-type]
