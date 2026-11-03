"""The record a serving gateway leaves: what stop reads, and what a restart keeps from it."""

from __future__ import annotations

import json
import os
from pathlib import Path

from zettcode.gateway import runfile
from zettcode.gateway.settings import Settings


def settings(tmp_path: Path) -> Settings:
    return Settings(
        token="secret",
        host="127.0.0.1",
        port=9123,
        roots=(tmp_path,),
        allow_full=False,
        directory=tmp_path / "gw",
        log_level="debug",
    )


def test_a_record_round_trips_and_is_readable_by_its_owner_only(tmp_path):
    made = settings(tmp_path)

    runfile.write(made)

    record = runfile.read(made.directory)
    assert record is not None and record.pid == os.getpid() and record.settings == made
    if os.name != "nt":
        assert runfile.path(made.directory).stat().st_mode & 0o777 == 0o600


def test_a_record_is_cleared_only_by_the_process_it_names(tmp_path):
    made = settings(tmp_path)
    runfile.write(made)

    assert runfile.clear(made.directory, pid=os.getpid() + 1) is False
    assert runfile.read(made.directory) is not None

    assert runfile.clear(made.directory, pid=os.getpid()) is True
    assert runfile.read(made.directory) is None


def test_a_record_cannot_send_a_restart_to_another_folder(tmp_path):
    made = settings(tmp_path)
    runfile.write(made)
    raw = json.loads(runfile.path(made.directory).read_text(encoding="utf-8"))
    raw["directory"] = str(tmp_path / "elsewhere")
    runfile.path(made.directory).write_text(json.dumps(raw), encoding="utf-8")

    record = runfile.read(made.directory)

    assert record is not None and record.settings.directory == made.directory


def test_a_damaged_record_is_no_record_and_can_still_be_cleared(tmp_path):
    made = settings(tmp_path)
    runfile.ensure_directory(made.directory)
    runfile.path(made.directory).write_text(json.dumps({"pid": "not a number", "port": 1}), encoding="utf-8")

    assert runfile.read(made.directory) is None
    assert runfile.clear(made.directory) is True
    assert not runfile.path(made.directory).exists()
