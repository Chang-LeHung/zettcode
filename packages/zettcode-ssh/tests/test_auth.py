"""Both sign-ins: keys/agent need no secret, and a password never reaches argv or durable state."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from zettcode.ssh.transport import Target, Transport

PASSWORD = "s3cret-with space"


@pytest.fixture
def fake_ssh(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "record.json"
    executable = bin_dir / "ssh"
    executable.write_text(
        f"#!{sys.executable} -I\n"
        "import json, os, shlex, stat, subprocess, sys\n"
        "argv = sys.argv[1:]\n"
        "askpass = os.environ.get('SSH_ASKPASS', '')\n"
        "mode = stat.S_IMODE(os.stat(os.path.dirname(askpass)).st_mode) if askpass else None\n"
        "secret = os.path.join(os.path.dirname(askpass), 'secret') if askpass else ''\n"
        "secret_mode = stat.S_IMODE(os.stat(secret).st_mode) if secret and os.path.exists(secret) else None\n"
        "given = ''\n"
        "if askpass:\n"
        "    given = subprocess.run([askpass], capture_output=True, text=True).stdout.strip()\n"
        f"open({str(record)!r}, 'w').write(json.dumps({{'argv': argv, 'given': given, 'dir_mode': mode, "
        "'secret_mode': secret_mode, 'require': os.environ.get('SSH_ASKPASS_REQUIRE'), "
        "'env_has_password': any('s3cret' in value for value in os.environ.values())}))\n"
        "if os.environ.get('FAKE_REJECT'):\n"
        "    sys.stderr.write('Permission denied (publickey,password).\\n')\n"
        "    raise SystemExit(255)\n"
        "args = shlex.split(argv[-1])\n"
        "os.execv(sys.executable, [sys.executable, *args[1:]])\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    return record, tmp_path


def recorded(record: Path) -> dict:
    return json.loads(record.read_text(encoding="utf-8"))


async def test_key_sign_in_sends_no_password_prompt(fake_ssh):
    record, directory = fake_ssh
    transport = Transport(Target("alias", str(directory)))
    try:
        assert await transport.run("ping", {}) == str(directory)
    finally:
        await transport.aclose()
    seen = recorded(record)
    assert "BatchMode=yes" in seen["argv"] and "BatchMode=no" not in seen["argv"]
    assert seen["require"] is None and seen["given"] == ""


async def test_password_sign_in_uses_askpass_and_never_argv(fake_ssh):
    record, directory = fake_ssh
    target = Target("alias", str(directory), "deploy", "password")
    transport = Transport(target, password=PASSWORD)
    try:
        assert await transport.run("ping", {}) == str(directory)
        request = json.dumps({"target": target.export()})
        assert PASSWORD not in request and "password" == target.auth
    finally:
        await transport.aclose()
    seen = recorded(record)
    assert "BatchMode=no" in seen["argv"] and "NumberOfPasswordPrompts=1" in seen["argv"]
    assert "PreferredAuthentications=password,keyboard-interactive" in seen["argv"]
    assert ("-l", "deploy") == tuple(seen["argv"][seen["argv"].index("-l") : seen["argv"].index("-l") + 2])
    assert seen["given"] == PASSWORD
    assert seen["dir_mode"] == 0o700 and seen["secret_mode"] == 0o600
    assert seen["require"] == "force"
    assert PASSWORD not in " ".join(seen["argv"]) and seen["env_has_password"] is False
    # Closing the connection takes the password with it.
    assert not list(Path(seen["argv"][0]).parent.glob("zettcode-ssh-askpass-*"))


async def test_closing_forgets_the_password_and_its_helper(fake_ssh):
    record, directory = fake_ssh
    transport = Transport(Target("alias", str(directory), None, "password"), password=PASSWORD)
    try:
        assert await transport.run("ping", {}) == str(directory)
        assert transport.needs_password is False
        helper = transport._askpass
        assert helper is not None and helper.directory is not None
        directory_path = helper.directory
        assert directory_path.is_dir()
    finally:
        await transport.aclose()
    assert transport.password is None and transport.needs_password is True
    assert not directory_path.exists(), "the password's directory goes with the channel"


async def test_a_refused_password_reports_the_server_diagnostic(fake_ssh, monkeypatch):
    record, directory = fake_ssh
    monkeypatch.setenv("FAKE_REJECT", "1")
    transport = Transport(Target("alias", str(directory), None, "password"), password="wrong")
    try:
        with pytest.raises(RuntimeError, match=r"Permission denied \(publickey,password\)"):
            await transport.run("ping", {})
    finally:
        await transport.aclose()
    assert transport.status.startswith("disconnected")


async def test_an_inherited_password_target_fails_closed_without_one(fake_ssh):
    record, directory = fake_ssh
    restored = Target.restore({"host": "alias", "path": str(directory), "user": "deploy", "auth": "password"})
    transport = Transport(restored)
    try:
        with pytest.raises(RuntimeError, match="never saved or inherited"):
            await transport.run("ping", {})
    finally:
        await transport.aclose()
    assert not record.exists(), "nothing may be started for a target whose password is missing"


def test_the_plugin_says_a_restored_password_target_needs_one(monkeypatch):
    from zettcode.plugin_api import POLICY, PluginContext, ShellPolicy, ZettCodeConfig
    from zettcode.ssh.plugin import SSHPlugin

    policy = ShellPolicy()
    policy.level = type(policy.level)("full")
    plugin = SSHPlugin()
    plugin.restore_child({"host": "alias", "path": "/remote", "auth": "password"})
    context = PluginContext(
        ZettCodeConfig(workspace=Path("/tmp"), models=(), store=Path("/tmp/store")), {POLICY: policy}, name="ssh"
    )
    plugin.activate(context)
    # Before any tool call builds a transport, the restored target already says what it needs.
    assert "never saved or inherited" in plugin.status()
    assert "password needed" in plugin.state()
    backend = plugin.backend()
    assert backend.transport.needs_password
    assert "password needed" in plugin.state()


def test_descriptors_accept_the_old_shape_and_refuse_secrets():
    assert Target.restore({"host": "alias", "path": "/srv"}) == Target("alias", "/srv")
    assert Target.restore({"host": "alias", "path": "/srv", "user": "deploy", "auth": "password"}) == Target(
        "alias", "/srv", "deploy", "password"
    )
    for state in (
        {"host": "alias", "path": "/srv", "password": "x"},
        {"host": "alias", "path": "/srv", "user": "-oProxyCommand=x"},
        {"host": "alias", "path": "/srv", "auth": "whatever"},
    ):
        with pytest.raises(ValueError):
            Target.restore(state)


@pytest.mark.parametrize("password", ["", "line\nbreak", "nul\x00byte"])
async def test_an_unusable_password_is_refused_before_ssh(fake_ssh, password):
    record, directory = fake_ssh
    transport = Transport(Target("alias", str(directory), None, "password"), password=password)
    try:
        with pytest.raises(ValueError):
            await transport.run("ping", {})
    finally:
        await transport.aclose()
    assert not record.exists()
