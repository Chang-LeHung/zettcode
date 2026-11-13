"""The CLI command shape and the two gateway plugins."""

from __future__ import annotations

import dataclasses
import json

import pytest

from zettcode.code_agents import (
    CLAUDE,
    CODEX,
    ClaudeCodeAgent,
    CliAgent,
    CodexAgent,
    Command,
    ConfigError,
    _events,
    _timeout,
)
from zettcode.code_agents.config import DEFAULT_PERMISSION, resolve


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


# -- the plugin's own settings ---------------------------------------------------------------------------------------


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Point the plugin at a settings file and a state folder of its own, and return a function that writes the file."""
    path = tmp_path / "config.json"
    monkeypatch.setenv("ZETTCODE_CODE_AGENTS_CONFIG", str(path))
    monkeypatch.setenv("ZETTCODE_CODE_AGENTS_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ZETTCODE_CODE_AGENTS_CWD", str(tmp_path))
    for name in ("BIN", "ARGS", "RESUME_ARGS"):
        monkeypatch.delenv(f"ZETTCODE_CODEX_{name}", raising=False)
        monkeypatch.delenv(f"ZETTCODE_CLAUDE_{name}", raising=False)
    monkeypatch.delenv("ZETTCODE_CODE_AGENTS_TIMEOUT", raising=False)

    def write(content) -> None:
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")

    return write


def test_with_no_settings_an_agent_runs_in_the_gateways_folder_and_is_fully_trusted(tmp_path, settings_file):
    settings = resolve(CODEX)

    assert DEFAULT_PERMISSION == "full" and settings.permission == "full"
    assert settings.cwd == tmp_path.resolve()
    assert settings.timeout == 900.0
    assert (settings.binary, settings.args) == ("codex", CODEX.args)


def test_a_tools_own_section_beats_the_top_level_which_beats_the_environment(tmp_path, settings_file, monkeypatch):
    (tmp_path / "top").mkdir()
    (tmp_path / "api").mkdir()
    monkeypatch.setenv("ZETTCODE_CLAUDE_BIN", "from-the-environment")
    settings_file(
        {
            "cwd": str(tmp_path / "top"),
            "permission": "read",
            "timeout": 30,
            "codex": {"cwd": str(tmp_path / "api"), "permission": "workspace", "bin": "/opt/codex"},
        }
    )

    codex, claude = resolve(CODEX), resolve(CLAUDE)

    assert (codex.cwd, codex.permission, codex.timeout, codex.binary) == (
        (tmp_path / "api").resolve(),
        "workspace",
        30.0,
        "/opt/codex",
    )
    # Claude has no section: it takes the shared values, and its own command from the environment.
    assert (claude.cwd, claude.permission, claude.timeout) == ((tmp_path / "top").resolve(), "read", 30.0)
    assert claude.binary == "from-the-environment"


@pytest.mark.parametrize(
    ("content", "needle"),
    [
        ("{not json", "is not valid JSON"),
        ("[1, 2]", "must hold one JSON object"),
        ({"permission": "root"}, '"permission"'),
        ({"permission": 3}, '"permission" in'),
        ({"cwd": "/no/such/folder/anywhere"}, "does not exist"),
        ({"cwd": ""}, '"cwd" in'),
        ({"timeout": 0}, '"timeout"'),
        ({"timeout": True}, '"timeout"'),
        ({"timeout": "soon"}, '"timeout"'),
        ({"codex": "yes"}, '"codex" in'),
        ({"codex": {"bin": ""}}, '"bin" in'),
        # {permission} is several arguments, so it cannot be part of one (--sandbox={permission} cannot work).
        ({"codex": {"args": "exec --sandbox={permission} {prompt}"}}, "word of its own"),
        ({"codex": {"resume_args": "exec resume {session} x{permission} {prompt}"}}, '"resume_args"'),
        ({"codex": {"args": "exec {prmpt}"}}, r"names \{prmpt\}"),
        ({"codex": {"args": "exec 'unclosed {prompt}"}}, "not a command line"),
        ({"codex": {"args": "exec {"}}, "cannot be filled in"),
    ],
)
def test_a_setting_that_cannot_be_used_is_refused_with_the_file_and_the_key(settings_file, content, needle):
    settings_file(content)

    with pytest.raises(ConfigError, match=needle) as caught:
        resolve(CODEX)

    assert "config.json" in str(caught.value)


def test_a_missing_or_empty_settings_file_is_no_settings(settings_file, tmp_path):
    assert resolve(CODEX).permission == "full"
    settings_file("  \n")
    assert resolve(CODEX).permission == "full"


# -- what each trust level asks of each CLI ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool", "permission", "resumed", "expected"),
    [
        (CODEX, "full", False, ["--dangerously-bypass-approvals-and-sandbox"]),
        (CODEX, "workspace", False, ["--sandbox", "workspace-write"]),
        (CODEX, "read", False, ["--sandbox", "read-only"]),
        # `codex exec resume` has no --sandbox: the same choice goes in as a configuration override.
        (CODEX, "full", True, ["--dangerously-bypass-approvals-and-sandbox"]),
        (CODEX, "workspace", True, ["-c", 'sandbox_mode="workspace-write"']),
        (CODEX, "read", True, ["-c", 'sandbox_mode="read-only"']),
        (CLAUDE, "full", False, ["--permission-mode", "bypassPermissions"]),
        (CLAUDE, "workspace", True, ["--permission-mode", "acceptEdits"]),
        (CLAUDE, "read", False, ["--permission-mode", "plan"]),
    ],
)
async def test_each_trust_level_becomes_the_arguments_of_its_cli(
    tmp_path, settings_file, monkeypatch, tool, permission, resumed, expected
):
    script = tmp_path / "fake"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        "print(json.dumps({'session_id': 's-1', 'result': json.dumps(sys.argv[1:])}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    settings_file({"permission": permission, tool.name: {"bin": str(script)}})
    if resumed:
        (tmp_path / "state").mkdir()
        (tmp_path / "state" / "a.json").write_text(json.dumps({"session": "s-0"}), encoding="utf-8")

    argv = json.loads(await CliAgent("a", "A", tool)._run("do it"))

    # The flags are inside the command, before the prompt (Codex) or before -p (Claude), never glued to it.
    for flag in expected:
        assert flag in argv
    assert argv.index(expected[0]) < argv.index("do it")
    assert ("resume" in argv) is (resumed and tool is CODEX)


async def test_an_edit_of_the_settings_applies_to_the_next_message_with_no_restart(tmp_path, settings_file):
    script = tmp_path / "fake"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "print(json.dumps({'session_id': 's-1', 'result': json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()})}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    agent = CliAgent("agent-1", "Codex", dataclasses.replace(CODEX, binary=str(script)))

    settings_file({"cwd": str(first), "permission": "read"})
    one = json.loads(await agent._run("hello"))
    settings_file({"cwd": str(second), "permission": "workspace"})
    two = json.loads(await agent._run("again"))

    assert one["cwd"] == str(first.resolve()) and "read-only" in one["argv"]
    # The same running agent, the next message: the new folder, and the new level in the form a resumed turn takes.
    assert two["cwd"] == str(second.resolve()) and 'sandbox_mode="workspace-write"' in two["argv"]
    assert "resume" in two["argv"]


async def test_what_was_chosen_for_one_agent_wins_over_the_file_and_belongs_to_that_agent_alone(
    tmp_path, settings_file
):
    script = tmp_path / "fake"
    script.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "print(json.dumps({'session_id': 's-1', 'result': json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()})}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    filed, chosen = tmp_path / "filed", tmp_path / "chosen"
    filed.mkdir()
    chosen.mkdir()
    tool = dataclasses.replace(CODEX, binary=str(script))
    settings_file({"cwd": str(filed), "permission": "full"})

    picky = CodexAgent().create_with("picky", "Picky", {"cwd": str(chosen), "permission": "read"})
    plain = CodexAgent().create("plain", "Plain")
    assert isinstance(picky, CliAgent) and isinstance(plain, CliAgent)
    picky.source = plain.source = tool

    one = json.loads(await picky._run("hello"))
    two = json.loads(await plain._run("hello"))

    assert one["cwd"] == str(chosen.resolve()) and "read-only" in one["argv"]
    # An agent started with no choice follows the file, as before.
    assert two["cwd"] == str(filed.resolve()) and "read-only" not in two["argv"]


def test_an_empty_choice_leaves_the_file_in_charge_and_a_choice_the_tool_does_not_know_is_refused(
    tmp_path, settings_file
):
    settings_file({"permission": "workspace"})

    assert resolve(CODEX, overrides={"permission": "", "cwd": ""}).permission == "workspace"
    assert resolve(CODEX, overrides={"permission": "read"}).permission == "read"
    assert resolve(CODEX, overrides={"unknown": "x", "timeout": "5"}).timeout != 5
    with pytest.raises(ConfigError, match="full, workspace or read"):
        resolve(CODEX, overrides={"permission": "root"})


def test_the_two_plugins_offer_a_folder_and_an_access_level_and_name_full_as_the_unrestricted_one():
    for plugin in (CodexAgent(), ClaudeCodeAgent()):
        fields = {item.name: item for item in plugin.fields}
        assert fields["cwd"].kind == "directory"
        assert fields["permission"].choices == ("full", "workspace", "read")
        assert fields["permission"].unrestricted == "full"


async def test_a_broken_settings_file_fails_the_turn_with_a_sentence_and_the_agent_goes_on(tmp_path, settings_file):
    agent = CliAgent("agent-1", "Codex", CODEX)
    settings_file("{oops")

    with pytest.raises(ConfigError, match="not valid JSON"):
        await agent._run("hello")

    # Mended, the very next turn runs; nothing about the agent had to be rebuilt.
    script = tmp_path / "fake"
    script.write_text('#!/usr/bin/env python3\nprint(\'{"result": "ok"}\')\n', encoding="utf-8")
    script.chmod(0o755)
    settings_file({"codex": {"bin": str(script)}})
    assert await agent._run("hello") == "ok"


def test_a_command_template_without_the_permission_word_is_run_exactly_as_written(tmp_path):
    own = Command("codex", "exec {prompt}", "exec resume {session} {prompt}")

    assert own.argv("hi", "", tmp_path, permission=("--sandbox", "read-only")) == ["codex", "exec", "hi"]
    shaped = Command("codex", "exec {permission} {prompt}", "x")
    assert shaped.argv("hi", "", tmp_path, permission=("--a", "b")) == ["codex", "exec", "--a", "b", "hi"]
    assert shaped.argv("hi", "", tmp_path) == ["codex", "exec", "hi"], "no flags: the word leaves nothing behind"
