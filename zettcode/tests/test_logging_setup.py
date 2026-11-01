"""The standard-logging setup shared by the three long-running processes."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from zettcode import logging_setup


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_setup_writes_one_json_object_with_extra_fields(tmp_path: Path):
    path = tmp_path / "tui.jsonl"
    logger = logging_setup.setup("terminal", path=path)

    logger.info("turn.start", extra={"session": "01abc", "seconds": 1.25})

    (record,) = _records(path)
    assert record["level"] == "info"
    assert record["logger"] == "zettcode.terminal"
    assert record["event"] == "turn.start"
    assert record["session"] == "01abc"
    assert record["seconds"] == 1.25
    assert record["pid"] > 0


def test_logger_exception_keeps_the_traceback(tmp_path: Path):
    path = tmp_path / "gateway.jsonl"
    logger = logging_setup.setup("gateway", path=path)

    try:
        raise RuntimeError("the socket closed")
    except RuntimeError:
        logger.exception("request.failed", extra={"route": "/messages"})

    (record,) = _records(path)
    assert record["level"] == "error"
    assert record["route"] == "/messages"
    assert "RuntimeError: the socket closed" in str(record["traceback"])


def test_rotation_bounds_the_file_and_keeps_the_requested_backups(tmp_path: Path, monkeypatch):
    path = tmp_path / "terminal.jsonl"
    monkeypatch.setenv("ZETTCODE_LOG_MAX_BYTES", "700")
    monkeypatch.setenv("ZETTCODE_LOG_BACKUPS", "2")
    logger = logging_setup.setup("terminal", path=path)

    for index in range(8):
        logger.info("turn.start", extra={"index": index, "padding": "x" * 100})

    assert path.exists()
    assert path.with_name("terminal.jsonl.1").exists()
    assert not path.with_name("terminal.jsonl.3").exists()


def test_the_level_environment_drops_lower_events(tmp_path: Path, monkeypatch):
    path = tmp_path / "gateway.jsonl"
    monkeypatch.setenv("ZETTCODE_LOG_LEVEL", "warning")
    logger = logging_setup.setup("gateway", path=path)

    logger.debug("request")
    logger.error("start.failed")

    (record,) = _records(path)
    assert record["event"] == "start.failed"


def test_a_log_that_cannot_be_opened_does_not_reach_the_caller(tmp_path: Path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    logger = logging_setup.setup("terminal", path=blocker / "tui.jsonl")
    logger.error("start.failed")


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX file modes")
def test_a_diagnostic_file_and_its_folder_are_owner_only(tmp_path: Path):
    path = tmp_path / "logs" / "terminal.jsonl"
    logger = logging_setup.setup("terminal", path=path)

    logger.info("start")

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_the_documented_jsonl_paths_are_the_ones_the_program_uses():
    home = Path.home() / ".zettcode" / "log"

    assert logging_setup.log_path("terminal") == home / "terminal.jsonl"
    assert logging_setup.log_path("broker") == home / "broker.jsonl"
    assert logging_setup.log_path("gateway") == home / "gateway.jsonl"


def test_rotating_a_text_log_keeps_the_requested_backups(tmp_path: Path):
    path = tmp_path / "tui.log"
    path.write_text("x" * 100, encoding="utf-8")

    logging_setup.rotate_text(path, max_bytes=10, backups=2)

    assert not path.exists()
    assert path.with_name("tui.log.1").read_text(encoding="utf-8") == "x" * 100
    assert not path.with_name("tui.log.2").exists()
