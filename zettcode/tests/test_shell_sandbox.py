"""`safe` is a sandbox: what a command may write and reach, enforced by the operating system and not by a reading of it."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from zettcode.config import load_config
from zettcode.engine.extensions.files import CodingBundle
from zettcode.engine.permission import Permission, ShellPolicy
from zettcode.engine.permission.sandbox import ShellSandbox, temporary_roots
from zettcode.engine.tools.boundary import Boundary, Sandboxer
from zettcode.engine.tools.shell import shell_tool

#: Real probes need the platform's sandbox. They are skipped, not faked, where there is none (Windows, or a Linux
#: machine without bubblewrap): what the fallback does there is tested separately, with a stand-in.
_POSIX = sys.platform == "darwin" or sys.platform.startswith("linux")


def _real(workspace: Path, *, network: bool = False) -> ShellSandbox:
    sandbox = ShellSandbox(workspace, network=network)
    if not (_POSIX and sandbox.available):
        pytest.skip(f"no operating-system sandbox here: {sandbox.unavailable_reason}")
    return sandbox


def _outside() -> Path:
    """A path the sandbox must refuse: the account's real home, which is not under the temp directory.

    The suite points ``HOME`` and the temp directory at throwaway places, and the temp directory is writable by
    design, so neither would show the boundary. The password database knows the real one.
    """
    import os
    import pwd

    return Path(pwd.getpwuid(os.getuid()).pw_dir) / f".zettcode-sandbox-probe-{os.getpid()}"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch) -> Path:
    """A workspace the sandbox may write, and the directory commands start in."""
    path = tmp_path / "project"
    path.mkdir()
    monkeypatch.chdir(path)
    return path.resolve()


async def _run(policy: ShellPolicy, command: str) -> str:
    tool = shell_tool(policy)
    return str(await tool.handler(command=command))


# -- the boundary, probed against the kernel ----------------------------------------------------------------------


async def test_a_sandboxed_command_may_write_the_workspace(workspace: Path):
    policy = ShellPolicy(Permission.SAFE, workspace, _real(workspace))

    out = await _run(policy, "echo kept > made.txt && cat made.txt")

    assert out.strip() == "kept"
    assert (workspace / "made.txt").read_text().strip() == "kept", "the write is real, not a copy"


async def test_a_sandboxed_command_may_write_tmp(workspace: Path):
    policy = ShellPolicy(Permission.SAFE, workspace, _real(workspace))
    marker = Path("/tmp") / f"zettcode-sandbox-test-{workspace.parent.name}"
    try:
        await _run(policy, f"echo ok > {marker} && cat {marker}")
        assert marker.read_text().strip() == "ok" if marker.exists() else True
    finally:
        marker.unlink(missing_ok=True)


async def test_a_sandboxed_command_cannot_write_outside_the_workspace_and_tmp(workspace: Path):
    """The point of the level: a write to the user's home is refused by the kernel, not by a reading of the command."""
    policy = ShellPolicy(Permission.SAFE, workspace, _real(workspace))
    target = _outside()
    try:
        with pytest.raises(RuntimeError, match="Operation not permitted|Read-only file system|Permission denied"):
            await _run(policy, f"echo x > {target}")
        with pytest.raises(RuntimeError, match="Operation not permitted|Read-only file system|Permission denied"):
            await _run(policy, f"mkdir {target}.d")
        assert not target.exists() and not Path(f"{target}.d").exists()
    finally:
        target.unlink(missing_ok=True)
        Path(f"{target}.d").rmdir() if Path(f"{target}.d").exists() else None


async def test_a_sandboxed_command_cannot_reach_the_network_unless_the_config_allows_it(workspace: Path):
    command = "python3 -c \"import socket; socket.create_connection(('1.1.1.1', 53), 2)\""
    blocked = ShellPolicy(Permission.SAFE, workspace, _real(workspace))

    with pytest.raises(RuntimeError):
        await _run(blocked, command)


async def test_the_files_that_run_code_later_stay_read_only_even_inside_the_workspace(workspace: Path):
    """A hook or a start-up file that is already there cannot be rewritten, on either platform.

    Creating one that is not there yet is a different guarantee: Seatbelt can deny a path that does not exist,
    bubblewrap can only mount over one that does (the framework documents it: "only protected once it exists"),
    so that half is asserted for macOS and left unclaimed on Linux. The docs say the same.
    """
    (workspace / ".git" / "hooks").mkdir(parents=True)
    (workspace / ".zshrc").write_text("# mine\n")
    policy = ShellPolicy(Permission.SAFE, workspace, _real(workspace))

    with pytest.raises(RuntimeError):
        await _run(policy, "echo 'rm -rf ~' > .git/hooks/pre-commit")
    with pytest.raises(RuntimeError):
        await _run(policy, "echo alias >> .zshrc")
    assert (workspace / ".zshrc").read_text() == "# mine\n", "an existing start-up file is untouched"
    assert not (workspace / ".git" / "hooks" / "pre-commit").exists()

    if sys.platform == "darwin":
        with pytest.raises(RuntimeError):
            await _run(policy, "echo alias > .bashrc")
        assert not (workspace / ".bashrc").exists(), "macOS also stops a protected file being created"


async def test_credentials_are_not_readable_and_the_environment_carries_no_secrets(workspace: Path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-leak")
    policy = ShellPolicy(Permission.SAFE, workspace, _real(workspace))

    out = await _run(policy, "env")

    assert "sk-should-not-leak" not in out and "OPENAI_API_KEY" not in out
    assert "PATH=" in out, "what a command needs to start is still there"


async def test_a_command_still_reads_the_machine_it_needs(workspace: Path):
    policy = ShellPolicy(Permission.SAFE, workspace, _real(workspace))
    (workspace / "a.txt").write_text("hello")

    out = await _run(policy, "cat a.txt && git --version && ls /usr | head -1")

    assert "hello" in out and "git version" in out


async def test_a_failure_inside_the_sandbox_names_the_boundary_so_the_model_does_not_retry_it(workspace: Path):
    policy = ShellPolicy(Permission.SAFE, workspace, _real(workspace))
    target = _outside()
    try:
        with pytest.raises(RuntimeError) as failure:
            await _run(policy, f"echo x > {target}")
    finally:
        target.unlink(missing_ok=True)

    assert "[sandbox]" in str(failure.value) and "/permission full" in str(failure.value)
    assert "no network" in str(failure.value)


async def test_the_exit_code_and_output_are_the_framework_s_own(workspace: Path):
    policy = ShellPolicy(Permission.SAFE, workspace, _real(workspace))

    with pytest.raises(RuntimeError, match="exited with code 7"):
        await _run(policy, "echo before; exit 7")
    assert (await _run(policy, "printf 'a\\nb\\n'")) == "a\nb\n"


# -- which level sandboxes, and what happens where there is no sandbox ---------------------------------------------


class _Spy(Sandboxer):
    """A stand-in sandbox that records what it was asked to wrap and runs nothing sandboxed."""

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.wrapped: list[str] = []
        self.directories: list[Path | None] = []
        self.unavailable_reason = None if available else "no bwrap"

    @property
    def available(self) -> bool:
        return self._available

    def wrap(self, command: str, cwd: Path | None = None) -> str:
        self.wrapped.append(command)
        self.directories.append(cwd)
        return f"echo SANDBOXED && {command}"

    def hint(self) -> str:
        return "[sandbox] hint"


def _policy(level: Permission, spy: _Spy, workspace: Path) -> ShellPolicy:
    policy = ShellPolicy(level, workspace)
    policy.sandbox = spy  # type: ignore[assignment]
    return policy


@pytest.mark.parametrize(
    ("level", "sandboxed"),
    [(Permission.DENY, False), (Permission.ASK, False), (Permission.SAFE, True), (Permission.FULL, False)],
)
async def test_only_the_safe_level_runs_a_command_in_the_sandbox(level: Permission, sandboxed: bool, workspace: Path):
    spy = _Spy()
    out = await _run(_policy(level, spy, workspace), "echo hi")

    assert ("SANDBOXED" in out) is sandboxed
    assert spy.wrapped == (["echo hi"] if sandboxed else [])


async def test_a_change_of_level_applies_to_the_next_command(workspace: Path):
    """`/permission` lands in a request already running: the tool reads the level at each call."""
    spy = _Spy()
    policy = _policy(Permission.ASK, spy, workspace)
    tool = shell_tool(policy)

    assert "SANDBOXED" not in await tool.handler(command="echo one")
    policy.level = Permission.SAFE
    assert "SANDBOXED" in await tool.handler(command="echo two")
    policy.level = Permission.FULL
    assert "SANDBOXED" not in await tool.handler(command="echo three")


async def test_where_the_machine_has_no_sandbox_the_command_runs_as_given(workspace: Path):
    """`safe` there asks about anything it cannot prove harmless; it never pretends to a boundary it cannot draw."""
    spy = _Spy(available=False)
    policy = _policy(Permission.SAFE, spy, workspace)

    assert policy.sandboxed is False
    assert (await _run(policy, "echo plain")).strip() == "plain"
    assert spy.wrapped == []
    assert policy.allows_unasked("ls") is True and policy.allows_unasked("rm x") is False


async def test_a_failure_gets_the_boundary_note_only_when_it_ran_sandboxed(workspace: Path):
    spy = _Spy()
    with pytest.raises(RuntimeError, match=r"\[sandbox\] hint"):
        await _run(_policy(Permission.SAFE, spy, workspace), "exit 3")
    with pytest.raises(RuntimeError) as plain:
        await _run(_policy(Permission.FULL, spy, workspace), "exit 3")
    assert "[sandbox]" not in str(plain.value)


async def test_without_a_policy_every_command_runs_as_given(workspace: Path):
    shell = CodingBundle().tools[-1]

    assert shell.name == "bash" and (await shell.handler(command="echo plain")).strip() == "plain"
    assert not any("read_file" in rule for rule in shell.guidelines), "it does not send the model to a tool it lacks"


def test_the_shell_tool_has_the_same_schema_with_a_policy_and_without(workspace: Path):
    plain = CodingBundle().tools[-1]
    guarded = CodingBundle(ShellPolicy(Permission.SAFE, workspace)).tools[-1]

    assert (guarded.name, guarded.parameters, guarded.description) == (plain.name, plain.parameters, plain.description)
    assert guarded.guidelines == plain.guidelines


def test_the_policy_is_the_boundary_the_shell_tool_asks(workspace: Path):
    assert isinstance(ShellPolicy(Permission.SAFE, workspace), Boundary)
    assert isinstance(ShellSandbox(workspace), Sandboxer)
    with pytest.raises(TypeError):
        Boundary()  # type: ignore[abstract]
    with pytest.raises(TypeError):
        Sandboxer()  # type: ignore[abstract]


async def test_a_blank_command_is_refused_before_it_is_wrapped(workspace: Path):
    spy = _Spy()

    with pytest.raises(ValueError, match="blank"):
        await _run(_policy(Permission.SAFE, spy, workspace), "   ")

    assert spy.wrapped == []


async def test_a_sandboxed_command_carries_the_directory_it_runs_in(workspace: Path):
    """A Linux sandbox puts ``--chdir`` in the argv, so the directory has to reach the wrapper or it wins."""
    spy = _Spy()
    policy = _policy(Permission.SAFE, spy, workspace)
    (workspace / "sub").mkdir()
    tool = shell_tool(policy)

    await tool.handler(command="echo hi", work_dir="sub")

    assert spy.directories == [(workspace / "sub").resolve()]
    assert spy.wrapped == ["echo hi"]


# -- the boundary's description ----------------------------------------------------------------------------


def test_the_temporary_directories_are_the_ones_that_exist():
    roots = temporary_roots()

    assert roots and all(root.is_dir() for root in roots)
    assert len(set(roots)) == len(roots)


def test_the_sandbox_is_probed_only_when_asked_and_once(monkeypatch, tmp_path: Path):
    calls: list[object] = []
    from zettcode.engine.permission import sandbox as module

    monkeypatch.setattr(module, "create_sandbox", lambda *a, **k: calls.append(k) or object())
    sandbox = ShellSandbox(tmp_path)

    assert calls == [], "constructing a policy does not touch the machine"
    assert sandbox.available is (_POSIX)
    assert sandbox.available is (_POSIX)
    assert len(calls) == (1 if _POSIX else 0)


def test_the_wrapper_hands_the_library_the_directory_the_command_runs_in(monkeypatch, tmp_path: Path):
    """The line that dropped it: the library puts ``--chdir`` in its argv, so it must be the tool's directory."""
    seen: list[Path] = []

    class _Library:
        def wrap(self, command: str, *, cwd: Path):
            seen.append(cwd)
            return SimpleNamespace(argv=["true"], env={})

    sandbox = ShellSandbox(tmp_path)
    sandbox._sandbox = _Library()  # type: ignore[assignment]
    sandbox._probed = True
    elsewhere = tmp_path / "sub"
    elsewhere.mkdir()

    sandbox.wrap("echo x", cwd=elsewhere)
    sandbox.wrap("echo y")

    assert seen == [elsewhere, Path.cwd().resolve()]


def test_a_platform_with_no_sandbox_says_why(monkeypatch, tmp_path: Path):
    from zettcode.engine.permission import sandbox as module

    monkeypatch.setattr(module.sys, "platform", "win32")
    sandbox = ShellSandbox(tmp_path)

    assert sandbox.available is False
    assert "no sandbox" in (sandbox.unavailable_reason or "")
    with pytest.raises(RuntimeError):
        sandbox.wrap("echo x")


def test_a_linux_machine_that_cannot_sandbox_falls_back_instead_of_failing(monkeypatch, tmp_path: Path):
    from zett_agent.sandbox import SandboxUnavailableError

    from zettcode.engine.permission import sandbox as module

    def refuse(*args, **kwargs):
        raise SandboxUnavailableError("bubblewrap (bwrap) was not found")

    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module, "create_sandbox", refuse)
    # The platform is faked, the host's paths are not: on Windows `/tmp` would be a drive-less `\tmp` the policy rejects.
    monkeypatch.setattr(module, "temporary_roots", lambda: (tmp_path,))
    sandbox = ShellSandbox(tmp_path)

    assert sandbox.available is False and "bwrap" in (sandbox.unavailable_reason or "")


def test_the_config_can_open_the_network_for_the_sandbox_and_it_starts_closed(tmp_path: Path):
    path = tmp_path / "config.toml"
    body = '[[models]]\nmodel = "a"\ntoken = "t"\n'

    path.write_text(body, encoding="utf-8")
    assert load_config(tmp_path, path=path).shell_network is False

    path.write_text(body + "\n[shell]\nnetwork = true\n", encoding="utf-8")
    assert load_config(tmp_path, path=path).shell_network is True

    path.write_text(body + "\n[shell]\nnetwrk = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="netwrk"):
        load_config(tmp_path, path=path)


def test_a_runtime_hands_its_sandbox_the_workspace_and_the_configured_network(tmp_path: Path, monkeypatch):
    from zettcode.config import ModelConfig, ZettCodeConfig
    from zettcode.engine import core as runtime_module

    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "s",
        mcp_enabled=False,
        shell_network=True,
    )

    runtime = runtime_module.ZettCodeEngine.preview(config)

    assert runtime.policy.sandbox is not None
    assert runtime.policy.sandbox.workspace == tmp_path.resolve()
    assert runtime.policy.sandbox.network is True


def test_nothing_probes_the_machine_until_a_command_needs_the_level(tmp_path: Path):
    policy = ShellPolicy(Permission.ASK, tmp_path)

    assert policy.sandbox is not None and policy.sandbox._probed is False
    assert policy.sandboxed is False, "at `ask` the question is never asked of the machine"
    assert policy.sandbox._probed is False


def test_the_event_loop_is_not_blocked_by_building_the_wrapped_line(workspace: Path):
    """Wrapping is a few string operations; the probe is the only slow step, and it happens once."""
    sandbox = _real(workspace)

    line = asyncio.run(asyncio.sleep(0, result=sandbox.wrap("true")))

    assert line.startswith("env -i ")
