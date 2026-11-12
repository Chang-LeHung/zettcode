"""The CLI command shape and the two gateway plugins."""

from __future__ import annotations

import json

import pytest

from zettcode.code_agents import ClaudeCodeAgent, CliAgent, CodexAgent, Command, _events, _timeout


def test_a_command_uses_the_resume_form_when_a_session_is_known(tmp_path):
    command = Command(
        "claude",
        "-p {prompt} --session-id {session}",
        "-p {prompt} --resume {session}",
    )

    assert command.argv("hello", "new-id", tmp_path, resume=False) == [
        "claude",
        "-p",
        "hello",
        "--session-id",
        "new-id",
    ]
    assert command.argv("hello", "abc", tmp_path) == ["claude", "-p", "hello", "--resume", "abc"]


def test_the_json_answer_and_session_id_are_read():
    stdout = "\n".join(
        json.dumps(event)
        for event in (
            {"session_id": "s-1", "result": ""},
            {"type": "item.completed", "item": {"text": "done"}},
        )
    )

    assert _events(stdout) == ("done", "s-1")


def test_both_plugins_carry_a_name_and_a_logo():
    assert CodexAgent.name == "codex" and CodexAgent.avatar.startswith("data:image/svg+xml;base64,")
    assert ClaudeCodeAgent.name == "claude" and ClaudeCodeAgent.avatar.startswith("data:image/svg+xml;base64,")


def test_a_bad_timeout_is_refused_before_a_command_starts(monkeypatch):
    monkeypatch.setenv("ZETTCODE_CODE_AGENTS_TIMEOUT", "nine")
    with pytest.raises(RuntimeError, match="number of seconds"):
        _timeout()

    monkeypatch.setenv("ZETTCODE_CODE_AGENTS_TIMEOUT", "0")
    with pytest.raises(RuntimeError, match="positive"):
        _timeout()

    monkeypatch.delenv("ZETTCODE_CODE_AGENTS_TIMEOUT")
    assert _timeout() > 0


async def test_a_cli_turn_saves_the_session_and_returns_its_text(tmp_path, monkeypatch):
    script = tmp_path / "fake"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps({'session_id': 's-1', 'result': sys.argv[1]}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    monkeypatch.setenv("ZETTCODE_CODE_AGENTS_DIR", str(tmp_path / "state"))

    agent = CliAgent("agent-1", "Fake", Command(str(script), "{prompt}", "resume {session} {prompt}"))

    assert await agent._run("hello") == "hello"
    assert json.loads((tmp_path / "state" / "agent-1.json").read_text()) == {"session": "s-1"}
