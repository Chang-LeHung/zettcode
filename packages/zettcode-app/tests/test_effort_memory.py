"""The reasoning level a session was last run at comes back with it.

The level is per session, not per process and not per configuration: opening a session again reasons as much as
that conversation last did, a new session starts at the level a run starts at, and a level equal to that one is not
written down at all — a session that holds no level is one that behaves that way. It travels with the model, which
is why it is recorded beside it: a conversation that reasoned at ``high`` and came back at ``low`` would answer the
same question with less care, and nothing on screen would say why.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from zett_agent.extensions.shell_approval import ShellApprovalMode
from zett_agent.messages import AssistantMessage, UserMessage

from zettcode.config import ModelConfig, ReasoningEffort, ZettCodeConfig
from zettcode.engine import core as runtime_module
from zettcode.engine.storage import SessionStore
from zettcode.engine.storage.metadata import SESSION_METADATA_FILE
from zettcode.sdk.builtins import load_agent_plugins


def _runtime(
    tmp_path: Path,
    monkeypatch,
    *,
    started_at: ReasoningEffort = ReasoningEffort.MEDIUM,
    levels: tuple[ReasoningEffort, ...] = (),
    models: tuple[ModelConfig, ...] = (),
):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    (tmp_path / "work").mkdir(exist_ok=True)
    config = ZettCodeConfig(
        workspace=tmp_path / "work",
        models=models or (ModelConfig(model="m", token="t", reasoning_efforts=levels),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
        sessions_enabled=False,
        shell_approval=ShellApprovalMode.REVIEW,
        reasoning_effort=started_at,
    )
    return runtime_module.ZettCodeEngine.preview(config, load_agent_plugins)


async def _stored(runtime, session_id: str, *, effort: str | None = None) -> None:
    """Give a session a conversation on disk, and a level when one was recorded."""
    store = SessionStore(runtime.config.store, runtime.config.workspace)
    await store.append(session_id, "req", UserMessage(content="hello"))
    await store.append(session_id, "req", AssistantMessage(content="hi there"))
    if effort is not None:
        store.set_effort(session_id, effort, default=runtime.default_effort.value)


def _recorded(runtime, session_id: str) -> str | None:
    """Read the level written in a session's own metadata file, or ``None`` when it has none."""
    path = runtime.config.store / runtime.config.workspace.name / session_id / SESSION_METADATA_FILE
    for found in runtime.config.store.rglob(SESSION_METADATA_FILE):
        if found.parent.name == session_id:
            path = found
            break
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("effort")


# -- what is written ------------------------------------------------------------------------------------------------


def test_a_level_the_reader_chose_is_written_into_the_sessions_own_file(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    runtime.use_effort("high")

    assert runtime.effort is ReasoningEffort.HIGH
    assert _recorded(runtime, runtime.session_id) == "high"


def test_the_level_a_run_starts_at_is_not_written_down(tmp_path: Path, monkeypatch):
    """A session that holds no level already reasons that way, so the file says nothing."""
    runtime = _runtime(tmp_path, monkeypatch)

    runtime.use_effort(runtime.default_effort.value)

    assert _recorded(runtime, runtime.session_id) is None


def test_going_back_to_the_default_takes_the_recorded_level_away(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.use_effort("high")

    runtime.use_effort(runtime.default_effort.value)

    assert _recorded(runtime, runtime.session_id) is None


def test_a_level_chosen_for_the_run_at_launch_is_not_written_into_the_session(tmp_path: Path, monkeypatch):
    """``effort=`` on a client is "this process", so the session keeps whatever level it had."""
    runtime = _runtime(tmp_path, monkeypatch)

    runtime.use_effort("high", remember=False)

    assert runtime.effort is ReasoningEffort.HIGH
    assert _recorded(runtime, runtime.session_id) is None


def test_a_level_the_model_does_not_take_is_refused_and_nothing_is_written(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch, levels=(ReasoningEffort.LOW, ReasoningEffort.MEDIUM))

    with pytest.raises(ValueError, match="does not take ultra"):
        runtime.use_effort("ultra")

    assert runtime.effort is ReasoningEffort.MEDIUM
    assert _recorded(runtime, runtime.session_id) is None


@pytest.mark.parametrize("wanted", ["off", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"])
def test_every_level_can_be_remembered(wanted: str, tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    runtime.use_effort(wanted)

    assert _recorded(runtime, runtime.session_id) == (None if wanted == runtime.default_effort.value else wanted)


# -- what comes back ------------------------------------------------------------------------------------------------


async def test_opening_a_session_again_puts_its_level_back_in_force(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    first = runtime.session_id
    await _stored(runtime, first, effort="high")
    runtime.use_session(first)
    assert runtime.effort is ReasoningEffort.HIGH

    second = runtime.new_session()
    assert runtime.effort is runtime.default_effort, "a new session does not inherit the last one's"

    runtime.use_session(first)
    assert runtime.effort is ReasoningEffort.HIGH, "and the one that reasoned at high is still high"
    assert second != first


async def test_a_session_that_never_chose_reasons_at_the_level_it_was_built_with(tmp_path: Path, monkeypatch):
    started_high = _runtime(tmp_path, monkeypatch, started_at=ReasoningEffort.HIGH)
    await _stored(started_high, "s1")
    await _stored(started_high, "s2", effort="low")

    started_high.use_session("s1")
    assert started_high.effort is ReasoningEffort.HIGH, "the level a run starts at"

    started_high.use_session("s2")
    assert started_high.effort is ReasoningEffort.LOW, "the session's own choice wins over the starting level"


async def test_a_level_a_newer_version_wrote_is_ignored_rather_than_fatal(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    await _stored(runtime, "s1", effort="time-travel")

    runtime.use_session("s1")

    assert runtime.effort is runtime.default_effort


async def test_a_stored_level_moves_to_the_nearest_one_the_model_takes(tmp_path: Path, monkeypatch):
    """A configuration that narrowed ``reasoning_efforts`` must not send a level its endpoint rejects."""
    runtime = _runtime(tmp_path, monkeypatch, levels=(ReasoningEffort.LOW, ReasoningEffort.MEDIUM))
    await _stored(runtime, "s1", effort="ultra")

    runtime.use_session("s1")

    assert runtime.effort is ReasoningEffort.MEDIUM, "the closest of the two this model takes"
    assert _recorded(runtime, "s1") == "ultra", "adopting it does not rewrite what the session decided"


async def test_a_session_is_read_once_and_remembered(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    await _stored(runtime, "s1", effort="high")
    runtime.use_session("s1")

    # Changing the file behind its back is not seen again: the process that holds the lock is the writer.
    store = SessionStore(runtime.config.store, runtime.config.workspace)
    store.set_effort("s1", "low", default=runtime.default_effort.value)
    runtime.use_session("s1")

    assert runtime.effort is ReasoningEffort.HIGH


async def test_a_session_recorded_on_a_wider_model_comes_back_at_its_level(tmp_path: Path, monkeypatch):
    """The level is read against the model the session ran on, not against whichever one the shell is on now.

    Opening a session switches to its own model, but the level is put back first — so a level the *current* model
    cannot take would be moved down on the way in and never read again. It is read again after the switch.
    """
    narrow = ModelConfig(model="narrow", token="t", reasoning_efforts=(ReasoningEffort.LOW, ReasoningEffort.MEDIUM))
    wide = ModelConfig(model="wide", token="t")
    runtime = _runtime(tmp_path, monkeypatch, models=(narrow, wide))
    store = SessionStore(runtime.config.store, runtime.config.workspace)
    await store.append("s1", "req", UserMessage(content="hello"))
    store.set_model("s1", "wide")
    store.set_effort("s1", "high", default=runtime.default_effort.value)
    assert runtime.active_model is not None and runtime.active_model.shown_name == "narrow"

    from zettcode.app.agent.agent import TerminalAgent

    agent = TerminalAgent(runtime)
    agent.restore_session("s1")

    assert agent.active_model is not None and agent.active_model.shown_name == "wide", "the session's own model"
    assert agent.effort == "high", "and the level it ran at on that model"


async def test_a_level_chosen_for_this_run_wins_over_what_a_session_remembers(tmp_path: Path, monkeypatch):
    """``effort=`` is about this process, so opening a session does not undo it."""
    runtime = _runtime(tmp_path, monkeypatch)
    await _stored(runtime, "s1", effort="low")
    await _stored(runtime, "s2", effort="medium")

    runtime.use_effort("ultra", remember=False)
    runtime.use_session("s1")

    assert runtime.effort is ReasoningEffort.ULTRA


def test_choosing_a_level_again_takes_the_run_level_back_to_the_session(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.use_effort("high", remember=False)

    runtime.use_effort("low")

    assert runtime._effort_override is False, "the session owns the level again"
    assert _recorded(runtime, runtime.session_id) == "low"


# -- the way the shell and the client reach it ----------------------------------------------------------------------


async def test_the_effort_command_remembers_it_and_resuming_restores_it(tmp_path: Path, monkeypatch):
    """Through the agent the shell drives, the way `/effort` does."""
    from zettcode.app.agent.agent import TerminalAgent

    runtime = _runtime(tmp_path, monkeypatch)
    agent = TerminalAgent(runtime)
    session = runtime.session_id
    await _stored(runtime, session)

    agent.use_effort("high")
    assert _recorded(runtime, session) == "high"

    agent.new_session()
    assert agent.effort == runtime.default_effort.value

    agent.use_session(session)
    assert agent.effort == "high"
