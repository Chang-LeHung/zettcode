"""ZettCode's subagent profiles and the task tool the runtime registers."""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.extensions.subagent import SubAgentExtension
from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelRequest, ModelResponse, ReasoningEffort, RetryOptions

from zettcode.app.agent.extensions.capabilities import ModelCapabilities
from zettcode.app.agent.extensions.files import FileTools
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
    files = next(extension for extension in explore.extensions if isinstance(extension, FileTools))
    assert files.read_only is True
    # Reasoning has no tools at all.
    assert not any(isinstance(extension, FileTools) for extension in profiles["reasoning"].extensions)
    # Coding edits, but no child is offered shell; it has no approval channel.
    write = next(extension for extension in profiles["coding"].extensions if isinstance(extension, FileTools))
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


class _Provider:
    """One provider that serves a parent and its children, and records what every request asked for.

    A request that carries the ``task`` tool is the parent's: it delegates one explore task, then answers.
    Any other is a child's, and reports. ``ask`` is added to the task call's arguments.
    """

    retry = RetryOptions(max_retries=0)

    def __init__(self, ask: dict | None = None) -> None:
        self.ask = ask or {}
        self.requests: list[ModelRequest] = []

    @property
    def children(self) -> list[ModelRequest]:
        return [request for request in self.requests if "task" not in {tool.name for tool in request.tools}]

    @property
    def parents(self) -> list[ModelRequest]:
        return [request for request in self.requests if "task" in {tool.name for tool in request.tools}]

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        if "task" not in {tool.name for tool in request.tools}:
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="child report")))
            return
        if isinstance(request.messages[-1], ToolMessage):
            yield ModelEvent.completed(ModelResponse(AssistantMessage(content="parent done")))
            return
        arguments = {
            "description": "look around",
            "prompt": "where is the render loop?",
            "subagent_type": "explore",
            **self.ask,
        }
        yield ModelEvent.completed(ModelResponse(AssistantMessage(tool_calls=(ToolCall("call-1", "task", arguments),))))


async def _delegate(tmp_path, provider, *, efforts=(), stale=None):
    """Run one parent turn on ``provider``, whose extension was built with ``stale`` as its model."""
    store = _store(tmp_path)
    config = ModelConfig(model="m", token="t", multimodal=True, reasoning_efforts=tuple(efforts))
    capabilities = ModelCapabilities({config: provider})
    extension = subagent_extension(
        model=stale or _StubModel(),
        persistence=store,
        capabilities=capabilities,
    )
    parent = await Agent.create(
        provider,
        config=AgentRunConfig(session_id="parent"),
        extensions=[store, extension, ToolGuidelinesExtension()],
    )
    result = await parent.run("where is the render loop?")
    return store, result


async def test_the_task_tool_runs_an_explore_child_and_links_its_session(tmp_path):
    provider = _Provider()

    store, result = await _delegate(tmp_path, provider)

    assert result.content == "parent done"
    # The explore profile offers exactly the read-only filesystem tools.
    assert {tool.name for tool in provider.children[0].tools} == {"read", "glob", "grep"}
    child_ids = [session_id for session_id in store.session_ids() if session_id != "parent"]
    assert len(child_ids) == 1
    child = store.read(child_ids[0])
    assert child.parent_session_id == "parent"


class _Untouched(_StubModel):
    """The model the extension was *built* with; a child must never reach it."""

    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, request: ModelRequest):
        self.calls += 1
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content="wrong model")))


async def test_a_child_runs_on_the_model_its_parent_request_runs_on_not_the_one_the_runtime_was_built_with(tmp_path):
    """`/model` and resuming change the parent's model; the children had kept the first one."""
    provider = _Provider()
    built_with = _Untouched()

    await _delegate(tmp_path, provider, stale=built_with)

    assert built_with.calls == 0
    assert len(provider.children) == 1


@pytest.mark.parametrize(
    ("efforts", "sent"),
    [
        # The profile's own level (explore: low), for a model that takes everything.
        ((), ReasoningEffort.LOW),
        # A model that starts at medium: the profile's low is moved to the nearest it takes.
        ((ReasoningEffort.MEDIUM, ReasoningEffort.HIGH), ReasoningEffort.MEDIUM),
        ((ReasoningEffort.OFF, ReasoningEffort.HIGH), ReasoningEffort.OFF),
    ],
)
async def test_a_profiles_default_level_is_moved_to_one_the_model_takes(tmp_path, efforts, sent):
    provider = _Provider()

    await _delegate(tmp_path, provider, efforts=efforts)

    assert provider.children[0].reasoning_effort == sent


async def test_the_parent_model_can_ask_for_the_level_a_child_thinks_at(tmp_path):
    provider = _Provider(ask={"reasoning_effort": "high"})

    await _delegate(tmp_path, provider)

    assert provider.children[0].reasoning_effort == ReasoningEffort.HIGH


async def test_the_task_schema_offers_only_the_levels_the_parents_model_takes(tmp_path):
    provider = _Provider()
    taken = (ReasoningEffort.LOW, ReasoningEffort.HIGH)

    await _delegate(tmp_path, provider, efforts=taken)

    task = next(tool for tool in provider.parents[0].tools if tool.name == "task")
    offered = task.parameters["properties"]["reasoning_effort"]
    assert offered["enum"] == ["low", "high"]
    assert "reasoning_effort" not in task.parameters.get("required", ())


async def test_a_level_the_model_does_not_take_is_refused_and_the_child_never_starts(tmp_path):
    """The tool says why, in words the parent can act on; no child is spent on a request that would fail."""
    provider = _Provider(ask={"reasoning_effort": "ultra"})

    store, result = await _delegate(tmp_path, provider, efforts=(ReasoningEffort.LOW, ReasoningEffort.HIGH))

    assert result.content == "parent done"
    assert provider.children == []
    tool_message = provider.parents[1].messages[-1]
    assert "low, high" in tool_message.content
    assert [session_id for session_id in store.session_ids() if session_id != "parent"] == []


async def test_two_tasks_asking_for_different_levels_do_not_share_one(tmp_path):
    """The requested level rides a context variable, so parallel calls each keep their own."""
    import asyncio

    from zettcode.app.agent.extensions import subagents as module

    async def ask(level):
        token = module._REQUESTED_EFFORT.set(level)
        await asyncio.sleep(0)
        seen = module._REQUESTED_EFFORT.get()
        module._REQUESTED_EFFORT.reset(token)
        return seen

    assert await asyncio.gather(ask("low"), ask("high")) == ["low", "high"]
    assert module._REQUESTED_EFFORT.get() is None


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

    for tool in ("read", "glob", "grep"):
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


def test_a_coding_child_with_a_shell_is_told_it_works_under_the_users_permission_level(tmp_path):
    profile = _profiles(tmp_path, shell=True)["coding"]

    assert "Tools: read, write_file, edit and bash" in profile.system_prompt
    assert "permission level" in profile.system_prompt and "cannot start another subagent" in profile.system_prompt
    assert "cannot run commands" not in profile.system_prompt
    assert "glob" not in profile.system_prompt and "grep" not in profile.system_prompt.replace("rg, grep", "")
    assert "permission level" in profile.description and "cannot run commands" not in profile.description


def test_a_coding_child_with_a_shell_gets_its_file_tools_from_the_parent_and_not_from_its_own_list(tmp_path):
    with_shell = _profiles(tmp_path, shell=True)["coding"]
    without = _profiles(tmp_path)["coding"]

    assert not any(isinstance(extension, FileTools) for extension in with_shell.extensions)
    assert any(isinstance(extension, FileTools) for extension in without.extensions)


def test_only_the_coding_profile_takes_what_the_parent_has():
    from zettcode.app.agent.extensions.subagents import INHERITING

    assert INHERITING == {"coding"}


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
    await runtime_module.ZettCodeEngine.preview(config).start()
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
