"""The structured diagnostic lines a support report can be read from."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from zettcode import diagnostics
from zettcode.broker.files import broker_dir
from zettcode.broker.files import log_path as broker_log_path
from zettcode.gateway.runfile import log_path as gateway_log_path
from zettcode.gateway.settings import default_directory
from zettcode.paths import DEFAULT_LOG


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_file_event_is_one_json_line_with_the_safe_fields(tmp_path: Path):
    path = tmp_path / "nested" / "terminal.log"

    diagnostics.write("terminal", "turn.failed", path=path, session="01abc", seconds=1.25)

    (record,) = _records(path)
    assert record["component"] == "terminal"
    assert record["event"] == "turn.failed"
    assert record["level"] == "info"
    assert record["session"] == "01abc"
    assert record["seconds"] == 1.25
    assert record["pid"] > 0
    assert record["time"].endswith("+00:00")


def test_an_exception_carries_its_type_message_and_traceback(tmp_path: Path):
    path = tmp_path / "broker.log"

    try:
        raise RuntimeError("the socket closed")
    except RuntimeError as error:
        diagnostics.exception("broker", "request.failed", error, path=path, method="POST", route="/messages")

    (record,) = _records(path)
    assert record["level"] == "error"
    assert record["error"] == {"type": "RuntimeError", "message": "the socket closed"}
    assert "RuntimeError: the socket closed" in str(record["traceback"])
    assert record["method"] == "POST"
    assert record["route"] == "/messages"


def test_a_log_that_cannot_be_written_does_not_reach_the_caller(tmp_path: Path, capsys):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    diagnostics.write("terminal", "start", path=blocker / "tui.log", session="s")

    assert capsys.readouterr().err == "", "a failed file write must not fall back onto the screen"


def test_a_stderr_event_is_one_json_line_when_no_path_is_named(capsys):
    diagnostics.write("broker", "listening", session="s", port=1234)

    record = json.loads(capsys.readouterr().err)
    assert record["component"] == "broker"
    assert record["event"] == "listening"
    assert record["port"] == 1234


def test_a_field_json_cannot_sort_is_still_written(tmp_path: Path):
    path = tmp_path / "tui.log"

    diagnostics.write("terminal", "start", path=path, mixed={1: "one", "two": 2})

    (record,) = _records(path)
    assert record["mixed"] == {"1": "one", "two": 2}


def test_an_exception_whose_str_raises_is_still_recorded(tmp_path: Path):
    path = tmp_path / "broker.log"

    class Unprintable(Exception):
        def __str__(self) -> str:
            raise RuntimeError("no text")

    try:
        raise Unprintable()
    except Unprintable as error:
        diagnostics.exception("broker", "request.failed", error, path=path)

    (record,) = _records(path)
    assert record["error"] == {"type": "Unprintable", "message": "<unprintable Unprintable>"}


def test_the_documented_log_paths_are_the_ones_the_program_uses(monkeypatch):
    monkeypatch.delenv("ZETTCODE_BROKER_DIR", raising=False)
    monkeypatch.delenv("ZETTCODE_GATEWAY_DIR", raising=False)
    home = Path.home() / ".zettcode"

    assert DEFAULT_LOG == home / "log" / "tui.log"
    assert broker_log_path(broker_dir()) == home / "broker" / "broker.log"
    assert gateway_log_path(default_directory()) == home / "gateway" / "gateway.log"


@pytest.mark.skipif(os.name == "nt", reason="Windows does not expose POSIX file modes")
def test_a_diagnostic_file_and_its_folder_are_owner_only(tmp_path: Path):
    path = tmp_path / "logs" / "tui.log"

    diagnostics.write("terminal", "start", path=path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_huge_exception_is_capped(tmp_path: Path):
    path = tmp_path / "broker.log"

    try:
        raise RuntimeError("x" * (diagnostics.MAX_MESSAGE + 500))
    except RuntimeError as error:
        diagnostics.exception("broker", "request.failed", error, path=path)

    (record,) = _records(path)
    assert len(record["error"]["message"]) <= diagnostics.MAX_MESSAGE
    assert len(record["traceback"]) <= diagnostics.MAX_TRACEBACK


def test_a_deep_traceback_keeps_the_failure_at_the_end(tmp_path: Path, monkeypatch):
    path = tmp_path / "broker.log"
    monkeypatch.setattr(diagnostics, "MAX_TRACEBACK", 200)

    def deep(remaining: int) -> None:
        if remaining:
            deep(remaining - 1)
            return
        raise ZeroDivisionError("division by zero")

    try:
        deep(60)
    except ZeroDivisionError as error:
        diagnostics.exception("broker", "request.failed", error, path=path)

    (record,) = _records(path)
    trace = str(record["traceback"])
    assert len(trace) <= diagnostics.MAX_TRACEBACK
    assert "<traceback truncated>" in trace
    assert trace.rstrip().endswith("ZeroDivisionError: division by zero")


def test_a_refusal_omits_the_empty_traceback(tmp_path: Path):
    path = tmp_path / "terminal.log"

    try:
        raise ValueError("nothing to compact")
    except ValueError as error:
        diagnostics.exception("terminal", "command.refused", error, path=path, level="warning", trace=False)

    (record,) = _records(path)
    assert record["level"] == "warning"
    assert "traceback" not in record
