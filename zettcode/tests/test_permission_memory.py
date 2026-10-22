"""The permission level a session was last run at comes back with it.

The level is per session, not per process and not per configuration: opening a session again puts back what that
conversation was last run under, a new session starts at the default, and a level equal to the default is not written
down at all — a session that holds no level is one that behaves that way.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from zett_agent.extensions.shell_approval import ShellApprovalMode
from zett_agent.messages import AssistantMessage, UserMessage

from zettcode.app.agent import runtime as runtime_module
from zettcode.app.agent.permission import Permission
from zettcode.app.agent.storage import SessionStore
from zettcode.app.agent.storage.metadata import SESSION_METADATA_FILE
from zettcode.config import ModelConfig, ZettCodeConfig


def _runtime(tmp_path: Path, monkeypatch, *, level: Permission = Permission.ASK):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    (tmp_path / "work").mkdir(exist_ok=True)
    config = ZettCodeConfig(
        workspace=tmp_path / "work",
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
        sessions_enabled=False,
        shell_approval=ShellApprovalMode.ALLOW_ALL if level is Permission.FULL else ShellApprovalMode.REVIEW,
    )
    return runtime_module.ZettCodeRuntime.preview(config)


async def _stored(runtime, session_id: str, *, permission: str | None = None) -> None:
    """Give a session a conversation on disk, and a level when one was recorded."""
    store = SessionStore(runtime.config.store, runtime.config.workspace)
    await store.append(session_id, "req", UserMessage(content="hello"))
    await store.append(session_id, "req", AssistantMessage(content="hi there"))
    if permission is not None:
        store.set_permission(session_id, permission, default=runtime.default_permission.value)


def _recorded(runtime, session_id: str) -> str | None:
    """Read the level written in a session's own metadata file, or ``None`` when it has none."""
    path = runtime.config.store / runtime.config.workspace.name / session_id / SESSION_METADATA_FILE
    for found in runtime.config.store.rglob(SESSION_METADATA_FILE):
        if found.parent.name == session_id:
            path = found
            break
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("permission")


# -- what is written ------------------------------------------------------------------------------------------------


def test_a_level_the_reader_chose_is_written_into_the_sessions_own_file(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    runtime.use_permission("safe")

    assert runtime.permission is Permission.SAFE
    assert _recorded(runtime, runtime.session_id) == "safe"


def test_the_level_a_run_starts_at_is_not_written_down(tmp_path: Path, monkeypatch):
    """A session that holds no level already behaves that way, so the file says nothing."""
    runtime = _runtime(tmp_path, monkeypatch)

    runtime.use_permission(runtime.default_permission.value)

    assert _recorded(runtime, runtime.session_id) is None


def test_going_back_to_the_default_takes_the_recorded_level_away(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.use_permission("full")

    runtime.use_permission(runtime.default_permission.value)

    assert _recorded(runtime, runtime.session_id) is None


def test_a_level_chosen_for_the_run_at_launch_is_not_written_into_the_session(tmp_path: Path, monkeypatch):
    """`--full` says "this run", so the session keeps whatever level it had."""
    runtime = _runtime(tmp_path, monkeypatch)

    runtime.approve_all_shell_commands()

    assert runtime.permission is Permission.FULL
    assert _recorded(runtime, runtime.session_id) is None


# -- what comes back --------------------------------------------------------------------------------------------------


async def test_opening_a_session_again_puts_its_level_back_in_force(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    first = runtime.session_id
    await _stored(runtime, first, permission="full")
    runtime.use_session(first)
    assert runtime.permission is Permission.FULL

    second = runtime.new_session()
    assert runtime.permission is runtime.default_permission, "a new session does not inherit the last one's"

    runtime.use_session(first)
    assert runtime.permission is Permission.FULL, "and the one that chose full is still full"
    assert second != first


async def test_a_session_that_never_chose_runs_at_the_default_it_was_built_with(tmp_path: Path, monkeypatch):
    started_full = _runtime(tmp_path, monkeypatch, level=Permission.FULL)
    await _stored(started_full, "s1")
    await _stored(started_full, "s2", permission="ask")

    started_full.use_session("s1")
    assert started_full.permission is Permission.FULL

    started_full.use_session("s2")
    assert started_full.permission is Permission.ASK, "the session's own choice wins over the starting level"


async def test_a_level_a_newer_version_wrote_is_ignored_rather_than_fatal(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    await _stored(runtime, "s1", permission="time-travel")

    runtime.use_session("s1")

    assert runtime.permission is runtime.default_permission


async def test_a_session_is_read_once_and_remembered(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    await _stored(runtime, "s1", permission="safe")
    runtime.use_session("s1")

    # Changing the file behind its back is not seen again: the process that holds the lock is the writer.
    store = SessionStore(runtime.config.store, runtime.config.workspace)
    store.set_permission("s1", "full", default="ask")
    runtime.use_session("s1")

    assert runtime.permission is Permission.SAFE


async def test_a_level_chosen_for_this_run_wins_over_what_a_session_remembers(tmp_path: Path, monkeypatch):
    """`--full` and a client's own `permission=` are about this process, so opening a session does not undo them."""
    runtime = _runtime(tmp_path, monkeypatch)
    await _stored(runtime, "s1", permission="ask")
    await _stored(runtime, "s2", permission="safe")

    runtime.use_permission("full", remember=False)
    runtime.use_session("s1")

    assert runtime.permission is Permission.FULL


def test_the_command_takes_the_run_level_back_to_the_session(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    runtime.use_permission("full", remember=False)

    runtime.use_permission("safe")

    assert runtime._permission_override is False, "the session owns the level again"


# -- the shell --------------------------------------------------------------------------------------------------------


async def test_the_permission_command_remembers_it_and_resuming_restores_it(tmp_path: Path, monkeypatch):
    """Through the agent the shell drives, the way `/permission` does."""
    from zettcode.app.agent.agent import ZettCodeAgent

    runtime = _runtime(tmp_path, monkeypatch)
    agent = ZettCodeAgent(runtime)
    session = runtime.session_id
    await _stored(runtime, session)

    agent.use_permission("safe")
    assert _recorded(runtime, session) == "safe"

    agent.new_session()
    assert agent.permission is runtime.default_permission

    agent.use_session(session)
    assert agent.permission is Permission.SAFE


@pytest.mark.parametrize("name", ["safe", "full", "deny"])
async def test_every_level_can_be_remembered(name: str, tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)
    session = runtime.session_id

    runtime.use_permission(name)

    assert _recorded(runtime, session) == name
    runtime.new_session()
    runtime.use_session(session)
    assert runtime.permission.value == name
