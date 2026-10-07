"""The release check: what it stores, what it offers, and what it never does."""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zettcode import update
from zettcode.update import (
    UpdateState,
    check_for_update,
    display_command,
    fetch_latest,
    is_newer,
    read_state,
    run_upgrade,
    upgrade_command,
    write_state,
)

NOON = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("candidate", "current", "newer"),
    [
        ("0.1.3", "0.1.2", True),
        # Releases are not decimals: 1.10 is after 1.9.
        ("0.1.10", "0.1.9", True),
        ("0.2.0", "0.1.99", True),
        ("1.0.0", "0.9.9", True),
        ("0.1.2", "0.1.2", False),
        ("0.1.1", "0.1.2", False),
        ("v0.1.3", "0.1.2", True),
        # A release candidate never outranks the release it leads to.
        ("0.2.0rc1", "0.2.0", False),
    ],
)
def test_versions_compare_the_way_releases_do(candidate, current, newer):
    assert is_newer(candidate, current) is newer


def test_a_missing_or_unusable_file_reads_as_nothing(tmp_path: Path):
    path = tmp_path / "update.json"

    assert read_state(path) == UpdateState()

    path.write_text("{", encoding="utf-8")
    assert read_state(path) == UpdateState()

    path.write_text('["not", "an", "object"]', encoding="utf-8")
    assert read_state(path) == UpdateState()

    path.write_text('{"latest": 7, "checked_at": "yesterday", "skipped": []}', encoding="utf-8")
    assert read_state(path) == UpdateState()


def test_the_state_round_trips_through_the_file(tmp_path: Path):
    path = tmp_path / "nested" / "update.json"
    state = UpdateState(checked_at=NOON, latest="0.1.3", skipped="0.1.2")

    write_state(state, path)

    assert read_state(path) == state
    assert json.loads(path.read_text(encoding="utf-8"))["latest"] == "0.1.3"


def test_a_stored_answer_is_trusted_for_a_day():
    moment = datetime.now(timezone.utc)

    assert UpdateState(checked_at=moment).stale is False
    assert UpdateState(checked_at=moment - timedelta(hours=25)).stale is True
    assert UpdateState().stale is True


def test_a_version_is_offered_only_when_it_is_newer_and_not_skipped():
    assert UpdateState(latest="0.1.3").offer("0.1.2") == "0.1.3"
    assert UpdateState(latest="0.1.2").offer("0.1.2") is None
    assert UpdateState(latest="0.1.1").offer("0.1.2") is None
    assert UpdateState(latest="0.1.3", skipped="0.1.3").offer("0.1.2") is None
    # A skip is for one version: the next release is offered again.
    assert UpdateState(latest="0.1.4", skipped="0.1.3").offer("0.1.2") == "0.1.4"


async def test_a_fresh_answer_does_not_ask_the_index_again(tmp_path: Path):
    path = tmp_path / "update.json"
    write_state(UpdateState(checked_at=datetime.now(timezone.utc), latest="0.1.1"), path)

    def refuse() -> str:  # pragma: no cover - only runs when the check is wrong
        raise AssertionError("a fresh answer was fetched again")

    assert await check_for_update(path, fetch=refuse) is None
    assert read_state(path).latest == "0.1.1"


async def test_a_stale_answer_is_fetched_and_stored(tmp_path: Path):
    path = tmp_path / "update.json"
    now = datetime.now(timezone.utc)

    state = await check_for_update(path, fetch=lambda: "0.1.9", now=lambda: now)

    assert state == UpdateState(checked_at=now, latest="0.1.9")
    assert read_state(path) == state
    # The skip survives a refresh: it names a version, not a check.
    write_state(UpdateState(checked_at=now - timedelta(days=2), latest="0.1.9", skipped="0.1.9"), path)
    refreshed = await check_for_update(path, fetch=lambda: "0.1.10", now=lambda: now)
    assert refreshed == UpdateState(checked_at=now, latest="0.1.10", skipped="0.1.9")


async def test_a_check_that_fails_says_nothing_and_changes_nothing(tmp_path: Path):
    path = tmp_path / "update.json"
    now = datetime.now(timezone.utc)
    stale = UpdateState(checked_at=now - timedelta(days=2), latest="0.1.5", skipped="0.1.4")
    write_state(stale, path)

    def offline() -> str:
        raise RuntimeError("no network")

    assert await check_for_update(path, fetch=offline, now=lambda: now) is None
    # Still stale, so the next start tries again rather than waiting out the day.
    assert read_state(path) == stale


def test_the_index_reader_uses_the_version_it_finds(tmp_path: Path):
    payload = tmp_path / "index.json"
    payload.write_text(json.dumps({"info": {"version": "0.1.9"}}), encoding="utf-8")

    assert fetch_latest(url=payload.as_uri()) == "0.1.9"

    payload.write_text(json.dumps({"info": {}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="without a version"):
        fetch_latest(url=payload.as_uri())

    with pytest.raises(RuntimeError, match="could not read"):
        fetch_latest(url=(tmp_path / "absent.json").as_uri())


def test_the_index_is_verified_against_the_system_trust_store():
    """A proxy in front of the index is normal; the bundled roots fail there."""
    import truststore

    context = update.ssl_context()

    assert isinstance(context, ssl.SSLContext)
    assert isinstance(context, truststore.SSLContext)


def test_the_upgrade_command_follows_the_installer(monkeypatch):
    monkeypatch.setattr(update, "installed_by_uv_tool", lambda: True)
    monkeypatch.setattr(update, "which", lambda name: "/usr/local/bin/uv")

    assert upgrade_command() == ("uv", "tool", "upgrade", "zettcode")

    # pip installed it, or uv is not on this machine: upgrade where we run.
    monkeypatch.setattr(update, "installed_by_uv_tool", lambda: False)
    assert upgrade_command() == (sys.executable, "-m", "pip", "install", "--upgrade", "zettcode")

    monkeypatch.setattr(update, "installed_by_uv_tool", lambda: True)
    monkeypatch.setattr(update, "which", lambda name: None)
    assert upgrade_command()[0] == sys.executable


def test_the_shown_command_is_the_one_a_reader_would_type():
    assert display_command(("uv", "tool", "upgrade", "zettcode")) == "uv tool upgrade zettcode"
    assert display_command(("/usr/bin/python3", "-m", "pip", "install", "--upgrade", "zettcode")) == (
        "pip install --upgrade zettcode"
    )
    # Anything else is shown as it will run, interpreter path and all.
    assert display_command(("/opt/venv/bin/zettcode-tool", "--upgrade")) == "/opt/venv/bin/zettcode-tool --upgrade"


async def test_the_upgrade_captures_its_output_and_reports_failure():
    ok, output = await run_upgrade((sys.executable, "-c", "print('installed')"))
    assert (ok, output) == (True, "installed")

    ok, output = await run_upgrade((sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"))
    assert ok is False
    assert output == "boom"

    ok, output = await run_upgrade(("/nonexistent/zettcode-upgrade",))
    assert ok is False
    assert output


async def test_a_background_call_does_not_block_the_loop():
    started = threading.Event()

    def work() -> str:
        started.set()
        time.sleep(0.05)
        return "answered"

    task = asyncio.ensure_future(update.in_background(work))
    await asyncio.sleep(0)

    assert started.wait(2.0)
    # The thread is asleep, and the loop is not waiting for it.
    assert task.done() is False
    assert await task == "answered"


async def test_a_background_call_hands_back_what_it_raised():
    def work() -> str:
        raise RuntimeError("no network")

    with pytest.raises(RuntimeError, match="no network"):
        await update.in_background(work)


async def test_cancelling_a_background_call_leaves_its_thread_alone():
    """The answer of a request nobody waits for must not become an error."""
    loop = asyncio.get_running_loop()
    failures: list[dict] = []
    loop.set_exception_handler(lambda _loop, context: failures.append(context))
    release = threading.Event()
    finished = threading.Event()

    def work() -> str:
        release.wait(3.0)
        finished.set()
        return "too late"

    task = asyncio.ensure_future(update.in_background(work))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    release.set()
    assert finished.wait(3.0)
    await asyncio.sleep(0.05)
    assert failures == []
