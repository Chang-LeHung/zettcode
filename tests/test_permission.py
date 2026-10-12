"""The shell permission levels: what each decides, and what enforces it."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from zett_agent.extensions.shell_approval import ShellApprovalExtension, ShellApprovalMode
from zett_agent.messages import ToolCall

from zettcode.app.agent.permission import (
    DENIED_MESSAGE,
    PERMISSION_LEVELS,
    Permission,
    ShellDenyExtension,
    ShellPolicy,
    parse_permission,
)
from zettcode.app.agent.permission.approval import ShellApprovalMemory


class _AskedTheReader(Exception):
    """Raised by the fake context when a command reaches the approval prompt."""


class _Context:
    """The two things the approval extension touches before it asks the reader."""

    def __init__(self) -> None:
        self.config = SimpleNamespace(session_id="session-1")
        self.asked: list[object] = []

    async def emit(self, event: object) -> None:
        self.asked.append(event)
        raise _AskedTheReader


def _call(command: str, tool: str = "bash") -> ToolCall:
    return ToolCall("call-1", tool, {"command": command})


async def _ran(extension, command: str, tool: str = "bash") -> list[str]:
    """Run one tool call through an extension and say what happened to it."""
    ran: list[str] = []
    context = _Context()

    async def call_next():
        ran.append(command)
        return "ok"

    try:
        await extension.on_tool_call(context, _call(command, tool), call_next)
    except _AskedTheReader:
        return ["asked"]
    except PermissionError as error:
        return ["denied", str(error)]
    return ran


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def test_there_are_four_levels_strictest_first():
    assert [level.value for level in PERMISSION_LEVELS] == ["deny", "ask", "safe", "auto"]


def test_a_level_is_parsed_by_name_and_a_wrong_name_lists_the_right_ones():
    assert parse_permission("  SAFE ") is Permission.SAFE
    with pytest.raises(ValueError, match="Try one of: deny, ask, safe, auto"):
        parse_permission("yolo")


def test_the_configured_approval_mode_picks_the_starting_level():
    assert ShellPolicy.from_mode(ShellApprovalMode.REVIEW).level is Permission.ASK
    assert ShellPolicy.from_mode(ShellApprovalMode.ALLOW_ALL).level is Permission.AUTO


def test_each_level_answers_whether_a_command_may_run_unasked(repo: Path):
    policy = ShellPolicy(workspace=repo)
    answers = {}
    for level in PERMISSION_LEVELS:
        policy.level = level
        answers[level.value] = (policy.allows_unasked("git status"), policy.allows_unasked("rm -rf build"))

    assert answers == {
        "deny": (False, False),
        "ask": (False, False),
        "safe": (True, False),
        "auto": (True, True),
    }


async def test_the_approval_memory_lets_the_level_skip_the_prompt(repo: Path):
    policy = ShellPolicy(workspace=repo)
    memory = ShellApprovalMemory(policy)

    assert await memory.is_allowed("s", "ls") is False, "ask: nothing is allowed until it is approved"
    policy.level = Permission.SAFE
    assert await memory.is_allowed("s", "ls") is True
    assert await memory.is_allowed("s", "rm x") is False
    policy.level = Permission.AUTO
    assert await memory.is_allowed("s", "rm x") is True


async def test_a_command_approved_by_hand_stays_approved_whatever_the_level():
    """`p` remembers an exact command; going stricter than auto does not forget it."""
    policy = ShellPolicy()
    memory = ShellApprovalMemory(policy)
    await memory.allow_command("pytest -q")

    assert await memory.is_allowed("s", "pytest -q") is True
    assert await memory.is_allowed("s", "pytest -x") is False


async def test_without_a_policy_the_memory_behaves_as_it_did_before_levels():
    memory = ShellApprovalMemory()

    assert await memory.is_allowed("s", "ls") is False
    await memory.allow_command("ls")
    assert await memory.is_allowed("s", "ls") is True


async def test_ask_puts_a_command_to_the_reader_and_safe_and_auto_do_not(repo: Path):
    """The real approval extension, driven through the real memory.

    The fake context raises when the extension emits its request, which is how the
    test knows the command reached the prompt without a prompt having to exist.
    """
    policy = ShellPolicy(workspace=repo)
    approval = ShellApprovalExtension(ShellApprovalMemory(policy))

    assert await _ran(approval, "ls") == ["asked"], "ask"
    policy.level = Permission.SAFE
    assert await _ran(approval, "ls") == ["ls"], "safe: a read runs"
    assert await _ran(approval, "rm -rf build") == ["asked"], "safe: a write still asks"
    assert await _ran(approval, "ls; rm x") == ["asked"], "safe: a read chained to a write still asks"
    policy.level = Permission.AUTO
    assert await _ran(approval, "rm -rf build") == ["rm -rf build"], "auto"


async def test_deny_refuses_a_shell_command_and_tells_the_model_why():
    policy = ShellPolicy(Permission.DENY)
    deny = ShellDenyExtension(policy)

    outcome = await _ran(deny, "ls")

    assert outcome == ["denied", DENIED_MESSAGE]
    assert "permission: deny" in DENIED_MESSAGE
    assert "file tools" in DENIED_MESSAGE, "the model is told what is still open to it"


async def test_deny_leaves_every_other_tool_alone():
    deny = ShellDenyExtension(ShellPolicy(Permission.DENY))

    assert await _ran(deny, "x", tool="read_file") == ["x"]
    assert await _ran(deny, "x", tool="replace_in_file") == ["x"]


@pytest.mark.parametrize("level", [Permission.ASK, Permission.SAFE, Permission.AUTO])
async def test_only_deny_refuses(level: Permission):
    deny = ShellDenyExtension(ShellPolicy(level))

    assert await _ran(deny, "ls") == ["ls"]


async def test_a_command_remembered_by_hand_does_not_get_past_deny():
    """Deny is the strictest level: what the reader once approved does not override it."""
    policy = ShellPolicy(Permission.DENY)
    memory = ShellApprovalMemory(policy)
    await memory.allow_command("ls")
    chain = ShellDenyExtension(policy)

    assert await memory.is_allowed("s", "ls") is True, "the memory still remembers it"
    assert (await _ran(chain, "ls"))[0] == "denied", "and the deny layer runs before the memory is asked"


async def test_a_change_of_level_applies_to_the_next_command_in_flight(repo: Path):
    """The level is read at each shell call, not when a request starts."""
    policy = ShellPolicy(Permission.ASK, repo)
    deny = ShellDenyExtension(policy)
    approval = ShellApprovalExtension(ShellApprovalMemory(policy))

    assert await _ran(approval, "ls") == ["asked"]
    policy.level = Permission.DENY
    assert (await _ran(deny, "ls"))[0] == "denied"
    policy.level = Permission.SAFE
    assert await _ran(deny, "ls") == ["ls"]
    assert await _ran(approval, "ls") == ["ls"]


def test_the_deny_layer_runs_before_the_approval_layer():
    """If the reader's prompt came first, `deny` would put a panel up and then refuse."""
    policy = ShellPolicy()

    assert ShellDenyExtension(policy).priority < ShellApprovalExtension().priority
