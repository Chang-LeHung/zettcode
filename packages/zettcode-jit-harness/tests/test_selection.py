"""The harness a session borrowed is remembered on disk, and only a record this program could have written is followed."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from zettcode.jit_harness.selection import ALL_SESSIONS, HarnessChoices


def _folder(root: Path, name: str = "other") -> Path:
    folder = root / "harness" / name
    folder.mkdir(parents=True)
    return folder


def _store(root: Path) -> Path:
    return root / "harness" / ".borrowed"


def test_a_borrow_survives_a_new_window_and_clearing_it_forgets_it(tmp_path: Path):
    folder = _folder(tmp_path)
    first = HarnessChoices(_store(tmp_path))
    assert first.select("s1", "library/todos", folder)

    later = HarnessChoices(_store(tmp_path))
    borrowed = later.target("s1")
    assert borrowed is not None and borrowed.directory == folder
    assert later.target("s2") is None
    assert later.clear("s1")
    assert HarnessChoices(_store(tmp_path)).target("s1") is None

    first.select("s3", "x", folder)
    folder.rmdir()
    assert HarnessChoices(_store(tmp_path)).target("s3") is None, "a folder that is gone is not borrowed"


def test_a_dead_record_is_removed_when_it_is_read(tmp_path: Path):
    folder = _folder(tmp_path)
    HarnessChoices(_store(tmp_path)).select("s1", "x", folder)
    folder.rmdir()

    HarnessChoices(_store(tmp_path)).target("s1")

    assert list(_store(tmp_path).iterdir()) == []


def test_ids_that_are_paths_stay_inside_the_store_and_the_default_marker_is_never_stored(tmp_path: Path):
    folder = _folder(tmp_path)
    choices = HarnessChoices(_store(tmp_path))
    choices.select("../../escape", "x", folder)
    choices.select("a/b", "x", folder)
    choices.select(ALL_SESSIONS, "x", folder)

    assert {path.parent for path in tmp_path.rglob("*.json")} == {_store(tmp_path)}
    assert HarnessChoices(_store(tmp_path)).target("../../escape") is not None
    assert HarnessChoices(_store(tmp_path)).target(ALL_SESSIONS) is None


def test_a_record_is_followed_only_when_it_names_a_folder_under_the_harness_directory(tmp_path: Path):
    store = _store(tmp_path)
    store.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (store / "abs.json").write_text(json.dumps({"label": "x", "directory": str(outside)}), encoding="utf-8")
    (store / "rel.json").write_text(json.dumps({"label": "x", "directory": "harness"}), encoding="utf-8")
    (store / "bad.json").write_text("{", encoding="utf-8")
    (store / "empty.json").write_text("", encoding="utf-8")

    choices = HarnessChoices(store)

    assert [choices.target(name) for name in ("abs", "rel", "bad", "empty")] == [None] * 4
    assert list(store.iterdir()) == [], "none of them is kept to be read again"


def test_a_borrow_that_cannot_be_written_down_is_still_made_and_says_why(tmp_path: Path):
    folder = _folder(tmp_path)
    blocker = tmp_path / "harness" / ".borrowed"
    blocker.write_text("a file where the store should be", encoding="utf-8")
    choices = HarnessChoices(blocker)

    assert choices.select("s1", "x", folder)

    assert choices.target("s1") is not None
    assert choices.store_error


def test_choosing_the_same_folder_under_another_name_moves_nothing(tmp_path: Path):
    folder = _folder(tmp_path)
    heard: list[str] = []
    choices = HarnessChoices(_store(tmp_path))
    choices.select("s1", "old title", folder)
    choices.add_listener(heard.append)

    assert choices.select("s1", "new title", folder) is False

    assert heard == []
    borrowed = choices.target("s1")
    assert borrowed is not None and borrowed.label == "new title"


def test_a_record_cannot_lead_out_of_the_harness_directory_by_dots_a_link_or_the_directory_itself(tmp_path: Path):
    store = _store(tmp_path)
    store.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "harness" / "link").symlink_to(outside, target_is_directory=True)
    named = {
        "dots": str(tmp_path / "harness" / ".." / "outside"),
        "link": str(tmp_path / "harness" / "link"),
        "root": str(tmp_path / "harness"),
    }
    for session, directory in named.items():
        (store / f"{session}.json").write_text(json.dumps({"label": "x", "directory": directory}), encoding="utf-8")

    choices = HarnessChoices(store)

    assert [choices.target(session) for session in named] == [None] * 3


def test_a_folder_that_would_not_be_read_back_is_not_written_and_says_so(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "harness").mkdir()
    choices = HarnessChoices(_store(tmp_path))

    assert choices.select("s1", "x", outside)

    assert choices.store_error and not _store(tmp_path).exists()


def test_the_error_of_one_write_is_not_reported_for_the_next(tmp_path: Path):
    folder = _folder(tmp_path)
    blocker = tmp_path / "harness" / ".borrowed"
    blocker.write_text("in the way", encoding="utf-8")
    choices = HarnessChoices(blocker)
    choices.select("s1", "x", folder)
    assert choices.store_error
    blocker.unlink()

    choices.select("s2", "y", folder)

    assert choices.store_error is None


def test_a_folder_that_cannot_be_examined_keeps_its_record_but_is_not_borrowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    folder = _folder(tmp_path)
    HarnessChoices(_store(tmp_path)).select("s1", "x", folder)
    real = os.stat

    def refuse(path: object, *args: object, **kwargs: object) -> os.stat_result:
        if str(path) == str(folder):
            raise PermissionError("not now")
        return real(path, *args, **kwargs)  # type: ignore[arg-type]

    with monkeypatch.context() as patched:
        patched.setattr(os, "stat", refuse)
        assert HarnessChoices(_store(tmp_path)).target("s1") is None

    assert HarnessChoices(_store(tmp_path)).target("s1") is not None, "it comes back once it can be examined"


def test_a_refused_write_leaves_no_record_of_an_earlier_borrow(tmp_path: Path):
    folder = _folder(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    choices = HarnessChoices(_store(tmp_path))
    choices.select("s1", "x", folder)

    choices.select("s1", "y", outside)

    assert HarnessChoices(_store(tmp_path)).target("s1") is None
