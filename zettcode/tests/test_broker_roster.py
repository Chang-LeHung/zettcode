"""Who is registered, what each is called, and which one a typed name means."""

from __future__ import annotations

import pytest

from zettcode.broker.protocol import PeerInfo, Refused, SessionUpdate
from zettcode.broker.roster import MIN_PREFIX, Roster
from zettcode.broker.text import tail_id

A = "01a10b75-aaaa-7000-8000-000000000001"
B = "02b20c86-bbbb-7000-8000-000000000002"
C = "03c30d97-cccc-7000-8000-000000000003"
D = "01a10b99-dddd-7000-8000-000000000004"


def put(roster: Roster, owner: int, session_id, title="", workspace="/w", status="idle"):
    """Register what a ``session.update`` would carry, through the same reading of it the broker gives it."""
    return roster.set(
        owner, SessionUpdate.parse({"session_id": session_id, "title": title, "workspace": workspace, "status": status})
    )


def _roster(*specs: tuple[int, str, str]) -> Roster:
    roster = Roster()
    for owner, session_id, title in specs:
        put(roster, owner, session_id, title, "/work")
    return roster


def _code(call) -> str:
    with pytest.raises(Refused) as refused:
        call()
    return refused.value.reason


# -- registering ------------------------------------------------------------------------------------------


def test_a_session_is_registered_with_a_handle_made_from_its_title():
    roster = _roster((1, A, "Fix the Parser"))

    (entry,) = roster.entries()

    assert (entry.session_id, entry.title, entry.handle) == (A, "Fix the Parser", "fix-the-parser")


def test_a_second_connection_cannot_hold_a_session_that_is_already_held():
    roster = _roster((1, A, "one"))

    assert _code(lambda: put(roster, 2, A, "again", "/w", "idle")) == "duplicate"
    assert [e.owner for e in roster.entries()] == [1], "and the first holder is untouched"


def test_the_same_connection_may_register_its_own_session_again_to_change_the_title():
    roster = _roster((1, A, "old name"))

    put(roster, 1, A, "new name", "/w", "working")

    (entry,) = roster.entries()
    assert (entry.title, entry.handle, entry.status) == ("new name", "new-name", "working")


def test_a_connection_that_switches_session_leaves_the_old_one_free_for_others():
    roster = _roster((1, A, "first"))
    put(roster, 1, B, "second", "/w", "idle")

    put(roster, 2, A, "taken over", "/w", "idle")

    assert sorted(e.session_id for e in roster.entries()) == [A, B]


@pytest.mark.parametrize(
    "session_id", [None, 5, "", " ", "a b", "a/b", "../x", "x" * 65, "-leading", ".leading", "tab\tid", "new\nline"]
)
def test_an_id_that_cannot_be_one_is_refused(session_id):
    assert _code(lambda: put(Roster(), 1, session_id, "t", "/w", "idle")) == "invalid"


@pytest.mark.parametrize("status", [None, "", "busy", 5, "IDLE"])
def test_an_unknown_status_is_treated_as_idle_rather_than_refused(status):
    entry = put(Roster(), 1, A, "t", "/w", status)

    assert entry.status == "idle"


def test_a_title_is_cleaned_before_it_is_kept():
    roster = Roster()

    entry = put(roster, 1, A, "  two\nlines \x1b[31mred\x1b[0m  ", "/w", "idle")

    assert entry.title == "two lines red"


def test_dropping_forgets_the_session_and_frees_its_id():
    roster = _roster((1, A, "x"))

    dropped = roster.drop(1)

    assert dropped is not None and dropped.session_id == A and len(roster) == 0
    put(roster, 2, A, "again", "/w", "idle")
    assert len(roster) == 1


def test_dropping_a_connection_that_holds_nothing_is_not_an_error():
    assert Roster().drop(99) is None


def test_entries_are_listed_in_the_order_they_registered():
    roster = _roster((3, C, "c"), (1, A, "a"), (2, B, "b"))

    assert [e.session_id for e in roster.entries()] == [C, A, B]


# -- handles ----------------------------------------------------------------------------------------------


def test_two_titles_that_reduce_to_the_same_word_get_different_handles():
    roster = _roster((1, A, "Fix parser"), (2, B, "fix PARSER"), (3, C, "Fix parser!"))

    assert [e.handle for e in roster.entries()] == [
        "fix-parser",
        f"fix-parser-{tail_id(B)}",
        f"fix-parser-{tail_id(C)}",
    ]


def test_a_handle_does_not_move_when_a_session_that_came_later_arrives():
    roster = _roster((1, A, "build"))
    before = roster.of(1).handle

    put(roster, 2, B, "build", "/w", "idle")

    assert roster.of(1).handle == before == "build"


def test_a_handle_is_kept_when_the_session_is_registered_again_with_the_same_title():
    roster = _roster((1, A, "build"), (2, B, "build"))
    put(roster, 2, B, "build", "/w", "working")

    assert roster.of(2).handle == f"build-{tail_id(B)}"


def test_a_freed_handle_can_be_used_again():
    roster = _roster((1, A, "build"), (2, B, "build"))
    roster.drop(1)

    put(roster, 3, C, "build", "/w", "idle")

    assert roster.of(3).handle == "build"


def test_a_session_with_no_usable_title_is_named_for_the_folder_it_works_in():
    roster = Roster()
    put(roster, 1, A, "修复解析器", "/home/me/zettdemos")
    put(roster, 2, B, "", "/home/me/Another Project/")
    put(roster, 3, C, "!!!", "C:\\Users\\me\\winproj")

    assert [e.handle for e in roster.entries()] == ["zettdemos", "another-project", "winproj"]


def test_two_untitled_sessions_in_one_folder_are_told_apart_by_the_end_of_the_id():
    """The folder is what a person recognises, so the second session keeps it and adds what is unique.

    A number would be shorter but would say nothing: two untitled sessions in one folder have the same
    description in the menu, and which of them got ``-2`` depends on which registered first.
    """
    roster = Roster()
    put(roster, 1, A, "", "/home/me/zettdemos")
    put(roster, 2, B, "", "/home/me/zettdemos")

    assert [e.handle for e in roster.entries()] == ["zettdemos", f"zettdemos-{tail_id(B)}"]


def test_a_session_with_neither_a_title_nor_a_usable_folder_falls_back_to_the_end_of_the_id():
    roster = Roster()
    put(roster, 1, A, "", "")
    put(roster, 2, B, "!!!", "/")
    put(roster, 3, C, "", "/日本語")

    assert [e.handle for e in roster.entries()] == ["session-000001", "session-000002", "session-000003"]


def test_a_title_beats_the_folder_and_a_name_is_kept_until_the_title_changes():
    roster = Roster()
    put(roster, 1, A, "", "/home/me/zettdemos")
    assert roster.of(1).handle == "zettdemos"

    put(roster, 1, A, "Fix the parser", "/home/me/zettdemos")

    assert roster.of(1).handle == "fix-the-parser"


def test_two_untitled_sessions_started_in_the_same_minute_are_still_told_apart_by_name():
    """Ids are time-ordered, so their starts agree for a minute; a name made from the start would be one name."""
    first = "01a138df-3a1c-7b02-9c11-5f2d3e4a77c1"
    second = "01a138df-3a1d-7d9e-8a30-0b6e1c92f0d4"
    roster = Roster()
    put(roster, 1, first, "", "")
    put(roster, 2, second, "", "")

    assert [e.handle for e in roster.entries()] == ["session-4a77c1", "session-92f0d4"]


def test_a_title_that_looks_like_another_sessions_id_does_not_steal_it():
    """Ids are resolved first, so a title equal to somebody's id prefix would be unreachable by its handle."""
    roster = _roster((1, A, "other"), (2, B, "01a10b75"))

    assert roster.of(2).handle != "01a10b75"
    assert roster.resolve("01a10b75").session_id == A


def test_a_handle_that_equals_another_sessions_full_id_is_made_different():
    roster = _roster((1, "plain", "x"), (2, B, "plain"))

    assert roster.of(2).handle != "plain"


def test_a_handle_is_something_the_composer_can_type_after_an_at_sign():
    import re

    from zettcode.app.agent.dialogue.mentions import MENTION

    roster = _roster((1, A, "Fix the Parser!"), (2, B, "修复"), (3, C, "a" * 80))

    for entry in roster.entries():
        match = MENTION.fullmatch(f"@{entry.handle}")
        assert match is not None and match.group(1) == entry.handle, entry.handle
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", entry.handle)


# -- resolving a typed name --------------------------------------------------------------------------------


def test_a_session_can_be_named_by_its_handle_its_id_the_start_of_its_id_or_its_title():
    roster = _roster((1, A, "Fix the parser"))

    for name in (
        "fix-the-parser",
        "@fix-the-parser",
        A,
        A.upper(),
        "01a1",
        "01A10B75",
        "Fix The Parser",
        "  fix   the parser ",
    ):
        assert roster.resolve(name).session_id == A, name


def test_a_name_that_matches_nothing_says_so():
    assert _code(lambda: _roster((1, A, "x")).resolve("nope")) == "unknown"


@pytest.mark.parametrize("name", [None, 5, "", "   ", "@", "@@", []])
def test_what_is_not_a_name_is_unknown(name):
    assert _code(lambda: _roster((1, A, "x")).resolve(name)) == "unknown"


def test_a_prefix_shorter_than_the_minimum_means_nothing():
    roster = _roster((1, A, "x"))

    assert len("01a") < MIN_PREFIX
    assert _code(lambda: roster.resolve("01a")) == "unknown"
    assert roster.resolve("01a1").session_id == A


def test_a_prefix_that_fits_several_sessions_is_ambiguous_and_lists_them():
    roster = _roster((1, A, "alpha"), (2, D, "delta"))

    with pytest.raises(Refused) as refused:
        roster.resolve("01a10b")

    assert refused.value.reason == "ambiguous"
    assert "@alpha" in str(refused.value) and "@delta" in str(refused.value)
    assert roster.resolve("01a10b7").session_id == A, "one more character picks one"


def test_two_titles_that_differ_only_in_case_are_ambiguous_by_title_but_not_by_handle():
    roster = _roster((1, A, "Build It"), (2, B, "BUILD IT"))

    assert _code(lambda: roster.resolve("Build It")) == "ambiguous"
    assert roster.resolve("build-it").session_id == A
    assert roster.resolve(f"build-it-{tail_id(B)}").session_id == B


def test_a_name_that_is_a_handle_means_that_session_even_when_another_title_spells_it_differently():
    roster = _roster((1, A, "Build"), (2, B, "BUILD"))

    assert roster.resolve("Build").session_id == A, "'build' is the first one's handle, and handles come first"
    assert roster.resolve(f"build-{tail_id(B)}").session_id == B


def test_an_id_is_never_reinterpreted_as_something_else():
    roster = _roster((1, A, "x"), (2, B, "01a10b75-aaaa-7000-8000-000000000001"))

    assert roster.resolve(A).session_id == A


def test_a_handle_beats_a_title_that_happens_to_spell_it():
    roster = _roster((1, A, "deploy"), (2, B, "Something else"))
    put(roster, 2, B, "Something else", "/w", "idle")

    assert roster.resolve("deploy").session_id == A


def test_a_session_cannot_name_itself():
    roster = _roster((1, A, "me"), (2, B, "you"))

    assert _code(lambda: roster.resolve("me", asker=1)) == "self"
    assert roster.resolve("you", asker=1).session_id == B


def test_naming_oneself_by_a_prefix_is_still_refused():
    roster = _roster((1, A, "me"))

    assert _code(lambda: roster.resolve("01a1", asker=1)) == "self"


def test_resolving_with_nobody_registered_is_unknown():
    assert _code(lambda: Roster().resolve("anything")) == "unknown"


def test_the_public_form_has_exactly_what_the_wire_carries():
    roster = Roster()
    put(roster, 1, A, "t", "/w", "working")

    assert roster.snapshot() == (PeerInfo(A, "t", "t", "/w", "working"),)
