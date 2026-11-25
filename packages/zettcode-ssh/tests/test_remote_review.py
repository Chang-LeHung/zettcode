"""Review regressions using real pipes and the standalone payload; no SSH server is required."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
import signal
import sys
from pathlib import Path

import pytest
from zett_agent.agent import Agent, AgentRunConfig
from zett_agent.messages import ImageContent, ToolMessage

from zettcode.plugin_api import ShellPolicy
from zettcode.ssh.plugin import RemoteTools
from zettcode.ssh.remote import MAX_IMAGE, MAX_OUTPUT
from zettcode.ssh.transport import Target, Transport


@pytest.fixture(params=[sys.executable, shutil.which("python3.10")], ids=["current", "python310"])
def payload_python(request):
    if request.param is None:
        pytest.skip("Python 3.10 is not installed")
    return request.param


@pytest.fixture
def ssh_script(tmp_path, monkeypatch):
    """Install a fake SSH executable, but keep all subprocess/stream machinery real."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    executable = bin_dir / "ssh"
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])

    def install(source):
        executable.write_text(f"#!{sys.executable} -I\n" + source, encoding="utf-8")
        executable.chmod(0o755)

    return install


@pytest.fixture
def remote_ssh(tmp_path, ssh_script, payload_python):
    remote = tmp_path / "remote ' 中文 $ (project)"
    remote.mkdir()
    ssh_script(
        "import os, shlex, sys\n"
        "args = shlex.split(sys.argv[-1])\n"
        "assert args[:3] == ['python3', '-I', '-c'], args[:3]\n"
        f"os.execv({payload_python!r}, [{payload_python!r}, *args[1:]])\n"
    )
    return Transport(Target("test-alias", str(remote)), persistent=False), remote


async def test_large_request_preserves_authentication_diagnostic(ssh_script):
    ssh_script("import sys\nsys.stderr.write('Permission denied (publickey).\\n')\nsys.exit(255)\n")
    with pytest.raises(RuntimeError, match=r"SSH channel closed: Permission denied"):
        await Transport(Target("alias", "/remote")).run("write_file", {"file_path": "file", "content": "x" * 200000})


async def test_isolated_payload_ignores_workspace_login_and_pythonpath(remote_ssh, tmp_path, monkeypatch):
    transport, remote = remote_ssh
    login = tmp_path / "login"
    pythonpath = tmp_path / "pythonpath"
    login.mkdir()
    pythonpath.mkdir()
    sentinel = tmp_path / "IMPORTED_SHADOW"
    malicious = f"open({str(sentinel)!r}, 'w').write('unsafe import')\nraise RuntimeError('shadow import')\n"
    # selectors/time are imported after dispatch chdir; json and pathlib are imported at startup.
    for directory in (remote, login, pythonpath):
        for module in ("selectors", "json", "pathlib", "sitecustomize"):
            (directory / f"{module}.py").write_text(malicious, encoding="utf-8")
    monkeypatch.chdir(login)
    monkeypatch.setenv("PYTHONPATH", str(pythonpath))
    assert await transport.run("bash", {"command": "printf safe"}) == "safe"
    assert not sentinel.exists()


async def test_hidden_globs_grep_absolute_parent_and_symlinks(remote_ssh, tmp_path):
    transport, remote = remote_ssh
    for name in (".github/workflows/ci.yml", ".github/.secret", ".env", "src/.config", "src/a.txt"):
        path = remote / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("needle\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "unreachable.txt").write_text("needle\n", encoding="utf-8")
    (remote / "linked").symlink_to(outside, target_is_directory=True)
    (remote / "loop").symlink_to(remote, target_is_directory=True)
    (remote / "file-link").symlink_to(remote / ".env")
    for pattern in ("*", "**/*", "**/*.yml", ".github/**/*", "../outside/*", str(remote / "**/*")):
        candidate = Path(pattern)
        absolute = candidate.is_absolute()
        root = Path(candidate.anchor) if absolute else remote
        expression = candidate.relative_to(root).as_posix() if absolute else candidate.as_posix()
        expected = sorted(
            path.as_posix() if absolute else Path(os.path.relpath(path, remote)).as_posix()
            for path in root.glob(expression)
        )
        assert (await transport.run("glob", {"pattern": pattern})).splitlines() == expected
    result = await transport.run("grep", {"pattern": "needle"})
    assert ".github/workflows/ci.yml:1: needle" in result
    assert ".env:1: needle" in result and "src/.config:1: needle" in result
    assert "unreachable.txt" not in result and "loop/" not in result
    # Explicit path components still follow links; ** never follows them implicitly.
    assert await transport.run("glob", {"pattern": "linked/*"}) == "linked/unreachable.txt"
    assert (await transport.run("glob", {"pattern": "**/*", "max_results": 1})).endswith(
        "... [truncated; narrow the request]"
    )


async def test_writes_edits_follow_links_preserve_bytes_and_modes(remote_ssh):
    transport, remote = remote_ssh
    path = remote / "target"
    original = "中\r\nunique\r\nlast".encode()
    path.write_bytes(original)
    path.chmod(0o640)
    link = remote / "link"
    link.symlink_to("target")
    for old in ("absent", "1\t中"):
        with pytest.raises(RuntimeError, match="old_string not found"):
            await transport.run("edit", {"file_path": "link", "old_string": old, "new_string": "bad"})
        assert path.read_bytes() == original
    await transport.run("edit", {"file_path": "link", "old_string": "unique\r\n", "new_string": "新\r\n"})
    assert link.is_symlink() and path.read_bytes() == "中\r\n新\r\nlast".encode()
    assert path.stat().st_mode & 0o777 == 0o640
    await transport.run("write_file", {"file_path": "link", "content": "NUL\x00\r\n"})
    assert link.is_symlink() and path.read_bytes() == b"NUL\x00\r\n"
    await transport.run("edit", {"file_path": "link", "old_string": "\x00", "new_string": "\x00\x00"})
    assert path.read_bytes() == b"NUL\x00\x00\r\n"
    dangling = remote / "dangling"
    dangling.symlink_to("missing/target")
    await transport.run("write_file", {"file_path": "dangling", "content": "created"})
    assert dangling.is_symlink() and dangling.read_bytes() == b"created"
    assert not list(remote.rglob(".zettcode-ssh-*"))


async def test_atomic_failure_leaves_original_and_cleans_temporary(tmp_path, payload_python):
    from zettcode.ssh import remote as payload

    path = tmp_path / "target"
    path.write_bytes(b"unchanged")
    source = Path(payload.__file__).read_text(encoding="utf-8")
    # Execute the real payload, changing only os.replace to a simulated filesystem failure.
    suffix = (
        "\ndef fail(*args): raise OSError('replace failed')\n"
        "os.replace = fail\n"
        "try:\n"
        f"    atomic(Path({str(path)!r}), 'new')\n"
        "except OSError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('write should fail')\n"
    )
    process = await asyncio.create_subprocess_exec(
        payload_python,
        "-I",
        "-c",
        f"__name__ = 'review'; exec({source!r})" + suffix,
        stdin=asyncio.subprocess.DEVNULL,
    )
    assert await asyncio.wait_for(process.wait(), 5) == 0
    assert path.read_bytes() == b"unchanged"
    assert not list(tmp_path.glob(".zettcode-ssh-*"))


async def test_binary_images_text_rejection_and_exact_line_boundaries(remote_ssh):
    transport, remote = remote_ssh
    image = b"\x89PNG\r\n\x1a\n\xff\x00\x80"
    (remote / "not-an-extension").write_bytes(image)
    parts = await transport.run("read", {"file_path": "not-an-extension"})
    assert isinstance(parts[1], ImageContent) and parts[1].source.data == image
    with pytest.raises(RuntimeError, match="UnicodeDecodeError"):
        await transport.run("read_file", {"file_path": "not-an-extension"})
    with pytest.raises(RuntimeError, match="offset must be an integer"):
        await transport.run("read", {"file_path": "not-an-extension", "offset": 0})
    (remote / "large-image").write_bytes(image + b"x" * MAX_IMAGE)
    with pytest.raises(RuntimeError, match="Image exceeds"):
        await transport.run("read", {"file_path": "large-image"})
    (remote / "text").write_bytes("a\vb\u2028c\r\nlast".encode())
    assert await transport.run("read_file", {"file_path": "text"}) == "1\ta\vb\u2028c\n2\tlast"
    assert await transport.run("read_file", {"file_path": "text", "offset": 2}) == "2\tlast"
    assert await transport.run("read_file", {"file_path": "text", "offset": 3}) == ""


@pytest.mark.parametrize(
    "command,expected",
    [
        ("printf hello", "hello"),
        ("true", ""),
        ("printf warning >&2", "[stderr]\nwarning"),
        ("printf hello; printf warning >&2", "hello\n[stderr]\nwarning"),
    ],
)
async def test_successful_bash_output_matches_local_stream_format(remote_ssh, command, expected):
    transport, _ = remote_ssh
    assert await transport.run("bash", {"command": command}) == expected


async def test_bash_failures_preserve_exit_stderr_and_bounded_output(remote_ssh):
    transport, _ = remote_ssh
    with pytest.raises(RuntimeError) as failed:
        await transport.run("bash", {"command": "printf stdout; printf stderr >&2; exit 7"})
    assert "Command exited with code 7" in str(failed.value)
    assert "[remote exit code: 7]" in str(failed.value)
    assert "stdout" in str(failed.value) and "stderr" in str(failed.value)
    with pytest.raises(RuntimeError) as failed:
        await transport.run("bash", {"command": "printf '%060000d' 0; exit 9"})
    assert "truncated" in str(failed.value) and len(str(failed.value)) < MAX_OUTPUT + 1000
    assert len(str(failed.value)) > MAX_OUTPUT  # Not truncated to the old 4000-byte error summary.
    with pytest.raises(RuntimeError, match="cannot be blank"):
        await transport.run("bash", {"command": " \n "})


@pytest.mark.skipif(importlib.util.find_spec("sdk_helpers") is None, reason="checkout framework integration")
@pytest.mark.parametrize(
    "arguments,detail",
    [
        ({"command": "printf err >&2; exit 7"}, "exit code: 7"),
        ({"command": "printf err >&2; sleep 2", "timeout_seconds": 0.05}, "timed out"),
    ],
)
async def test_framework_marks_remote_bash_failure_unsuccessful(remote_ssh, arguments, detail):
    from sdk_helpers import ScriptedModel, asks_for, call

    transport, _ = remote_ssh
    policy = ShellPolicy()
    policy.level = type(policy.level)("full")
    backend = RemoteTools(transport.target, policy, "coding")
    model = ScriptedModel(asks_for(call("ssh__bash", arguments)), "done")
    agent = await Agent.create(model, config=AgentRunConfig(session_id="remote-review"), extensions=[backend])
    async for _ in agent.stream("run command"):
        pass
    message = next(item for item in model.requests[-1].messages if isinstance(item, ToolMessage))
    assert message.success is False
    assert detail in message.content and "err" in message.content


async def test_bash_timeout_kills_group_and_retains_output(remote_ssh):
    transport, remote = remote_ssh
    task = asyncio.create_task(
        transport.run(
            "bash",
            {
                "command": "printf before; printf stderr >&2; (sleep 1; touch SURVIVED) & wait",
                "timeout_seconds": 0.1,
            },
        )
    )
    done, _ = await asyncio.wait([task], timeout=3)
    assert done, "Remote bash deadline/cleanup hung"
    with pytest.raises(RuntimeError, match="timed out") as failed:
        await task
    assert "before" in str(failed.value) and "stderr" in str(failed.value)
    assert "remote exit code:" in str(failed.value)
    await asyncio.sleep(1.1)
    assert not (remote / "SURVIVED").exists()
    # EOF on stdout does not mean the process exited; the wait has the same deadline.
    with pytest.raises(RuntimeError, match="timed out"):
        await transport.run("bash", {"command": "exec >/dev/null 2>&1; sleep 2", "timeout_seconds": 0.05})


@pytest.fixture
def spawned(monkeypatch):
    original = asyncio.create_subprocess_exec
    processes = []

    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return processes


async def bounded_completion(task, processes):
    done, _ = await asyncio.wait([task], timeout=4)
    if not done:
        # A regression must fail, not strand pytest in cancellation cleanup.
        for process in processes:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
            process._transport.close()
        task.cancel()
        await asyncio.wait([task], timeout=1)
        pytest.fail("SSH cleanup exceeded its bound")
    assert processes and all(process.returncode is not None for process in processes)
    return await task


@pytest.mark.parametrize("stream", [1, 2], ids=["stdout", "stderr"])
async def test_real_transport_overflow_reaps_paused_streams(ssh_script, spawned, tmp_path, stream):
    ssh_script(
        f"import os, sys, time\nsys.stdin.buffer.read()\nfd = {stream}\nwhile True: os.write(fd, b'x' * 65536)\n"
    )
    task = asyncio.create_task(
        Transport(Target("alias", str(tmp_path)), persistent=False).run("read_file", {"file_path": "file"})
    )
    with pytest.raises(ValueError, match="output limit"):
        await bounded_completion(task, spawned)


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
async def test_real_transport_cancel_deadline_drains_both_streams(ssh_script, spawned, tmp_path, monkeypatch, reason):
    # Leave the real readers idle long enough for both asyncio buffers to pause. The marker
    # removes interpreter-startup timing from the deadline/cancellation regression.
    marker = tmp_path / "ready"
    ssh_script(
        "import os, time\nos.write(1, b'x' * 140000)\nos.write(2, b'y' * 140000)\n"
        f"open({str(marker)!r}, 'w').close()\ntime.sleep(30)\n"
    )

    async def idle_reader(stream, limit):
        await asyncio.Event().wait()

    monkeypatch.setattr("zettcode.ssh.transport.bounded", idle_reader)

    async def ready():
        for _ in range(300):
            if marker.exists():
                return
            await asyncio.sleep(0.01)
        pytest.fail("Fake SSH did not fill its pipes")

    if reason == "deadline":
        original = asyncio.wait_for

        async def short_wait(awaitable, timeout):
            await ready()
            return await original(awaitable, 0.01)

        monkeypatch.setattr(asyncio, "wait_for", short_wait)
    task = asyncio.create_task(
        Transport(Target("alias", str(tmp_path)), persistent=False).run(
            "write_file", {"file_path": "file", "content": "x" * 2000000}
        )
    )
    if reason == "cancel":
        await ready()
        task.cancel()
    with pytest.raises(asyncio.CancelledError if reason == "cancel" else asyncio.TimeoutError):
        await bounded_completion(task, spawned)


async def test_cleanup_closes_pipes_inherited_by_detached_descendant(ssh_script, spawned, tmp_path):
    child_pid = tmp_path / "child-pid"
    ssh_script(
        "import os, subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(30)'], start_new_session=True)\n"
        f"open({str(child_pid)!r}, 'w').write(str(child.pid))\n"
        "while True: os.write(1, b'x' * 65536)\n"
    )
    task = asyncio.create_task(
        Transport(Target("alias", str(tmp_path)), persistent=False).run("read_file", {"file_path": "file"})
    )
    try:
        with pytest.raises(ValueError, match="output limit"):
            await bounded_completion(task, spawned)
    finally:
        if child_pid.exists():
            try:
                os.kill(int(child_pid.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
