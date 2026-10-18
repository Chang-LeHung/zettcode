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
    in_background,
    installed_version,
    is_newer,
    read_state,
    record_install,
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


def test_an_answer_that_arrives_after_the_loop_closed_is_dropped_quietly(monkeypatch):
    """The thread is left behind when the session ends, so its answer can come too late.

    ``call_soon_threadsafe`` raises once the loop is closed, and a daemon thread that
    raises prints a traceback — which, while the interpreter is shutting down, can abort
    the whole process (exit code 134, seen on CI). Nobody is waiting for the answer any
    more, so it is dropped: the thread ends without raising.
    """
    release = threading.Event()
    raised: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: raised.append(args.exc_value))
    loop = asyncio.new_event_loop()

    async def start() -> asyncio.Task:
        task = asyncio.ensure_future(in_background(lambda: (release.wait(5.0), "late")[1]))
        await asyncio.sleep(0.02)  # the thread is running, and waiting on the event
        return task

    task = loop.run_until_complete(start())
    task.cancel()
    loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
    loop.close()
    thread = next(thread for thread in threading.enumerate() if thread.name == "zettcode-background")

    release.set()
    thread.join(5.0)

    assert not thread.is_alive(), "the thread finished"
    assert raised == [], "and did not raise on its way out"


def test_a_failure_that_arrives_after_the_loop_closed_is_dropped_quietly(monkeypatch):
    """The same for a check that failed: reporting the error is as unwanted as the answer."""
    release = threading.Event()
    raised: list[BaseException] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: raised.append(args.exc_value))
    loop = asyncio.new_event_loop()

    def fails() -> str:
        release.wait(5.0)
        raise OSError("the index could not be reached")

    async def start() -> asyncio.Task:
        task = asyncio.ensure_future(in_background(fails))
        await asyncio.sleep(0.02)
        return task

    task = loop.run_until_complete(start())
    task.cancel()
    loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
    loop.close()
    thread = next(thread for thread in threading.enumerate() if thread.name == "zettcode-background")

    release.set()
    thread.join(5.0)

    assert not thread.is_alive() and raised == []


# -- recognising a uv tool environment --------------------------------------------------------------------------


def _fake_environment(tmp_path: Path, monkeypatch, *, receipt: bool, named_like_a_tool: bool) -> Path:
    """An interpreter path that is a link to another one, as every virtual environment's ``python`` is."""
    inside = tmp_path / "uv" / "tools" / "zettcode" if named_like_a_tool else tmp_path / "venvs" / "zettcode"
    (inside / "bin").mkdir(parents=True)
    link = inside / "bin" / "python"
    link.symlink_to(Path(sys.executable).resolve())
    if receipt:
        (inside / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(link))
    monkeypatch.setattr(sys, "prefix", str(inside))
    return link


@pytest.mark.skipif(sys.platform == "win32", reason="links need privileges there")
def test_a_uv_tool_environment_is_recognised_although_its_python_is_a_link_elsewhere(tmp_path, monkeypatch):
    """The bug: the path was resolved, which names the interpreter the environment was built from."""
    link = _fake_environment(tmp_path, monkeypatch, receipt=False, named_like_a_tool=True)

    assert "tools" not in link.resolve().parts, "resolving it loses the directory that says what it is"
    assert update.installed_by_uv_tool() is True


@pytest.mark.skipif(sys.platform == "win32", reason="links need privileges there")
def test_the_receipt_uv_leaves_is_what_decides_wherever_the_tools_directory_was_put(tmp_path, monkeypatch):
    _fake_environment(tmp_path, monkeypatch, receipt=True, named_like_a_tool=False)

    assert update.installed_by_uv_tool() is True


@pytest.mark.skipif(sys.platform == "win32", reason="links need privileges there")
def test_an_ordinary_environment_is_not_taken_for_a_uv_tool(tmp_path, monkeypatch):
    _fake_environment(tmp_path, monkeypatch, receipt=False, named_like_a_tool=False)

    assert update.installed_by_uv_tool() is False


@pytest.mark.skipif(sys.platform == "win32", reason="links need privileges there")
def test_a_uv_tool_environment_is_upgraded_with_uv_and_never_with_a_pip_it_does_not_have(tmp_path, monkeypatch):
    _fake_environment(tmp_path, monkeypatch, receipt=True, named_like_a_tool=True)
    monkeypatch.setattr(update, "which", lambda name: "/usr/local/bin/uv")

    assert upgrade_command() == ("uv", "tool", "upgrade", "zettcode")


# -- what an upgrade installed, read back and written down -------------------------------------------------------


def _interpreter(tmp_path: Path, body: str) -> str:
    """A stand-in interpreter: a script that ignores its arguments and runs ``body``."""
    script = tmp_path / "fake-python"
    script.write_text(f"#!{sys.executable}\n{body}\n", encoding="utf-8")
    script.chmod(0o755)
    return str(script)


async def test_the_installed_version_is_read_from_a_fresh_process():
    import importlib.metadata

    assert await installed_version() == importlib.metadata.version("zettcode")


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in is a shell script")
async def test_the_last_line_is_the_version_so_a_banner_before_it_does_not_matter(tmp_path):
    executable = _interpreter(tmp_path, "print('warning: something noisy')\nprint('0.4.2')\nprint()")

    assert await installed_version(executable) == "0.4.2"


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in is a shell script")
@pytest.mark.parametrize(
    "body",
    [
        "raise SystemExit(3)",
        "print()",
        "import sys; sys.stderr.write('boom'); sys.exit(1)",
        # It printed a version and then died: a half-finished answer is not an answer.
        "print('0.9.9'); raise SystemExit(1)",
    ],
)
async def test_a_probe_that_fails_or_says_nothing_is_unconfirmed_not_unchanged(tmp_path, body):
    assert await installed_version(_interpreter(tmp_path, body)) is None


async def test_an_interpreter_that_does_not_exist_is_unconfirmed():
    assert await installed_version("/nonexistent/python") is None


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in is a shell script")
async def test_the_probe_runs_away_from_the_workspace_so_a_stray_package_there_cannot_answer(tmp_path):
    import tempfile

    executable = _interpreter(tmp_path, "import os; print(os.getcwd())")

    assert Path(await installed_version(executable)).resolve() == Path(tempfile.gettempdir()).resolve()


def test_a_recorded_install_is_written_beside_what_the_last_check_found(tmp_path):
    path = tmp_path / "update.json"
    write_state(UpdateState(checked_at=NOON, latest="0.2.0", skipped="0.1.9"), path)

    record_install(path, "0.2.0")

    state = read_state(path)
    assert (state.installed, state.installed_by) == ("0.2.0", sys.executable)
    assert (state.checked_at, state.latest, state.skipped) == (NOON, "0.2.0", "0.1.9")


def test_a_recorded_install_with_no_state_file_yet_creates_one(tmp_path):
    path = tmp_path / "deep" / "update.json"

    record_install(path, "0.2.0", executable="/venv/bin/python")

    assert read_state(path) == UpdateState(installed="0.2.0", installed_by="/venv/bin/python")


def test_a_new_install_forgets_an_explanation_given_about_the_old_one(tmp_path):
    path = tmp_path / "update.json"
    write_state(UpdateState(installed="0.2.0", installed_by=sys.executable, noted="0.2.0"), path)

    record_install(path, "0.3.0")

    assert read_state(path).noted is None, "a different mismatch deserves its own explanation"


def test_the_new_fields_round_trip_and_an_old_file_without_them_still_reads(tmp_path):
    path = tmp_path / "update.json"
    state = UpdateState(checked_at=NOON, latest="0.2.0", installed="0.2.0", installed_by="/v/python", noted="0.2.0")
    write_state(state, path)
    assert read_state(path) == state

    path.write_text(json.dumps({"checked_at": NOON.isoformat(), "latest": "0.2.0", "skipped": None}), encoding="utf-8")
    assert read_state(path) == UpdateState(checked_at=NOON, latest="0.2.0")


def test_a_confirmed_install_newer_than_what_runs_is_not_offered_again_in_that_interpreter():
    state = UpdateState(latest="0.2.0", installed="0.2.0", installed_by="/v/python")

    assert state.shadowed_by("0.1.5", "/v/python") == "0.2.0"
    assert state.offer("0.1.5", "/v/python") is None


def test_it_is_still_offered_to_an_interpreter_that_was_not_the_one_upgraded():
    state = UpdateState(latest="0.2.0", installed="0.2.0", installed_by="/v/python")

    assert state.shadowed_by("0.1.5", "/another/python") is None
    assert state.offer("0.1.5", "/another/python") == "0.2.0"


def test_nothing_is_shadowed_once_the_running_version_has_caught_up():
    state = UpdateState(latest="0.2.0", installed="0.2.0", installed_by="/v/python")

    assert state.shadowed_by("0.2.0", "/v/python") is None
    assert state.offer("0.2.0", "/v/python") is None, "and it is not newer, so there is nothing to say either"


def test_a_release_newer_than_the_recorded_install_is_offered_once_the_copy_is_not_shadowed():
    state = UpdateState(latest="0.3.0", installed="0.2.0", installed_by="/v/python")

    assert state.shadowed_by("0.2.0", "/v/python") is None
    assert state.offer("0.2.0", "/v/python") == "0.3.0"


def test_a_skipped_version_stays_skipped_whatever_was_installed():
    state = UpdateState(latest="0.3.0", skipped="0.3.0", installed="0.1.0", installed_by="/v/python")

    assert state.offer("0.1.0", "/v/python") is None
