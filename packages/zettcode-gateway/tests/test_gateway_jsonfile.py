"""The gateway's JSON files: a missing or damaged one reads as nothing, and a write is whole or absent."""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

from zettcode.gateway.jsonfile import read_json, write_json


def test_a_document_written_is_the_document_read(tmp_path: pathlib.Path):
    path = tmp_path / "state" / "one.json"
    write_json(path, {"名": ["a", 1]}, ensure_ascii=False)

    assert read_json(path) == {"名": ["a", 1]}
    assert "名" in path.read_text(encoding="utf-8")
    assert [item.name for item in path.parent.iterdir()] == ["one.json"], "no temporary file is left"


def test_a_missing_or_damaged_file_reads_as_nothing(tmp_path: pathlib.Path):
    assert read_json(tmp_path / "absent.json") is None
    damaged = tmp_path / "damaged.json"
    damaged.write_text("{not json", encoding="utf-8")
    assert read_json(damaged) is None
    assert read_json(tmp_path) is None, "a folder where a file should be is not a document"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
def test_a_private_file_is_readable_by_its_owner_only_even_over_an_older_temporary(tmp_path: pathlib.Path):
    path = tmp_path / "secret.json"
    leftover = tmp_path / f".secret.json.{os.getpid()}.tmp"
    leftover.write_text("old", encoding="utf-8")
    leftover.chmod(0o644)

    write_json(path, {"token": "x"}, private=True)

    assert path.stat().st_mode & 0o777 == 0o600


def test_a_write_that_fails_leaves_the_old_document_and_no_temporary(tmp_path: pathlib.Path):
    path = tmp_path / "keep.json"
    write_json(path, {"v": 1})

    with pytest.raises(TypeError):
        write_json(path, {"v": object()})

    assert read_json(path) == {"v": 1}
    assert [item.name for item in tmp_path.iterdir()] == ["keep.json"]
