"""Self-compaction for one session or for all of them: the session's choice, the config default, and what shows.

A session holds ``True``, ``False`` or nothing. Nothing means it follows ``[compaction] self`` in the config
file, so changing that default reaches every session that never chose, and none that did.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.agent import AgentRunConfig, AgentRunContext, AgentState
from zett_agent.messages import SystemMessage, UserMessage

from test_zettcode_app import build_app
from zettcode._compat import tomllib
from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.config import ModelConfig, ZettCodeConfig, load_config
from zettcode.config_edit import ConfigEditError, set_self_compaction
from zettcode.engine.core import ZettCodeEngine
from zettcode.engine.storage import SessionLocked

WHERE = Path("config.toml")
MODEL = '[[models]]\nmodel = "m"\ntoken = "t"\n'


def _config(tmp_path: Path, **changes) -> ZettCodeConfig:
    return ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="m", token="t"),),
        mcp_config=tmp_path / "absent-mcp.json",
        **changes,
    )


def _agent(tmp_path: Path, monkeypatch, **changes) -> ZettCodeAgent:
    monkeypatch.setattr("zettcode.engine.core.os.chdir", lambda path: None)
    return ZettCodeAgent(ZettCodeEngine.preview(_config(tmp_path, **changes)))


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(MODEL, encoding="utf-8")
    monkeypatch.setenv("ZETTCODE_CONFIG", str(path))
    return path


def _context(session_id: str) -> AgentRunContext:
    state = AgentState()
    state._messages.append(SystemMessage(content="instructions"))
    return AgentRunContext(AgentRunConfig(session_id=session_id), state, {})


# -- the config file ---------------------------------------------------------------------------------------


def test_the_default_comes_from_the_compaction_table(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(MODEL + "\n[compaction]\nself = true\n", encoding="utf-8")

    assert load_config(tmp_path, path=path).self_compaction is True


def test_without_the_table_the_default_is_off(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(MODEL, encoding="utf-8")

    assert load_config(tmp_path, path=path).self_compaction is False


@pytest.mark.parametrize("body", ["self = 1", 'self = "yes"', "unknown = true"])
def test_a_bad_compaction_table_is_refused(tmp_path: Path, body):
    path = tmp_path / "config.toml"
    path.write_text(f"{MODEL}\n[compaction]\n{body}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="self|compaction"):
        load_config(tmp_path, path=path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (MODEL, MODEL + "\n[compaction]\nself = true\n"),
        (MODEL + "\n[compaction]\nself = false\n", MODEL + "\n[compaction]\nself = true\n"),
        (MODEL + "\n[ui]\ntheme = 'nord'\n", MODEL + "\n[ui]\ntheme = 'nord'\n\n[compaction]\nself = true\n"),
    ],
)
def test_the_edit_sets_one_key_and_changes_nothing_else(text, expected):
    result = set_self_compaction(text, True, where=WHERE)

    assert tomllib.loads(result)["compaction"] == {"self": True}
    assert result == expected
    assert {k: v for k, v in tomllib.loads(result).items() if k != "compaction"} == {
        k: v for k, v in tomllib.loads(text).items() if k != "compaction"
    }


def test_the_edit_keeps_a_comment_beside_the_key():
    text = MODEL + "\n[compaction]\n# the model decides\nself = false  # off for now\n"

    result = set_self_compaction(text, True, where=WHERE)

    assert "# the model decides" in result
    assert tomllib.loads(result)["compaction"]["self"] is True


def test_an_inline_table_is_refused_rather_than_guessed_at():
    with pytest.raises(ConfigEditError, match="by hand"):
        set_self_compaction("compaction = { self = false }\n" + MODEL, True, where=WHERE)


# -- the session and the default ---------------------------------------------------------------------------


async def test_a_session_that_never_chose_follows_the_default(tmp_path: Path, monkeypatch):
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    on = _agent(tmp_path / "on", monkeypatch, self_compaction=True)
    off = _agent(tmp_path / "off", monkeypatch)
    try:
        assert on.self_compaction is True and on.self_compaction_choice is None
        assert off.self_compaction is False and off.self_compaction_choice is None
    finally:
        await on.runtime.aclose()
        await off.runtime.aclose()


async def test_the_models_tool_follows_the_default_and_the_sessions_own_choice(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch, self_compaction=True)
    try:
        ctx = _context(agent.session_id)
        await agent.runtime.compaction.on_tool(ctx)
        assert "compact_context" in ctx.tools, "no choice of its own: the default on applies"

        agent.use_self_compaction(False)
        ctx = _context(agent.session_id)
        await agent.runtime.compaction.on_tool(ctx)
        assert not ctx.tools, "an explicit off beats the default"
    finally:
        await agent.runtime.aclose()


async def test_an_explicit_choice_survives_a_change_of_the_default(tmp_path: Path, monkeypatch, config_file):
    agent = _agent(tmp_path, monkeypatch)
    try:
        agent.use_self_compaction(True)
        agent.remember_self_compaction(False)

        assert agent.self_compaction is True, "the session chose; the default moving does not move it"
        agent.use_self_compaction(None)
        assert agent.self_compaction is False, "taken back, it follows the default"
    finally:
        await agent.runtime.aclose()


async def test_the_choice_is_stored_with_the_session_and_read_by_a_new_process(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch)
    try:
        await agent.runtime.persistence.append(agent.session_id, "req", UserMessage(content="hello"))
        agent.use_self_compaction(True)
        session_id = agent.session_id
    finally:
        await agent.runtime.aclose()

    reopened = _agent(tmp_path, monkeypatch)
    try:
        assert reopened.runtime.self_compacting(session_id) is True
        assert reopened.runtime.self_compacting(reopened.session_id) is False, "a new session is its own"
    finally:
        await reopened.runtime.aclose()


async def test_a_session_open_elsewhere_cannot_have_its_choice_changed(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(type(agent.runtime), "session_locked", property(lambda self: True))

        with pytest.raises(SessionLocked):
            agent.use_self_compaction(True)
    finally:
        await agent.runtime.aclose()


async def test_a_failed_write_is_an_error_and_the_old_choice_stands(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch)
    try:
        await agent.runtime.persistence.append(agent.session_id, "req", UserMessage(content="hello"))

        def fail(*args, **kwargs):
            raise OSError("read-only")

        monkeypatch.setattr(agent.runtime.persistence, "set_self_compact", fail)

        with pytest.raises(ConfigEditError, match="not saved"):
            agent.use_self_compaction(True)
        assert agent.self_compaction_choice is None
    finally:
        await agent.runtime.aclose()


# -- the global default, through the command ---------------------------------------------------------------


async def test_global_writes_the_config_file_and_applies_at_once(tmp_path: Path, monkeypatch, config_file):
    agent = _agent(tmp_path, monkeypatch)
    try:
        message = agent.change_self_compaction("global on")

        assert tomllib.loads(config_file.read_text(encoding="utf-8"))["compaction"] == {"self": True}
        assert agent.self_compaction is True and agent.self_compaction_choice is None
        assert "**on**" in message
    finally:
        await agent.runtime.aclose()


async def test_global_without_a_config_file_says_so_and_changes_nothing(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ZETTCODE_CONFIG", str(tmp_path / "missing.toml"))
    agent = _agent(tmp_path, monkeypatch)
    try:
        with pytest.raises(ConfigEditError, match="does not exist"):
            agent.change_self_compaction("global on")
        assert agent.self_compaction is False
        assert not (tmp_path / "missing.toml").exists()
    finally:
        await agent.runtime.aclose()


async def test_a_failed_config_write_leaves_the_running_default_alone(tmp_path: Path, monkeypatch, config_file):
    agent = _agent(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(
            "zettcode.app.agent.agent.settings.write_text_atomically",
            lambda path, text: (_ for _ in ()).throw(OSError("full")),
        )

        with pytest.raises(ConfigEditError, match="could not be written"):
            agent.change_self_compaction("global on")
        assert agent.self_compaction is False
        assert "compaction" not in tomllib.loads(config_file.read_text(encoding="utf-8"))
    finally:
        await agent.runtime.aclose()


# -- what the reader is told -------------------------------------------------------------------------------


async def test_the_report_says_what_it_is_and_where_the_value_comes_from(tmp_path: Path, monkeypatch, config_file):
    agent = _agent(tmp_path, monkeypatch)
    try:
        following = agent.change_self_compaction("")
        chosen = agent.change_self_compaction("on")

        assert "following the config default" in following and "**off**" in following
        assert "this session chose it" in chosen and "**on**" in chosen
        for message in (following, chosen):
            assert "summarize its own earlier conversation" in message, "the concept is explained"
            assert "`global on|off`" in message
    finally:
        await agent.runtime.aclose()


async def test_the_one_line_summary_says_where_the_value_comes_from(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch, self_compaction=True)
    try:
        assert agent.self_compaction_summary() == "Self-compaction is on: this session follows the default (on)"
        agent.use_self_compaction(False)
        assert agent.self_compaction_summary() == "Self-compaction is off: this session chose it; the default is on"
    finally:
        await agent.runtime.aclose()


async def test_the_panel_is_the_choice_so_the_command_offers_no_word_menu():
    """Typing the command and a space must not open a list of words: Enter has to reach the panel."""
    app = build_app()

    command = next(c for c in app.commands if c.name == "/self-compact")

    assert command.options() == (), "no subcommands, as /effort has none: the panel is the choice"
    assert next(c for c in app.commands if c.name == "/effort").options() == ()


async def test_the_tool_says_what_self_compaction_is():
    from zettcode.engine.extensions.compaction import OnDemandCompaction

    extension = OnDemandCompaction(None, self_compact=lambda session_id: True)
    ctx = _context("s")

    await extension.on_tool(ctx)

    description = ctx.tools["compact_context"].description
    assert "self-compaction" in description.lower() and "your own context" in description
    assert "current user turn" in description, "the one thing it never touches is part of what the model reads"


def test_the_status_line_says_when_it_is_on():
    from dataclasses import replace

    from test_zettcode_app import build_app
    from zettcode.plugins.builtins import ShellRows

    context = build_app()._shell_context()
    rows = ShellRows()

    def status(on: bool) -> str:
        return rows.render_status_left(replace(context, activity=replace(context.activity, self_compact=on))).text()

    assert "self-compact" in status(True)
    assert "self-compact" not in status(False)
