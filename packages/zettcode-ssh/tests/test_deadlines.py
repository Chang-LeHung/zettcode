"""Deadline regressions without waiting for long-running commands or real alarms."""

import io
import json
from types import SimpleNamespace

import pytest

from zettcode.ssh import remote
from zettcode.ssh.tools import descriptor


@pytest.mark.parametrize("worker", [False, True], ids=["one-shot", "persistent"])
@pytest.mark.parametrize(
    "operation,arguments,expected",
    [
        ("bash", {}, 65),
        ("bash", {"timeout_seconds": 600}, 605),
        ("bash", {"timeout_seconds": 200.5}, 206),
        ("read", {}, 125),
        ("bash", {"timeout_seconds": 601}, 125),
        ("bash", {"timeout_seconds": True}, 125),
        ("bash", {"timeout_seconds": float("inf")}, 125),
        ("bash", {"timeout_seconds": 10**1000}, 125),
    ],
)
def test_remote_alarm_follows_request_deadline(monkeypatch, worker, operation, arguments, expected):
    request = {"id": 1, "operation": operation, "workspace": "/remote", "arguments": arguments}
    alarms = []
    output = io.BytesIO()
    monkeypatch.setattr(remote.sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode() + b"\n")))
    monkeypatch.setattr(remote.sys, "stdout", SimpleNamespace(buffer=output))
    monkeypatch.setattr(remote.signal, "signal", lambda *args: None)
    monkeypatch.setattr(remote.signal, "alarm", alarms.append)

    def dispatch(value):
        assert alarms[-1] == expected
        if operation == "bash":
            remote.duration(arguments.get("timeout_seconds", 60))
        return "done"

    monkeypatch.setattr(remote, "dispatch", dispatch)
    (remote.serve if worker else remote.main)()
    assert alarms == [125, expected, 0]
    response = json.loads(output.getvalue())
    assert response["ok"] == (operation != "bash" or expected != 125)


async def test_bash_schema_accepts_local_tool_ceiling():
    seen = []

    async def handler(**arguments):
        seen.append(arguments)
        return "done"

    tool = descriptor("bash", handler)
    assert await tool.handler(command="true", timeout_seconds=600) == "done"
    assert seen[0]["timeout_seconds"] == 600
    with pytest.raises(ValueError):
        await tool.handler(command="true", timeout_seconds=601)
