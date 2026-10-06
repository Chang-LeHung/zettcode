"""ZettCode's subagent profiles and the task tool the runtime registers."""

from __future__ import annotations

from pathlib import Path

from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.extensions.file_system import FileSystemExtension
from zett_agent.extensions.subagent import SubAgentExtension
from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelRequest, ModelResponse, RetryOptions

from zettcode.app.agent.capabilities import ModelCapabilities
from zettcode.app.agent.storage import SessionStore
from zettcode.app.agent.subagents import ZettCodeSubAgents, build_subagents


class _StubModel:
    """A model the profile tests never run; only its identity matters."""

    retry = RetryOptions(max_retries=0)

    async def stream(self, request: ModelRequest):
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content="unused")))


def _store(tmp_path: Path) -> SessionStore:
    """Return a session store rooted in the test's temporary directory."""
    return SessionStore(tmp_path)


def test_subagent_profiles_split_the_tools_by_what_a_child_may_touch(tmp_path):
    store = _store(tmp_path)
    definitions = build_subagents(
        model=_StubModel(),
        persistence=store,
        capabilities=ModelCapabilities({}),
    )
    profiles = {definition.name: definition for definition in definitions}

    assert set(profiles) == {"explore", "reasoning", "coding"}
    # Exploration reads and searches, but never writes or runs anything.
    explore = profiles["explore"]
    files = next(extension for extension in explore.extensions if isinstance(extension, FileSystemExtension))
    assert files.read_only is True
    # Reasoning has no tools at all.
    assert not any(isinstance(extension, FileSystemExtension) for extension in profiles["reasoning"].extensions)
    # Coding edits, but no child is offered shell; it has no approval channel.
    write = next(extension for extension in profiles["coding"].extensions if isinstance(extension, FileSystemExtension))
    assert write.read_only is False
    assert "run_shell" not in {tool.name for tool in write.tools}
    # Every child writes its own log into this application's store.
    for definition in definitions:
        assert store in definition.extensions


def test_no_subagent_profile_can_delegate_to_another(tmp_path):
    """A child has no ``task`` tool, so delegation cannot recurse."""
    definitions = build_subagents(
        model=_StubModel(),
        persistence=_store(tmp_path),
        capabilities=ModelCapabilities({}),
    )

    for definition in definitions:
        assert not any(isinstance(extension, SubAgentExtension) for extension in definition.extensions)


class _ParentModel:
    """Delegate one explore task, then answer with the child's report."""

    retry = RetryOptions(max_retries=0)

    async def stream(self, request: ModelRequest):
        if isinstance(request.messages[-1], ToolMessage):
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="parent done")))
            return
        yield ModelEvent.completed(
            ModelResponse(
                AssistantMessage(
                    tool_calls=(
                        ToolCall(
                            "call-1",
                            "task",
                            {
                                "description": "look around",
                                "prompt": "where is the render loop?",
                                "subagent_type": "explore",
                            },
                        ),
                    )
                )
            )
        )


class _ChildModel:
    """Record the tools the child was offered, then report."""

    retry = RetryOptions(max_retries=0)
    seen_tools: set[str] = set()

    async def stream(self, request: ModelRequest):
        _ChildModel.seen_tools = {tool.name for tool in request.tools}
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content="child report")))


async def test_the_task_tool_runs_an_explore_child_and_links_its_session(tmp_path):
    store = _store(tmp_path)
    extension = ZettCodeSubAgents(
        model=_ChildModel(),
        persistence=store,
        capabilities=ModelCapabilities({}),
    )
    parent = await Agent.create(
        _ParentModel(),
        config=AgentRunConfig(session_id="parent"),
        extensions=[store, extension, ToolGuidelinesExtension()],
    )

    result = await parent.run("where is the render loop?")

    assert result.content == "parent done"
    # The explore profile offers exactly the read-only filesystem tools.
    assert _ChildModel.seen_tools == {"read_file", "view_image", "glob", "grep"}
    child_ids = [session_id for session_id in store.session_ids() if session_id != "parent"]
    assert len(child_ids) == 1
    child = store.read(child_ids[0])
    assert child.parent_session_id == "parent"
