"""The profiles a page keeps for its threads, on their own: what is accepted, what excludes what, and what expires."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from zettcode.gateway.profiles import MAX_AVATAR, MAX_NAME, PROFILE_FILE, PROFILE_TTL, ProfileError, Profiles

PICTURE = "data:image/png;base64,AAAA"


def make(tmp_path: pathlib.Path) -> tuple[Profiles, list[float]]:
    clock = [1000.0]
    return Profiles(tmp_path, lambda: clock[0]), clock


def stored(tmp_path: pathlib.Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((tmp_path / PROFILE_FILE).read_text(encoding="utf-8"))
    return document


def test_a_change_is_kept_and_read_back_by_a_new_instance(tmp_path: pathlib.Path):
    profiles, _ = make(tmp_path)

    profiles.change("a", {"name": "  名字  ", "avatar": PICTURE, "pinned": True})

    expected = {"name": "名字", "avatar": PICTURE, "pinned": "1"}
    assert profiles.read("a") == expected
    assert "名字" in (tmp_path / PROFILE_FILE).read_text(encoding="utf-8"), "not escaped to ASCII"
    assert Profiles(tmp_path, lambda: 0.0).read("a") == expected


def test_what_is_read_is_a_copy(tmp_path: pathlib.Path):
    profiles, _ = make(tmp_path)
    profiles.change("a", {"name": "n"})

    got = profiles.read("a")
    assert isinstance(got, dict)
    got["name"] = "changed"

    assert profiles.read("a") == {"name": "n"}


def test_the_file_keeps_the_same_key_order_through_a_load_and_a_save(tmp_path: pathlib.Path):
    (tmp_path / PROFILE_FILE).write_text(
        json.dumps({"a": {"archived": "1", "pinned": "1", "avatar": PICTURE, "name": "n"}}), encoding="utf-8"
    )
    profiles, _ = make(tmp_path)

    profiles.change("a", {"name": "m"})

    assert list(stored(tmp_path)["a"]) == ["name", "avatar", "pinned", "archived"]


def test_an_empty_value_removes_an_override_and_a_profile_with_nothing_left_is_forgotten(tmp_path: pathlib.Path):
    profiles, _ = make(tmp_path)
    profiles.change("a", {"name": "n", "avatar": PICTURE})

    profiles.change("a", {"name": "   "})
    assert profiles.read("a") == {"avatar": PICTURE}
    profiles.change("a", {"avatar": ""})

    assert "a" not in profiles and stored(tmp_path) == {}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"name": 5}, f"name is a string of at most {MAX_NAME} characters"),
        ({"name": "x" * (MAX_NAME + 1)}, f"name is a string of at most {MAX_NAME} characters"),
        ({"avatar": 5}, "avatar is a small image data URL"),
        ({"avatar": "data:image/png;base64," + "A" * MAX_AVATAR}, "avatar is a small image data URL"),
        ({"avatar": "http://example.test/a.png"}, "avatar is an image data URL"),
        ({"pinned": "yes"}, "pinned is true or false"),
        ({"archived": 1}, "archived is true or false"),
        ({"pinned": "yes", "archived": "yes"}, "pinned is true or false"),
    ],
)
def test_a_field_of_the_wrong_kind_is_refused_with_its_sentence_and_changes_nothing(
    tmp_path: pathlib.Path, data: dict[str, object], message: str
):
    profiles, _ = make(tmp_path)
    profiles.change("a", {"name": "kept"})

    with pytest.raises(ProfileError) as refused:
        profiles.change("a", {"name": "other", **data})

    assert str(refused.value) == message
    assert profiles.read("a") == {"name": "kept"}
    assert stored(tmp_path) == {"a": {"name": "kept"}}


def test_a_name_and_a_picture_may_be_as_large_as_their_limits(tmp_path: pathlib.Path):
    profiles, _ = make(tmp_path)
    picture = "data:image/png;base64," + "A" * (MAX_AVATAR - len("data:image/png;base64,"))

    profiles.change("a", {"name": "x" * MAX_NAME, "avatar": picture})

    assert profiles.read("a") == {"name": "x" * MAX_NAME, "avatar": picture}


def test_pinned_and_archived_exclude_each_other_and_the_last_one_asked_for_wins(tmp_path: pathlib.Path):
    profiles, _ = make(tmp_path)

    profiles.change("a", {"pinned": True})
    profiles.change("a", {"archived": True})
    assert profiles.read("a") == {"archived": "1"}, "archiving unpins"
    profiles.change("a", {"pinned": True})
    assert profiles.read("a") == {"pinned": "1"}, "pinning brings it back"
    profiles.change("a", {"pinned": True, "archived": True})
    assert profiles.read("a") == {"archived": "1"}, "asked together, the archive wins"
    profiles.change("a", {"archived": False})
    assert "a" not in profiles


def test_a_stored_file_with_junk_in_it_keeps_only_what_a_profile_can_hold(tmp_path: pathlib.Path):
    (tmp_path / PROFILE_FILE).write_text(
        json.dumps(
            {
                "ok": {"name": "n", "pinned": "1", "archived": "0", "other": "x"},
                "empty": {"other": "x"},
                "wrong": "text",
                "7": {"name": 7, "avatar": PICTURE},
            }
        ),
        encoding="utf-8",
    )

    profiles, _ = make(tmp_path)

    assert profiles.read("ok") == {"name": "n", "pinned": "1"}
    assert profiles.read("7") == {"avatar": PICTURE}
    assert "empty" not in profiles and "wrong" not in profiles


def test_a_missing_or_damaged_file_is_an_empty_set_of_profiles(tmp_path: pathlib.Path):
    assert "a" not in make(tmp_path)[0]
    (tmp_path / PROFILE_FILE).write_text("[1, 2", encoding="utf-8")
    assert "a" not in make(tmp_path)[0]


def test_a_default_avatar_replaces_the_profile_and_is_kept(tmp_path: pathlib.Path):
    profiles, _ = make(tmp_path)
    profiles.change("agent", {"name": "gone", "pinned": True})

    profiles.set_default_avatar("agent", PICTURE)

    assert profiles.read("agent") == {"avatar": PICTURE}
    assert stored(tmp_path) == {"agent": {"avatar": PICTURE}}


def test_a_name_and_a_picture_outlive_their_session_for_a_day_but_a_pin_or_an_archive_does_not_expire(
    tmp_path: pathlib.Path,
):
    profiles, clock = make(tmp_path)
    profiles.change("named", {"name": "n"})
    profiles.change("pinned", {"pinned": True})
    profiles.change("archived", {"archived": True})
    profiles.change("listed", {"name": "here"})
    for session in ("named", "pinned", "archived", "listed"):
        profiles.read(session)

    clock[0] += PROFILE_TTL
    profiles.forget_vanished({"listed"})
    assert "named" in profiles, "a day exactly is not more than a day"

    clock[0] += 1
    profiles.forget_vanished({"listed"})

    assert "named" not in profiles
    assert "pinned" in profiles and "archived" in profiles and "listed" in profiles
    assert sorted(stored(tmp_path)) == ["archived", "listed", "pinned"]


def test_reading_a_profile_counts_as_the_session_still_being_here(tmp_path: pathlib.Path):
    profiles, clock = make(tmp_path)
    profiles.change("a", {"name": "n"})
    profiles.read("a")
    clock[0] += PROFILE_TTL - 10
    profiles.read("a")
    clock[0] += 20

    profiles.forget_vanished(set())

    assert "a" in profiles, "the day is counted from the last time it was read"


def test_a_profile_made_again_after_it_expired_starts_its_day_afresh(tmp_path: pathlib.Path):
    profiles, clock = make(tmp_path)
    profiles.change("a", {"name": "first"})
    profiles.read("a")
    clock[0] += PROFILE_TTL + 1
    profiles.forget_vanished(set())
    assert "a" not in profiles

    profiles.change("a", {"name": "second"})
    profiles.forget_vanished(set())

    assert "a" in profiles, "no stale timestamp from the first one expires the second at once"


def test_nothing_is_written_when_nothing_expired(tmp_path: pathlib.Path):
    profiles, _ = make(tmp_path)
    profiles.change("a", {"name": "n"})
    before = (tmp_path / PROFILE_FILE).stat().st_mtime_ns

    profiles.forget_vanished({"a"})

    assert (tmp_path / PROFILE_FILE).stat().st_mtime_ns == before
