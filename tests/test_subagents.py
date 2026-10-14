"""ZettCode's subagent profiles and the task tool the runtime registers."""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.extensions.file_system import FileSystemExtension
from zett_agent.extensions.subagent import SubAgentExtension
from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelRequest, ModelResponse, RetryOptions

from zettcode.app.agent.extensions.capabilities import ModelCapabilities
from zettcode.app.agent.extensions.subagents import build_subagents, subagent_extension
from zettcode.app.agent.storage import SessionStore
from zettcode.config import ModelConfig


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
    assert "bash" not in {tool.name for tool in write.tools}
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
    extension = subagent_extension(
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


# -- what a child is given, and what its parent is told about it --------------------------------------------


def _profiles(tmp_path, **kwargs):
    definitions = build_subagents(
        model=_StubModel(),
        persistence=_store(tmp_path),
        capabilities=ModelCapabilities({}),
        **kwargs,
    )
    return {definition.name: definition for definition in definitions}


def test_a_child_may_keep_working_well_past_what_the_frameworks_own_default_allowed(tmp_path):
    """A child exploring or editing a real codebase makes dozens of calls; 18 ended it with half a report."""
    from zettcode.config import DEFAULT_SUBAGENT_MAX_ITERATIONS

    profiles = _profiles(tmp_path)

    assert DEFAULT_SUBAGENT_MAX_ITERATIONS >= 200
    assert {definition.max_iterations for definition in profiles.values()} == {DEFAULT_SUBAGENT_MAX_ITERATIONS}


def test_the_iteration_budget_is_the_one_that_was_asked_for(tmp_path):
    profiles = _profiles(tmp_path, max_iterations=40)

    assert {definition.max_iterations for definition in profiles.values()} == {40}


def test_a_child_is_given_the_projects_own_instructions(tmp_path):
    """A child that edits files without the project's rules is the one most in need of them."""
    from zett_agent.extensions.agents_md import AgentsMdExtension

    profiles = _profiles(tmp_path, workspace=tmp_path)

    for definition in profiles.values():
        agents_md = [e for e in definition.extensions if isinstance(e, AgentsMdExtension)]
        assert len(agents_md) == 1, definition.name
        assert agents_md[0].directory == tmp_path


def test_each_child_reads_the_instructions_for_itself(tmp_path):
    """One extension shared by three profiles would be one object on three requests."""
    profiles = _profiles(tmp_path, workspace=tmp_path)

    seen = [
        id(extension)
        for definition in profiles.values()
        for extension in definition.extensions
        if type(extension).__name__ == "AgentsMdExtension"
    ]

    assert len(set(seen)) == len(profiles)


def test_with_no_workspace_a_child_is_given_no_project_instructions(tmp_path):
    from zett_agent.extensions.agents_md import AgentsMdExtension

    profiles = _profiles(tmp_path)

    assert not any(isinstance(e, AgentsMdExtension) for d in profiles.values() for e in d.extensions)


@pytest.mark.parametrize("name", ["explore", "reasoning", "coding"])
def test_every_prompt_says_the_report_is_all_the_parent_gets(tmp_path, name):
    prompt = _profiles(tmp_path)[name].system_prompt

    assert "the final message you write is the only thing it receives" in prompt
    assert "do not talk to the user" in prompt.lower()


def test_the_explore_prompt_names_its_tools_and_asks_for_evidence_with_locations(tmp_path):
    prompt = _profiles(tmp_path)["explore"].system_prompt

    for tool in ("read_file", "view_image", "glob", "grep"):
        assert tool in prompt
    assert "path:line" in prompt and "cannot change files or run commands" in prompt


def test_the_reasoning_prompt_says_it_has_no_tools_and_must_not_invent_facts(tmp_path):
    prompt = _profiles(tmp_path)["reasoning"].system_prompt

    assert "have no tools" in prompt and "instead of assuming" in prompt


def test_the_coding_prompt_says_it_cannot_run_commands_and_the_parent_will(tmp_path):
    prompt = _profiles(tmp_path)["coding"].system_prompt

    assert "You cannot run commands, not even tests or a formatter" in prompt
    assert "The parent runs them" in prompt
    assert "smallest change" in prompt and "Do not refactor" in prompt


@pytest.mark.parametrize("name", ["explore", "reasoning", "coding"])
def test_every_description_tells_the_parent_what_its_prompt_must_carry(tmp_path, name):
    description = _profiles(tmp_path)[name].description

    assert description and description[0].islower(), "the framework puts it in a sentence"
    assert len(description) > 80, "a one-line description is what made the parent delegate badly"


def test_the_explore_description_says_the_child_sees_none_of_the_conversation(tmp_path):
    assert "sees none of this conversation" in _profiles(tmp_path)["explore"].description


def test_the_coding_description_says_the_parent_runs_the_checks(tmp_path):
    description = _profiles(tmp_path)["coding"].description

    assert "cannot run commands" in description and "run the tests" in description


def test_the_reasoning_description_says_it_can_read_nothing(tmp_path):
    assert "can read nothing" in _profiles(tmp_path)["reasoning"].description


class _FakeProvider:
    def __init__(self, model, token, *, base_url, response):
        pass

    async def aclose(self):
        pass


async def _started_extensions(tmp_path, monkeypatch, **settings):
    """Start a real runtime with the client stubbed, and return the extensions it handed the agent."""
    from zettcode.app.agent import runtime as runtime_module
    from zettcode.config import ZettCodeConfig

    given: list[list[object]] = []

    async def fake_create_agent(model, **kwargs):
        given.append(list(kwargs["extensions"]))
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", _FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_enabled=False,
        **settings,
    )
    await runtime_module.ZettCodeRuntime.preview(config).start()
    return given[0]


async def test_the_runtime_hands_its_children_the_workspace_and_the_configured_budget(tmp_path, monkeypatch):
    """The wiring, through the runtime's own build: what the shell's settings actually reach."""
    from zett_agent.extensions.agents_md import AgentsMdExtension

    extensions = await _started_extensions(tmp_path, monkeypatch, subagent_max_iterations=77)

    (task,) = [e for e in extensions if isinstance(e, SubAgentExtension)]
    profiles = list(task._configured_subagents.values())
    assert {profile.max_iterations for profile in profiles} == {77}
    for profile in profiles:
        assert any(isinstance(e, AgentsMdExtension) for e in profile.extensions), profile.name


async def test_a_workspace_that_switched_project_instructions_off_gives_its_children_none(tmp_path, monkeypatch):
    from zett_agent.extensions.agents_md import AgentsMdExtension

    extensions = await _started_extensions(tmp_path, monkeypatch, agents_md_enabled=False)

    (task,) = [e for e in extensions if isinstance(e, SubAgentExtension)]
    assert not any(isinstance(e, AgentsMdExtension) for p in task._configured_subagents.values() for e in p.extensions)


def test_the_configured_budget_must_be_a_positive_whole_number(tmp_path):
    from zettcode.config import load_config

    path = tmp_path / "c.toml"
    for bad in (0, -3):
        path.write_text(f'[[models]]\nmodel = "m"\ntoken = "t"\n[harness]\nsubagent_max_iterations = {bad}\n')
        with pytest.raises(ValueError, match="must be positive"):
            load_config(tmp_path, path=path)
    for bad in ("true", '"many"', "2.5"):
        path.write_text(f'[[models]]\nmodel = "m"\ntoken = "t"\n[harness]\nsubagent_max_iterations = {bad}\n')
        with pytest.raises(ValueError, match="subagent_max_iterations"):
            load_config(tmp_path, path=path)


def test_the_budget_is_read_from_the_harness_table_and_defaults_when_absent(tmp_path):
    from zettcode.config import DEFAULT_SUBAGENT_MAX_ITERATIONS, load_config

    path = tmp_path / "c.toml"
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n[harness]\nsubagent_max_iterations = 64\n')
    assert load_config(tmp_path, path=path).subagent_max_iterations == 64
    path.write_text('[[models]]\nmodel = "m"\ntoken = "t"\n')
    assert load_config(tmp_path, path=path).subagent_max_iterations == DEFAULT_SUBAGENT_MAX_ITERATIONS
