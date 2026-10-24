"""The lock where it is used: a runtime holds the lock of the session it is in, and a locked agent writes nothing.

Two runtimes over one store stand in for two terminals: the operating system cannot tell them from two processes.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from zett_agent.messages import AssistantMessage, UserMessage

from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine import core as runtime_module
from zettcode.engine.storage import LOCK_FILE, LOCKED_MESSAGE, STORE_FILE, SessionLocked, SessionStore


def _runtime(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(runtime_module.os, "chdir", lambda path: None)
    (tmp_path / "work").mkdir(exist_ok=True)
    config = ZettCodeConfig(
        workspace=tmp_path / "work",
        models=(ModelConfig(model="m", token="t"),),
        store=tmp_path / "sessions",
        mcp_config=tmp_path / "absent-mcp.json",
        sessions_enabled=False,
    )
    return runtime_module.ZettCodeEngine.preview(config)


async def _stored(runtime, session_id: str) -> None:
    """Give a session a conversation on disk, as a process that had worked in it would have."""
    store = SessionStore(runtime.config.store, runtime.config.workspace)
    await store.append(session_id, "req", UserMessage(content="hello"))
    await store.append(session_id, "req", AssistantMessage(content="hi there"))


@pytest.fixture
def pair(tmp_path, monkeypatch):
    """Two terminals on one store: the first owns its session, the second has not opened anything yet."""
    first = _runtime(tmp_path, monkeypatch)
    second = _runtime(tmp_path, monkeypatch)
    yield first, second
    first.session_locks.release()
    second.session_locks.release()


# -- who holds what ------------------------------------------------------------------------------------------------


def test_a_launch_starts_in_a_new_session_and_holds_its_lock(pair):
    first, _ = pair

    assert first.session_locks.holds(first.session_id) and first.session_locked is False
    assert (first.persistence.session_dir(first.session_id) / LOCK_FILE).is_file()


def test_two_launches_never_share_a_session_so_neither_is_locked(pair):
    first, second = pair

    assert first.session_id != second.session_id
    assert not first.session_locked and not second.session_locked


def test_a_new_session_is_held_and_the_one_left_is_let_go(pair):
    first, second = pair
    old = first.session_id

    new = first.new_session()

    assert first.session_locks.holds(new) and not first.session_locks.holds(old)
    assert second.session_locks.claim(old) is True, "the session that was left is anybody's"


def test_resuming_a_session_another_process_has_open_selects_it_and_says_it_is_locked(pair):
    first, second = pair

    second.use_session(first.session_id)

    assert second.session_id == first.session_id, "it is shown: reading is harmless"
    assert second.session_locked is True
    assert first.session_locked is False


def test_resuming_a_session_nobody_has_open_takes_its_lock(pair):
    first, second = pair
    left = first.session_id
    first.new_session()

    second.use_session(left)

    assert second.session_locked is False and second.session_locks.holds(left)


def test_resuming_the_session_already_open_here_is_no_change(pair):
    first, _ = pair

    first.use_session(first.session_id)

    assert first.session_locked is False


def test_moving_from_a_locked_session_to_a_free_one_lets_go_of_nothing_it_did_not_hold(pair):
    first, second = pair
    second.use_session(first.session_id)
    assert second.session_locked

    second.new_session()

    assert not second.session_locked and first.session_locks.holds(first.session_id)


def test_the_lock_is_retaken_when_the_other_process_lets_go(pair):
    first, second = pair
    second.use_session(first.session_id)
    assert second.retake_session() is False

    first.session_locks.release()

    assert second.retake_session() is True and not second.session_locked


@pytest.mark.asyncio
async def test_closing_the_runtime_lets_go_of_the_session(pair):
    first, second = pair
    kept = first.session_id
    await _stored(first, kept)

    await first.aclose()

    assert second.session_locks.claim(kept) is True


@pytest.mark.asyncio
async def test_a_launch_closed_without_a_word_leaves_no_session_on_disk(pair):
    first, _ = pair
    folder = first.persistence.session_dir(first.session_id)
    assert folder.is_dir()

    await first.aclose()

    assert not folder.exists()


# -- a locked agent writes nothing ---------------------------------------------------------------------------------


@pytest.fixture
async def locked_agent(pair):
    """An agent in a session whose conversation is on disk and whose lock the other terminal holds."""
    first, second = pair
    await _stored(first, first.session_id)
    second.use_session(first.session_id)
    return ZettCodeAgent(second), ZettCodeAgent(first)


def test_the_agent_says_whether_its_session_is_the_others(locked_agent):
    locked, owner = locked_agent

    assert locked.session_locked is True and owner.session_locked is False


def test_the_guard_raises_a_value_error_that_says_why(locked_agent):
    locked, owner = locked_agent

    with pytest.raises(SessionLocked, match="read-only") as refused:
        locked.require_session()
    assert isinstance(refused.value, ValueError) and str(refused.value) == LOCKED_MESSAGE
    owner.require_session()


@pytest.mark.asyncio
async def test_a_turn_is_refused_before_anything_starts(locked_agent):
    locked, _ = locked_agent

    with pytest.raises(SessionLocked):
        async for _ in locked.stream(("do something",)):
            pass


@pytest.mark.asyncio
async def test_a_side_question_is_refused_too_because_the_store_records_it(locked_agent):
    locked, _ = locked_agent

    with pytest.raises(SessionLocked):
        async for _ in locked.stream(("what is this?",), side=True):
            pass


@pytest.mark.asyncio
async def test_naming_the_session_by_hand_is_refused_and_writes_no_title(locked_agent):
    locked, owner = locked_agent

    with pytest.raises(SessionLocked):
        await locked.rename_session("Taken over")

    assert owner.runtime.persistence.session_title(owner.session_id) is None


@pytest.mark.asyncio
async def test_compacting_is_refused(locked_agent):
    locked, _ = locked_agent

    with pytest.raises(SessionLocked):
        await locked.compact()


@pytest.mark.asyncio
async def test_the_background_title_is_never_asked_for_a_session_that_is_not_ours(locked_agent):
    locked, owner = locked_agent

    assert await locked.title_session(locked.session_id) is None
    assert owner.runtime.persistence.session_title(owner.session_id) is None


@pytest.mark.asyncio
async def test_reading_the_locked_session_is_allowed_and_it_is_the_whole_conversation(locked_agent, tmp_path):
    from zettcode.app.agent.conversation.transcript import Transcript

    locked, _ = locked_agent

    stored = locked.load_session(locked.session_id, Transcript())

    assert [entry.text for entry in stored.replayed.transcript.entries if getattr(entry, "text", "")][:2] == [
        "hello",
        "hi there",
    ]


@pytest.mark.asyncio
async def test_forking_a_locked_session_is_the_way_out_and_the_fork_is_ours(locked_agent):
    locked, owner = locked_agent

    forked = locked.fork_session()
    locked.use_session(forked)

    assert forked != owner.session_id
    assert not locked.session_locked and locked.runtime.session_locks.holds(forked)
    assert (locked.runtime.persistence.session_dir(forked) / STORE_FILE).exists()


def test_once_the_other_process_lets_go_the_agent_may_write_again(locked_agent):
    locked, owner = locked_agent
    owner.runtime.session_locks.release()

    assert locked.retake_session() is True
    locked.require_session()


# -- the whole thing, with a real second process -------------------------------------------------------------------

OWNER = """
import sys, time
from pathlib import Path
from zett_agent.messages import AssistantMessage, UserMessage
import asyncio
from zettcode.engine.storage import SessionLocks, SessionStore

store = SessionStore(Path(sys.argv[1]) / "sessions", Path(sys.argv[1]) / "work")
async def main():
    await store.append(sys.argv[2], "req", UserMessage(content="written by the other terminal"))
    await store.append(sys.argv[2], "req", AssistantMessage(content="and answered there"))
asyncio.run(main())
locks = SessionLocks(store.session_dir)
print("held" if locks.claim(sys.argv[2]) else "refused", flush=True)
time.sleep(120)
"""


@pytest.mark.skipif(os.name == "nt", reason="process signals")
@pytest.mark.asyncio
async def test_a_session_open_in_a_real_other_process_is_locked_here_until_that_process_dies(tmp_path, monkeypatch):
    import subprocess
    import sys

    (tmp_path / "work").mkdir()
    owner = subprocess.Popen([sys.executable, "-c", OWNER, str(tmp_path), A_ID], stdout=subprocess.PIPE, text=True)
    assert owner.stdout is not None and owner.stdout.readline().strip() == "held"
    runtime = _runtime(tmp_path, monkeypatch)
    try:
        runtime.use_session(A_ID)
        agent = ZettCodeAgent(runtime)

        assert agent.session_locked is True
        with pytest.raises(SessionLocked):
            agent.require_session()

        owner.kill()
        owner.wait(timeout=10)

        assert agent.retake_session() is True
        agent.require_session()
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait()
        runtime.session_locks.release()


A_ID = "01a10b75-aaaa-7000-8000-000000000001"
