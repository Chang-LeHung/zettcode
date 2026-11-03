"""Where the broker keeps its files, the note a session finds it by, and the directory it lives in."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from zettcode.broker.files import (
    DIRECTORY_VARIABLE,
    LOCK_FILE,
    LOG_FILE,
    NOTE_FILE,
    Note,
    broker_dir,
    ensure_directory,
    lock_path,
    log_path,
    note_path,
    read_note,
    remove_note,
    write_note,
)

INFO = Note(pid=4242, port=40123, token="secret-token", version=3)
NOTE = NOTE_FILE


def test_the_broker_names_its_three_files(tmp_path: Path):
    assert (NOTE_FILE, LOCK_FILE, LOG_FILE) == ("broker.json", "broker.lock", "broker.log")
    assert (note_path(tmp_path), lock_path(tmp_path), log_path(tmp_path)) == (
        tmp_path / "broker.json",
        tmp_path / "broker.lock",
        tmp_path / "broker.log",
    )


def test_the_directory_can_be_chosen_by_the_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv(DIRECTORY_VARIABLE, str(tmp_path / "chosen"))

    assert broker_dir() == tmp_path / "chosen"


def test_the_default_directory_follows_the_home_directory_at_the_time_of_asking(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(DIRECTORY_VARIABLE, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    assert broker_dir() == tmp_path / ".zettcode" / "broker"


def test_a_tilde_in_the_environment_variable_is_expanded(monkeypatch):
    monkeypatch.setenv(DIRECTORY_VARIABLE, "~/somewhere")

    # Not "no tilde anywhere": a Windows home can itself be an 8.3 short name such as RUNNER~1.
    assert broker_dir() == Path.home() / "somewhere"


# -- the note ----------------------------------------------------------------------------------------------


def test_the_note_round_trips(tmp_path: Path):
    write_note(tmp_path, INFO)

    assert read_note(tmp_path) == INFO


def test_a_directory_that_does_not_exist_yet_is_made(tmp_path: Path):
    write_note(tmp_path / "deep" / "er", INFO)

    assert read_note(tmp_path / "deep" / "er") == INFO


@pytest.mark.skipif(os.name == "nt", reason="Windows has no mode bits to check")
def test_the_note_is_readable_by_its_owner_only_because_the_token_is_the_credential(tmp_path: Path):
    write_note(tmp_path, INFO)

    assert (tmp_path / NOTE).stat().st_mode & 0o777 == 0o600


def test_writing_leaves_no_temporary_file_behind(tmp_path: Path):
    write_note(tmp_path, INFO)
    write_note(tmp_path, Note(pid=1, port=2, token="t", version=1))

    assert [p.name for p in tmp_path.iterdir()] == [NOTE]


def test_a_failed_write_leaves_the_old_note_and_no_temporary_file(tmp_path: Path, monkeypatch):
    write_note(tmp_path, INFO)

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        write_note(tmp_path, Note(pid=1, port=2, token="new", version=1))

    assert read_note(tmp_path) == INFO
    assert [p.name for p in tmp_path.iterdir()] == [NOTE]


def test_no_note_means_no_broker(tmp_path: Path):
    assert read_note(tmp_path) is None
    assert read_note(tmp_path / "missing") is None


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[]",
        "null",
        '"text"',
        "{}",
        '{"pid": 1, "port": 2}',
        '{"pid": "1", "port": 2, "token": "t", "version": 1}',
        '{"pid": 1, "port": "2", "token": "t", "version": 1}',
        '{"pid": 1, "port": 2, "token": "", "version": 1}',
        '{"pid": 1, "port": 2, "token": 5, "version": 1}',
        '{"pid": 1, "port": 0, "token": "t", "version": 1}',
        '{"pid": 1, "port": 70000, "token": "t", "version": 1}',
        '{"pid": 0, "port": 2, "token": "t", "version": 1}',
        '{"pid": -4, "port": 2, "token": "t", "version": 1}',
        '{"pid": true, "port": 2, "token": "t", "version": 1}',
        '{"pid": 1, "port": 2, "token": "t", "version": true}',
        '{"pid": 1.5, "port": 2, "token": "t", "version": 1}',
        "\x00\x01\x02",
    ],
)
def test_a_note_that_cannot_be_trusted_reads_as_no_broker(tmp_path: Path, content: str):
    (tmp_path / NOTE).write_text(content, encoding="utf-8")

    assert read_note(tmp_path) is None


def test_a_note_that_is_not_utf8_reads_as_no_broker(tmp_path: Path):
    (tmp_path / NOTE).write_bytes(b"\xff\xfe{")

    assert read_note(tmp_path) is None


def test_a_note_with_extra_fields_is_still_read(tmp_path: Path):
    note = {"pid": 1, "port": 2, "token": "t", "version": 1, "future": "field"}
    (tmp_path / NOTE).write_text(json.dumps(note), encoding="utf-8")

    assert read_note(tmp_path) == Note(pid=1, port=2, token="t", version=1)


def test_a_broker_removes_only_its_own_note(tmp_path: Path):
    write_note(tmp_path, INFO)

    assert remove_note(tmp_path, "somebody else's token") is False
    assert read_note(tmp_path) == INFO
    assert remove_note(tmp_path, INFO.token) is True
    assert read_note(tmp_path) is None


def test_removing_a_note_that_is_not_there_is_not_an_error(tmp_path: Path):
    assert remove_note(tmp_path, "t") is False


# -- who may look in the directory --------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_directory_the_broker_makes_is_private_to_its_owner(tmp_path: Path):
    directory = tmp_path / "broker"

    write_note(directory, INFO)

    assert (directory.stat().st_mode & 0o777) == 0o700


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_a_directory_that_already_exists_is_left_as_it_was(tmp_path: Path):
    directory = tmp_path / "shared"
    directory.mkdir(mode=0o755)
    os.chmod(directory, 0o755)

    ensure_directory(directory)

    assert (directory.stat().st_mode & 0o777) == 0o755
