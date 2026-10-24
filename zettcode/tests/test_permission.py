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
from zettcode.app.agent.permission.sandbox import ShellSandbox


class _Sandbox(ShellSandbox):
    """A sandbox that is, or is not, there, without asking the machine: ``safe`` depends on which."""

    def __init__(self, available: bool) -> None:
        super().__init__(Path.cwd())
        self._probed = True
        self._available = available

    @property
    def available(self) -> bool:
        return self._available


def _policy(repo: Path, *, sandbox: bool, level: Permission = Permission.ASK) -> ShellPolicy:
    """A policy over a sandbox this machine does or does not have."""
    return ShellPolicy(level, repo, _Sandbox(sandbox))


class _AskedTheReader(Exception):
    """Raised by the fake context when a command reaches the approval prompt."""


class _Context:
    """The two things the approval extension touches before it asks the reader."""

    def __init__(self) -> None:
        self.config = SimpleNamespace(session_id="session-1")
        self.session_id = "session-1"
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
    assert [level.value for level in PERMISSION_LEVELS] == ["deny", "ask", "safe", "full"]


def test_a_level_is_parsed_by_name_and_a_wrong_name_lists_the_right_ones():
    assert parse_permission("  SAFE ") is Permission.SAFE
    assert parse_permission("full") is Permission.FULL
    with pytest.raises(ValueError, match="Try one of: deny, ask, safe, full"):
        parse_permission("yolo")


def test_auto_is_still_taken_as_the_old_name_of_full():
    """The level was called ``auto`` until ``safe`` became a sandbox; configs, scripts and the SDK still say so."""
    assert parse_permission("auto") is Permission.FULL
    assert parse_permission(" AUTO ") is Permission.FULL
    assert Permission.AUTO is Permission.FULL
    assert Permission.FULL.value == "full"


def test_the_configured_approval_mode_picks_the_starting_level():
    assert ShellPolicy.from_mode(ShellApprovalMode.REVIEW).level is Permission.ASK
    assert ShellPolicy.from_mode(ShellApprovalMode.ALLOW_ALL).level is Permission.FULL


def test_each_level_answers_whether_a_command_may_run_unasked_with_no_sandbox(repo: Path):
    """Where the machine has no sandbox, `safe` is what it was before one existed: reads run, the rest ask."""
    policy = _policy(repo, sandbox=False)
    answers = {}
    for level in PERMISSION_LEVELS:
        policy.level = level
        answers[level.value] = (policy.allows_unasked("git status"), policy.allows_unasked("rm -rf build"))

    assert answers == {
        "deny": (False, False),
        "ask": (False, False),
        "safe": (True, False),
        "full": (True, True),
    }


def test_with_a_sandbox_safe_lets_every_command_run_because_the_kernel_is_the_boundary(repo: Path):
    policy = _policy(repo, sandbox=True, level=Permission.SAFE)

    assert policy.sandboxed is True
    assert policy.allows_unasked("git status") is True
    assert policy.allows_unasked("rm -rf build") is True, (
        "it runs, inside a boundary that cannot reach past the workspace"
    )


def test_only_safe_is_ever_sandboxed_and_only_where_the_machine_has_one(repo: Path):
    with_one = _policy(repo, sandbox=True)
    without = _policy(repo, sandbox=False)
    seen = {}
    for level in PERMISSION_LEVELS:
        with_one.level = without.level = level
        seen[level.value] = (with_one.sandboxed, without.sandboxed)

    assert seen == {
        "deny": (False, False),
        "ask": (False, False),
        "safe": (True, False),
        "full": (False, False),
    }


def test_a_policy_with_no_workspace_has_no_sandbox_to_offer():
    policy = ShellPolicy(Permission.SAFE)

    assert policy.sandbox is None and policy.sandboxed is False
    assert policy.allows_unasked("ls") is True and policy.allows_unasked("rm x") is False


async def test_the_approval_memory_lets_the_level_skip_the_prompt(repo: Path):
    policy = _policy(repo, sandbox=False)
    memory = ShellApprovalMemory(policy)

    assert await memory.is_allowed("s", "ls") is False, "ask: nothing is allowed until it is approved"
    policy.level = Permission.SAFE
    assert await memory.is_allowed("s", "ls") is True
    assert await memory.is_allowed("s", "rm x") is False
    policy.level = Permission.FULL
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


async def test_ask_puts_a_command_to_the_reader_and_safe_and_full_do_not(repo: Path):
    """The real approval extension, driven through the real memory.

    The fake context raises when the extension emits its request, which is how the
    test knows the command reached the prompt without a prompt having to exist.
    """
    policy = _policy(repo, sandbox=False)
    approval = ShellApprovalExtension(ShellApprovalMemory(policy))

    assert await _ran(approval, "ls") == ["asked"], "ask"
    policy.level = Permission.SAFE
    assert await _ran(approval, "ls") == ["ls"], "safe without a sandbox: a read runs"
    assert await _ran(approval, "rm -rf build") == ["asked"], "safe without a sandbox: a write still asks"
    assert await _ran(approval, "ls; rm x") == ["asked"], "safe without a sandbox: a read chained to a write asks"
    policy.sandbox = _Sandbox(True)
    assert await _ran(approval, "rm -rf build") == ["rm -rf build"], "safe with a sandbox: the boundary decides"
    policy.level = Permission.FULL
    assert await _ran(approval, "rm -rf build") == ["rm -rf build"], "full"


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


@pytest.mark.parametrize("level", [Permission.ASK, Permission.SAFE, Permission.FULL])
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
    policy = _policy(repo, sandbox=False, level=Permission.ASK)
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


async def test_the_level_the_command_sets_is_the_one_object_the_guard_the_runtime_built_reads(tmp_path):
    """The guide's promise that `/permission` lands in a request already running: no copy in between.

    The guard is handed the runtime's own policy when the request is assembled, and ``use_permission``
    changes that policy's level in place, so the guard's next shell call sees it with no restart.
    """
    from zett_agent.messages import ToolCall

    from zettcode.app.agent.permission import SHELL_APPROVAL_TOOL_NAME
    from zettcode.app.agent.runtime import ZettCodeEngine
    from zettcode.config import ModelConfig, ZettCodeConfig

    config = ZettCodeConfig(
        workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "sessions", mcp_enabled=False
    )
    runtime = ZettCodeEngine.preview(config)
    guard = ShellDenyExtension(runtime.policy)  # exactly how the runtime builds it

    async def shell_call() -> str:
        async def through():
            return "ran"

        try:
            return await guard.on_tool_call(None, ToolCall("c", SHELL_APPROVAL_TOOL_NAME, {}), through)  # type: ignore[arg-type]
        except PermissionError:
            return "refused"

    assert await shell_call() == "ran"
    runtime.use_permission("deny")
    assert await shell_call() == "refused"
    runtime.use_permission("full")
    assert await shell_call() == "ran"
    runtime.use_permission("auto")
    assert runtime.permission is Permission.FULL, "the old name still sets the level"
    assert await shell_call() == "ran"


async def test_the_guard_the_runtime_really_hands_the_agent_reads_the_policy_the_command_changes(tmp_path, monkeypatch):
    """Not a copy of how the runtime builds it: the extension it actually passes to ``create_agent``."""
    from zettcode.app.agent import runtime as runtime_module
    from zettcode.config import ModelConfig, ZettCodeConfig

    given: list[list[object]] = []

    class FakeProvider:
        def __init__(self, model, token, *, base_url, response):
            pass

        async def aclose(self):
            pass

    async def fake_create_agent(model, **kwargs):
        given.append(list(kwargs["extensions"]))
        return type("FakeClient", (), {"event_dispatcher": None})()

    monkeypatch.setattr("zett_agent.providers.openai.OpenAIProvider", FakeProvider)
    monkeypatch.setattr("zett_agent.client.create_agent", fake_create_agent)
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    config = ZettCodeConfig(
        workspace=tmp_path, models=(ModelConfig(model="m", token="t"),), store=tmp_path / "sessions", mcp_enabled=False
    )
    runtime = runtime_module.ZettCodeEngine.preview(config)
    await runtime.start()

    (guard,) = [e for e in given[0] if isinstance(e, ShellDenyExtension)]

    assert guard._policy is runtime.policy
    runtime.use_permission("deny")
    assert guard._policy.level is Permission.DENY
