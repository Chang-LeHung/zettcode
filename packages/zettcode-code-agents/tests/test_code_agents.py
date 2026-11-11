"""The CLI command shape and the two gateway plugins."""

from __future__ import annotations

import json

from zettcode.code_agents import ClaudeCodeAgent, CodexAgent, Command, _events


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
