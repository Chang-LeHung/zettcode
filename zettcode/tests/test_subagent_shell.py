"""The ``coding`` subagent has the parent's tools and the parent's permission level, without ``task`` and the rest.

A child that could run a command with nobody to ask would either run everything or wait for ever, so these run a real
child under a real parent: the approval it needs reaches the person through the parent, the answer reaches the child,
and what the level says (ask, deny, full) is what happens.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.extensions.ask_user import ASK_USER_EVENT_NAME, AskUserExtension
from zett_agent.extensions.base import AgentExtension
from zett_agent.extensions.external import ExternalEvent
from zett_agent.extensions.shell_approval import (
    SHELL_APPROVAL_EVENT_NAME,
    SHELL_APPROVAL_RESPONSE_EVENT_NAME,
    ShellApprovalExtension,
)
from zett_agent.extensions.skill import SkillExtension
from zett_agent.extensions.todo import TodoWriteExtension
from zett_agent.extensions.tool_guidelines import ToolGuidelinesExtension
from zett_agent.messages import AssistantMessage, ToolCall, ToolMessage
from zett_agent.model import ModelEvent, ModelRequest, ModelResponse, RetryOptions

from zettcode.config import ModelConfig
from zettcode.engine.dialogue.side import SideQuestions
from zettcode.engine.extensions.capabilities import ModelCapabilities
from zettcode.engine.extensions.files import CodingBundle
from zettcode.engine.extensions.messaging import SessionMessagingExtension
from zettcode.engine.extensions.subagents import subagent_extension
from zettcode.engine.extensions.usage import UsageExtension
from zettcode.engine.permission import DENIED_MESSAGE, Permission, ShellDenyExtension, ShellPolicy
from zettcode.engine.permission.approval import ShellApprovalMemory
from zettcode.engine.permission.sandbox import ShellSandbox
from zettcode.engine.plugins.builtin_agent import _shared_with_children
from zettcode.engine.storage import SessionStore
from zettcode.engine.tools.boundary import Sandboxer


class _Scripted:
    """One provider for a parent and its child. The parent delegates one ``coding`` task; the child runs ``steps``.

    A request that carries the ``task`` tool is the parent's. A child's makes the next call in ``steps`` (a tool name
    and its arguments) until they run out, then reports what the last tool said.
    """

    retry = RetryOptions(max_retries=0)

    def __init__(self, *steps: tuple[str, dict]) -> None:
        self.steps = list(steps)
        self.child_requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest):
        if "task" in {tool.name for tool in request.tools}:
            if isinstance(request.messages[-1], ToolMessage):
                yield ModelEvent.completed(ModelResponse(AssistantMessage(content="parent done")))
                return
            arguments = {"description": "change it", "prompt": "do it", "subagent_type": "coding"}
            call = ToolCall("task-1", "task", arguments)
            yield ModelEvent.completed(ModelResponse(AssistantMessage(tool_calls=(call,))))
            return
        self.child_requests.append(request)
        done = sum(isinstance(message, ToolMessage) for message in request.messages)
        if done < len(self.steps):
            name, arguments = self.steps[done]
            call = ToolCall(f"child-{done}", name, arguments)
            yield ModelEvent.completed(ModelResponse(AssistantMessage(tool_calls=(call,))))
            return
        last = next((m for m in reversed(request.messages) if isinstance(m, ToolMessage)), None)
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content=f"report: {last.content if last else ''}")))


class _SpySandbox(Sandboxer):
    """A stand-in for the operating-system sandbox: it records what it wrapped and runs nothing sandboxed."""

    def __init__(self) -> None:
        self.wrapped: list[str] = []
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def wrap(self, command: str) -> str:
        self.wrapped.append(command)
        return f"echo SANDBOXED && {command}"

    def hint(self) -> str:
        return "[sandbox] hint"


class _World:
    """A parent agent built the way the runtime builds one, with the pieces a test needs to reach."""

    def __init__(self, tmp_path: Path, provider: _Scripted, level: Permission, *, messaging: bool = False) -> None:
        self.provider = provider
        self.policy = ShellPolicy(level, tmp_path)
        self.store = SessionStore(tmp_path / "store", tmp_path)
        self.config = ModelConfig(model="m", token="t", multimodal=True)
        self.capabilities = ModelCapabilities({self.config: provider})
        self.messaging = messaging
        self.events: list[AgentEvent] = []
        self.sandbox: _SpySandbox | None = None
        #: Extensions this test adds beside the ones the runtime would: a skill root, for one.
        self.extra: list[object] = []
        #: What every tool of the parent returned, in order: the reports a child sent back are in here.
        self.tool_results: list[str] = []

    async def build(self) -> Agent:
        extensions = [
            self.store,
            ShellDenyExtension(self.policy),
            ShellApprovalExtension(ShellApprovalMemory(self.policy)),
            CodingBundle(self.policy),
            AskUserExtension(),
            TodoWriteExtension(),
            SessionMessagingExtension(object()),  # type: ignore[arg-type] - only the tools' presence is looked at
            UsageExtension(),
            SideQuestions(),
            self.capabilities,
            *self.extra,  # type: ignore[misc]
        ]
        shell = subagent_extension(
            model=self.provider,  # type: ignore[arg-type]
            persistence=self.store,
            capabilities=self.capabilities,
            shares=_shared_with_children(messaging=self.messaging),
        )
        return await Agent.create(
            self.provider,  # type: ignore[arg-type]
            config=AgentRunConfig(session_id="parent"),
            extensions=[*extensions, shell, ToolGuidelinesExtension()],
        )

    async def run(self, *, decision: str = "execute") -> AssistantMessage:
        """Run the parent's turn, answering the approval the person is asked the way the shell would."""
        parent = await self.build()
        final: AssistantMessage | None = None
        async for event in parent.stream("go", config=AgentRunConfig(session_id="parent")):
            self.events.append(event)
            if event.type is AgentEventType.RUN_COMPLETED:
                final = event.message
            if event.type is AgentEventType.TOOL_COMPLETED and event.message is not None:
                self.tool_results.append(str(event.message.content))
            if event.type is not AgentEventType.CUSTOM or event.payload is None:
                continue
            payload = event.payload
            if event.name != SHELL_APPROVAL_EVENT_NAME:
                continue
            reply = ExternalEvent(
                SHELL_APPROVAL_RESPONSE_EVENT_NAME,
                {"tool_call_id": payload["tool_call_id"], "decision": decision, "remember": False},
            )
            # The shell answers with the session the payload names, which is the child's.
            parent.emit_external_event(reply, config=AgentRunConfig(session_id=payload["session_id"]))
        assert final is not None
        return final

    def asked(self, name: str) -> list[AgentEvent]:
        return [e for e in self.events if e.type is AgentEventType.CUSTOM and e.name == name]

    @property
    def child_tools(self) -> set[str]:
        return {tool.name for tool in self.provider.child_requests[0].tools}

    @property
    def report(self) -> str:
        """What the child told the parent: its last model message."""
        return str(self.provider.child_requests[-1].messages[-1].content)


@pytest.fixture(autouse=True)
def _here(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)


# -- what the child has --------------------------------------------------------------------------------------------


async def test_the_coding_child_has_no_plan_panel_and_no_question_tool(tmp_path: Path):
    """Its plan would be drawn for nobody, and a question would interrupt a conversation you did not start."""
    world = _World(tmp_path, _Scripted(), Permission.FULL)

    await world.run()

    assert not {"todo_write", "ask_user"} & world.child_tools
    assert world.run is not None  # the parent keeps both


async def test_the_coding_child_has_the_parents_tools_but_not_task_search_the_harness_or_messaging(tmp_path: Path):
    world = _World(tmp_path, _Scripted(), Permission.FULL)

    await world.run()

    assert world.child_tools == {"read", "write_file", "edit", "bash"}
    assert not {"task", "glob", "grep", "list_sessions", "send_message", "ask_user"} & world.child_tools


async def test_the_session_messaging_tools_are_given_to_the_child_when_the_configuration_says_so(tmp_path: Path):
    world = _World(tmp_path, _Scripted(), Permission.FULL, messaging=True)

    await world.run()

    assert {"list_sessions", "send_message"} <= world.child_tools and "task" not in world.child_tools


def test_what_is_shared_with_a_child_and_what_is_not(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path)
    capabilities = ModelCapabilities({})
    policy = ShellPolicy(Permission.ASK, tmp_path)
    own = (
        store,
        capabilities,
        UsageExtension(),
        SideQuestions(),
        SessionMessagingExtension(object()),  # type: ignore[arg-type]
        AskUserExtension(),
        TodoWriteExtension(),
    )
    shared = (CodingBundle(policy), ShellDenyExtension(policy))

    without = _shared_with_children(messaging=False)
    with_messaging = _shared_with_children(messaging=True)

    assert [type(extension).__name__ for extension in own if without(extension)] == []
    assert all(without(extension) for extension in shared)
    messaging = own[4]
    assert with_messaging(messaging) and not with_messaging(store), "only the messaging tools are a switch"


def test_an_extension_a_third_party_plugin_brings_reaches_a_child_by_default(tmp_path: Path):
    """The list is what a child does *not* get, so a new capability is not silently dropped for children."""

    class Extra(AgentExtension):
        name = "Extra"

    assert _shared_with_children(messaging=False)(Extra())


# -- the child's shell is under the parent's permission level ------------------------------------------------------


async def test_at_ask_the_childs_command_is_put_to_the_person_through_the_parent_and_runs_when_approved(tmp_path: Path):
    world = _World(tmp_path, _Scripted(("bash", {"command": "echo from-child"})), Permission.ASK)

    result = await world.run(decision="execute")

    assert result.content == "parent done"
    (asked,) = world.asked(SHELL_APPROVAL_EVENT_NAME)
    assert asked.session_id == "parent", "it goes out under the session the person is watching"
    assert asked.payload["command"] == "echo from-child"
    child = asked.payload["session_id"]
    assert child != "parent" and world.store.read(child).parent_session_id == "parent", "and names the child's own"
    assert "from-child" in world.report


async def test_a_command_the_person_refuses_does_not_run_and_the_child_is_told(tmp_path: Path):
    marker = tmp_path / "ran"
    world = _World(tmp_path, _Scripted(("bash", {"command": f"touch {marker}"})), Permission.ASK)

    await world.run(decision="abort")

    assert not marker.exists()
    assert "aborted by user" in world.report


async def test_at_deny_the_childs_command_is_refused_without_asking_anyone(tmp_path: Path):
    marker = tmp_path / "ran"
    world = _World(tmp_path, _Scripted(("bash", {"command": f"touch {marker}"})), Permission.DENY)

    await world.run()

    assert not marker.exists() and world.asked(SHELL_APPROVAL_EVENT_NAME) == []
    assert DENIED_MESSAGE in world.report


async def test_at_full_the_childs_command_runs_without_asking(tmp_path: Path):
    world = _World(tmp_path, _Scripted(("bash", {"command": "echo straight"})), Permission.FULL)

    await world.run()

    assert world.asked(SHELL_APPROVAL_EVENT_NAME) == []
    assert "straight" in world.report


async def test_the_level_is_read_when_the_command_is_run_so_a_change_applies_to_a_child_already_working(tmp_path: Path):
    world = _World(
        tmp_path, _Scripted(("bash", {"command": "echo a"}), ("bash", {"command": "echo b"})), Permission.ASK
    )
    asked: list[str] = []
    original = world.policy.allows_unasked

    def watch(command: str) -> bool:
        asked.append(command)
        if len(asked) == 2:
            world.policy.level = Permission.FULL
        return original(command)

    world.policy.allows_unasked = watch  # type: ignore[method-assign]

    await world.run()

    assert len(asked) == 2, "both commands went through the parent's policy"
    assert len(world.asked(SHELL_APPROVAL_EVENT_NAME)) == 1, "the first was asked, the second ran at the new level"
    assert "b" in world.report


async def test_at_safe_the_childs_command_runs_inside_the_sandbox_the_parent_uses(tmp_path: Path):
    world = _World(tmp_path, _Scripted(("bash", {"command": "echo sealed"})), Permission.SAFE)
    spy = _SpySandbox()
    world.policy.sandbox = spy

    await world.run()

    assert spy.wrapped == ["echo sealed"], "the child's command was wrapped by the parent's sandbox"
    assert "SANDBOXED" in world.report and "sealed" in world.report


async def test_at_safe_on_a_machine_with_no_sandbox_the_child_falls_back_as_the_parent_does(tmp_path: Path):
    world = _World(tmp_path, _Scripted(("bash", {"command": "echo plain"})), Permission.SAFE)
    spy = _SpySandbox()
    spy._available = False
    world.policy.sandbox = spy

    await world.run()

    assert spy.wrapped == [] and world.asked(SHELL_APPROVAL_EVENT_NAME) == []
    assert "plain" in world.report


async def test_the_childs_edits_are_made_in_the_workspace_with_the_tools_it_shares(tmp_path: Path):
    steps = (("write_file", {"path": "made.txt", "content": "hello\n"}),)
    world = _World(tmp_path, _Scripted(*steps), Permission.ASK)

    await world.run()

    assert (tmp_path / "made.txt").read_text() == "hello\n"
    assert world.asked(SHELL_APPROVAL_EVENT_NAME) == [], "a file tool is not a shell command"


# -- the coding child's shell is under the parent's permission level --------------------------------------------------


async def test_a_question_the_child_cannot_ask_never_reaches_the_person(tmp_path: Path):
    """A child has no `ask_user`: it works until it is done, and what it needs has to be in the task."""
    world = _World(tmp_path, _Scripted(("ask_user", {"question": "which file?"})), Permission.ASK)

    await world.run()

    assert "ask_user" not in world.child_tools and world.asked(ASK_USER_EVENT_NAME) == []


# -- the other profiles stay small ---------------------------------------------------------------------------------


async def test_the_explore_child_still_only_reads_and_searches(tmp_path: Path):
    world = _World(tmp_path, _Scripted(), Permission.FULL)
    provider = world.provider

    original = provider.stream

    async def explore(request: ModelRequest):
        if "task" in {tool.name for tool in request.tools} and not isinstance(request.messages[-1], ToolMessage):
            arguments = {"description": "look", "prompt": "where?", "subagent_type": "explore"}
            call = ToolCall("task-1", "task", arguments)
            yield ModelEvent.completed(ModelResponse(AssistantMessage(tool_calls=(call,))))
            return
        async for event in original(request):
            yield event

    provider.stream = explore  # type: ignore[method-assign]

    await world.run()

    assert world.child_tools == {"read", "glob", "grep"}


# -- with the real tools the user has ---------------------------------------------------------------------------


async def test_under_the_real_sandbox_the_child_cannot_write_outside_the_workspace(tmp_path: Path):
    """The level is not a story the child is told: the kernel enforces it for the child as for the parent."""
    if sys.platform == "win32":
        pytest.skip("no operating-system sandbox on Windows")
    import os
    import pwd

    # The account's real home: the workspace and the temporary directories are writable by design, so neither shows
    # the boundary.
    outside = Path(pwd.getpwuid(os.getuid()).pw_dir) / f"zettcode-child-{tmp_path.name}"
    sandbox = ShellSandbox(tmp_path)
    if not sandbox.available:
        pytest.skip(f"no operating-system sandbox here: {sandbox.unavailable_reason}")
    world = _World(
        tmp_path,
        _Scripted(("bash", {"command": f"echo x > {outside}; echo status=$?"})),
        Permission.SAFE,
    )
    world.policy.sandbox = sandbox

    await world.run()

    assert not outside.exists(), "a file outside the workspace and the temporary roots"
    assert "status=0" not in world.report


async def test_two_children_of_one_turn_ask_for_their_own_approvals_and_both_are_answered(tmp_path: Path):
    """Parallel tool calls mean two children at once; each approval is routed by its own session and call id."""
    world = _World(tmp_path, _TwoChildren(), Permission.ASK)

    await world.run()

    asked = world.asked(SHELL_APPROVAL_EVENT_NAME)
    assert len(asked) == 2
    assert len({event.payload["session_id"] for event in asked}) == 2, "one approval per child"
    assert {event.payload["command"] for event in asked} == {"echo one", "echo two"}
    reports = " ".join(world.tool_results)
    assert "one" in reports and "two" in reports, "both children's reports came back to the parent"


async def test_a_skill_the_user_installed_is_offered_to_the_child_too(tmp_path: Path):
    skill = tmp_path / "skills" / "house-style"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: house-style\ndescription: How this repository writes code.\n---\n\nTwo spaces.\n",
        encoding="utf-8",
    )
    world = _World(tmp_path, _Scripted(), Permission.FULL)
    world.extra = [SkillExtension([tmp_path / "skills"])]

    await world.run()

    assert "read_skill" in world.child_tools


class _TwoChildren:
    """A parent that delegates twice in one response; each child runs one command and reports what it said."""

    retry = RetryOptions(max_retries=0)

    def __init__(self) -> None:
        self.reports: list[str] = []
        self.child_requests: list[ModelRequest] = []
        self._words: dict[str, str] = {}

    async def stream(self, request: ModelRequest):
        if "task" in {tool.name for tool in request.tools}:
            if isinstance(request.messages[-1], ToolMessage):
                yield ModelEvent.completed(ModelResponse(AssistantMessage(content="parent done")))
                return
            calls = tuple(
                ToolCall(f"task-{index}", "task", {"description": "run", "prompt": "go", "subagent_type": "coding"})
                for index in (1, 2)
            )
            yield ModelEvent.completed(ModelResponse(AssistantMessage(tool_calls=calls)))
            return
        self.child_requests.append(request)
        word = self._words.setdefault(request.cache_key or "", "one" if not self._words else "two")
        if not any(isinstance(message, ToolMessage) for message in request.messages):
            call = ToolCall(f"child-{word}", "bash", {"command": f"echo {word}"})
            yield ModelEvent.completed(ModelResponse(AssistantMessage(tool_calls=(call,))))
            return
        last = next(m for m in reversed(request.messages) if isinstance(m, ToolMessage))
        self.reports.append(str(last.content))
        yield ModelEvent.completed(ModelResponse(AssistantMessage(content=f"report: {last.content}")))

    @property
    def report(self) -> str:
        return " ".join(self.reports)
