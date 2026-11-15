"""The gateway's JSON files: a missing or damaged one reads as nothing, and a write is whole or absent."""

from __future__ import annotations

import os
import pathlib
import sys
import threading

import pytest

from zettcode.gateway.jsonfile import read_json, write_json

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")


def test_a_document_written_is_the_document_read(tmp_path: pathlib.Path):
    path = tmp_path / "state" / "one.json"
    write_json(path, {"名": ["a", 1]}, ensure_ascii=False)

    assert read_json(path) == {"名": ["a", 1]}
    assert "名" in path.read_text(encoding="utf-8")
    assert [item.name for item in path.parent.iterdir()] == ["one.json"], "no temporary file is left"


def test_ascii_is_escaped_and_a_document_is_indented_only_when_asked(tmp_path: pathlib.Path):
    plain, spaced = tmp_path / "plain.json", tmp_path / "spaced.json"
    write_json(plain, {"名": 1})
    write_json(spaced, {"a": 1}, indent=1)

    assert plain.read_text(encoding="utf-8") == '{"\\u540d": 1}'
    assert spaced.read_text(encoding="utf-8") == '{\n "a": 1\n}'


def test_a_missing_or_damaged_file_reads_as_nothing(tmp_path: pathlib.Path):
    assert read_json(tmp_path / "absent.json") is None
    damaged = tmp_path / "damaged.json"
    damaged.write_text("{not json", encoding="utf-8")
    assert read_json(damaged) is None
    assert read_json(tmp_path) is None, "a folder where a file should be is not a document"


@posix_only
def test_a_private_file_is_readable_by_its_owner_only(tmp_path: pathlib.Path):
    path = tmp_path / "secret.json"

    write_json(path, {"token": "x"}, private=True)

    assert path.stat().st_mode & 0o777 == 0o600


@posix_only
def test_a_filesystem_that_refuses_modes_keeps_the_write_and_closes_the_descriptor(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    def refuse(descriptor: int, mode: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "fchmod", refuse)
    before = len(os.listdir("/dev/fd"))

    write_json(tmp_path / "secret.json", {"token": "x"}, private=True)

    assert read_json(tmp_path / "secret.json") == {"token": "x"}
    assert len(os.listdir("/dev/fd")) == before, "no descriptor is left open"


def test_a_value_that_is_not_json_leaves_the_old_document(tmp_path: pathlib.Path):
    path = tmp_path / "keep.json"
    write_json(path, {"v": 1})

    with pytest.raises(TypeError):
        write_json(path, {"v": object()})

    assert read_json(path) == {"v": 1}
    assert [item.name for item in tmp_path.iterdir()] == ["keep.json"]


def test_a_write_that_fails_after_the_temporary_exists_removes_it_and_keeps_the_old_document(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path / "keep.json"
    write_json(path, {"v": 1})

    def refuse(source: object, target: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(PermissionError):
        write_json(path, {"v": 2})
    monkeypatch.undo()

    assert read_json(path) == {"v": 1}
    assert [item.name for item in tmp_path.iterdir()] == ["keep.json"], "the temporary was removed"


@posix_only
@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root may write anywhere")
def test_a_write_the_folder_refuses_is_raised_not_swallowed(tmp_path: pathlib.Path):
    folder = tmp_path / "closed"
    folder.mkdir()
    folder.chmod(0o500)
    try:
        with pytest.raises(OSError):
            write_json(folder / "one.json", {"v": 1})
    finally:
        folder.chmod(0o700)


def test_writes_of_one_file_from_several_threads_all_land_whole(tmp_path: pathlib.Path):
    path = tmp_path / "shared.json"
    failures: list[BaseException] = []

    def write(number: int) -> None:
        try:
            for _ in range(20):
                write_json(path, {"writer": number, "pad": "x" * 2000})
        except BaseException as error:  # noqa: BLE001 - the assertion below reports it
            failures.append(error)

    threads = [threading.Thread(target=write, args=(number,)) for number in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    document = read_json(path)
    assert isinstance(document, dict) and document["pad"] == "x" * 2000
    assert [item.name for item in tmp_path.iterdir()] == ["shared.json"]
