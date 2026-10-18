"""The session protocol both ends hold: the shape of every method's parameters.

How a line travels is tested with the wire (``test_broker_wire.py``) and the broker (``test_broker_server.py``).
"""

from __future__ import annotations

import pytest

from zettcode.broker.protocol import (
    MAX_HOPS,
    MAX_TEXT,
    MAX_TITLE,
    VIA_AGENT,
    VIA_USER,
    Limits,
    PeerInfo,
    Refused,
    SessionUpdate,
    parse_send,
    roster_from_wire,
)

# -- what a broker tells a session on arrival -------------------------------------------------------------


def test_the_limits_a_broker_announces_replace_this_ends_and_nonsense_does_not():
    assert Limits.from_wire({"max_text": 10}).max_text == 10
    assert Limits.from_wire({"max_text": -1}).max_text == MAX_TEXT
    assert Limits.from_wire({"max_text": True}).max_text == MAX_TEXT
    assert Limits.from_wire({"max_text": 1.5}).max_text == MAX_TEXT
    assert Limits.from_wire({"rate_window": "soon"}).rate_window == Limits().rate_window
    assert Limits.from_wire({"rate_window": 30}).rate_window == 30.0
    assert Limits.from_wire(None) == Limits() and Limits.from_wire([]) == Limits()


def test_limits_round_trip():
    limits = Limits(max_text=100, max_hops=2, rate_limit=3, rate_window=4.0)

    assert Limits.from_wire(limits.to_wire()) == limits


# -- refusals ------------------------------------------------------------------------------------------


def test_a_refusal_carries_its_reason_and_its_sentence_across_the_wire():
    wire = Refused("loop", "too many hops").to_wire()

    assert wire == {"reason": "loop", "message": "too many hops"}
    again = Refused.from_wire(wire)
    assert (again.reason, str(again)) == ("loop", "too many hops")


@pytest.mark.parametrize("raw", [None, 5, "x", {}, {"reason": 1, "message": "x"}, {"reason": "x"}])
def test_a_refusal_that_does_not_say_why_is_still_a_refusal(raw):
    assert Refused.from_wire(raw).reason == "invalid"


def test_a_refusal_sentence_is_cut_before_it_goes():
    assert len(Refused("x", "m" * 999).to_wire()["message"]) == 300


# -- the roster ----------------------------------------------------------------------------------------


def test_a_session_as_the_others_see_it_round_trips():
    info = PeerInfo("abc", "fix-parser", "Fix the parser", "/work", "working")

    assert PeerInfo.from_wire(info.to_wire()) == info


@pytest.mark.parametrize(
    "raw",
    [
        None,
        5,
        [],
        "x",
        {},
        {"session_id": "a"},
        {"handle": "a"},
        {"session_id": "", "handle": "a"},
        {"session_id": 1, "handle": "a"},
    ],
)
def test_an_entry_that_is_not_a_session_is_skipped(raw):
    assert PeerInfo.from_wire(raw) is None


def test_an_entry_is_cleaned_and_a_missing_part_is_repaired():
    info = PeerInfo.from_wire(
        {"session_id": "a", "handle": "h", "title": "x\x1b[31m  y\nz", "workspace": "/w\x00", "status": "sleeping"}
    )

    assert info == PeerInfo("a", "h", "x y z", "/w", "idle")
    assert PeerInfo.from_wire({"session_id": "a", "handle": "h"}) == PeerInfo("a", "h", "", "", "idle")


def test_a_long_title_and_workspace_are_cut():
    info = PeerInfo.from_wire({"session_id": "a", "handle": "h", "title": "t" * 999, "workspace": "w" * 999})

    assert len(info.title) == MAX_TITLE and len(info.workspace) == 512


def test_a_roster_with_a_damaged_entry_still_lists_the_rest():
    roster = roster_from_wire([{"session_id": "a", "handle": "h"}, "junk", None, {"session_id": "b", "handle": "i"}])

    assert [entry.session_id for entry in roster] == ["a", "b"]
    assert roster_from_wire("not a list") == () and roster_from_wire(None) == ()


def send(raw, limits=None):
    return parse_send(raw, limits or Limits())


# -- registering ---------------------------------------------------------------------------------------


def test_a_session_update_is_read_and_its_descriptive_parts_repaired():
    assert SessionUpdate.parse({"session_id": "s1"}) == SessionUpdate("s1", "", "", "idle")
    update = SessionUpdate.parse({"session_id": "s1", "title": "  A\tB ", "workspace": 5, "status": "dancing"})
    assert update == SessionUpdate("s1", "A B", "", "idle")
    assert SessionUpdate.parse({"session_id": "s1", "status": "working"}).status == "working"


@pytest.mark.parametrize("session_id", ["", " ", "-x", ".x", "a b", "a/b", "é", "x" * 65, "a\nb"])
def test_a_session_id_the_store_could_not_have_written_is_refused(session_id):
    with pytest.raises(Refused) as refused:
        SessionUpdate.parse({"session_id": session_id})

    assert refused.value.reason == "invalid"


@pytest.mark.parametrize("params", [{}, {"session_id": 5}, {"session_id": None}, {"session_id": ["a"]}])
def test_a_session_update_with_no_usable_id_is_refused(params):
    with pytest.raises(Refused):
        SessionUpdate.parse(params)


def test_a_session_id_at_the_longest_is_taken():
    assert SessionUpdate.parse({"session_id": "a" * 64}).session_id == "a" * 64


# -- sending -------------------------------------------------------------------------------------------


def test_a_send_is_read_with_agent_and_no_hops_as_the_defaults():
    assert send({"to": "bob", "text": "hi"}) == ("bob", "hi", VIA_AGENT, 0)


def test_the_text_is_cleaned_before_it_is_measured_and_before_it_is_kept():
    assert send({"to": "bob", "text": "a\x1b[31mb\x1b[0m\r\nc\x07"})[1] == "ab\nc"


def test_a_message_that_is_only_escape_sequences_has_nothing_to_say():
    with pytest.raises(Refused) as refused:
        send({"to": "bob", "text": "\x1b[31m\x07  \n"})

    assert refused.value.reason == "empty"


@pytest.mark.parametrize("text", ["", " ", "\n\t "])
def test_a_message_with_nothing_in_it_is_refused(text):
    with pytest.raises(Refused) as refused:
        send({"to": "bob", "text": text})

    assert refused.value.reason == "empty"


def test_the_longest_message_is_taken_and_one_character_more_is_refused():
    assert len(send({"to": "b", "text": "x" * MAX_TEXT})[1]) == MAX_TEXT
    with pytest.raises(Refused) as refused:
        send({"to": "b", "text": "x" * (MAX_TEXT + 1)})
    assert refused.value.reason == "too_long"


def test_the_limit_is_in_characters_not_bytes():
    emoji = "\U0001f600" * MAX_TEXT

    assert len(send({"to": "b", "text": emoji})[1]) == MAX_TEXT


def test_a_broker_that_announced_other_limits_applies_them():
    assert send({"to": "b", "text": "xxxx"}, Limits(max_text=4))[1] == "xxxx"
    with pytest.raises(Refused):
        send({"to": "b", "text": "xxxxx"}, Limits(max_text=4))


@pytest.mark.parametrize(
    "params",
    [
        {"text": "hi"},
        {"to": "bob"},
        {"to": 5, "text": "hi"},
        {"to": "bob", "text": 5},
        {"to": "bob", "text": None},
        {"to": "bob", "text": "hi", "via": "carrier pigeon"},
        {"to": "bob", "text": "hi", "via": 5},
        {"to": "bob", "text": "hi", "hops": -1},
        {"to": "bob", "text": "hi", "hops": True},
        {"to": "bob", "text": "hi", "hops": 1.5},
        {"to": "bob", "text": "hi", "hops": "2"},
    ],
)
def test_a_send_with_a_parameter_that_is_missing_or_of_the_wrong_kind_is_refused(params):
    with pytest.raises(Refused) as refused:
        send(params)

    assert refused.value.reason == "invalid"


def test_a_message_a_reader_typed_starts_a_chain_whatever_hops_it_claims():
    assert send({"to": "b", "text": "hi", "via": VIA_USER, "hops": 99})[3] == 0


def test_a_message_that_would_be_the_one_past_the_hop_limit_is_a_loop():
    assert send({"to": "b", "text": "hi", "hops": MAX_HOPS - 1})[3] == MAX_HOPS - 1
    with pytest.raises(Refused) as refused:
        send({"to": "b", "text": "hi", "hops": MAX_HOPS})
    assert refused.value.reason == "loop"


def test_fields_nobody_defined_are_ignored_so_a_later_version_can_add_them():
    assert send({"to": "b", "text": "hi", "priority": "high", "tags": [1]}) == ("b", "hi", VIA_AGENT, 0)
    assert SessionUpdate.parse({"session_id": "s", "colour": "red"}).session_id == "s"


# -- who a session is, and where a message came from -------------------------------------------------------


def test_a_session_is_a_zettcode_one_unless_it_says_it_is_an_external_program_and_an_unknown_kind_is_zettcode():
    assert SessionUpdate.parse({"session_id": "s"}).kind == "zettcode"
    assert SessionUpdate.parse({"session_id": "s", "kind": "external"}).kind == "external"
    assert SessionUpdate.parse({"session_id": "s", "kind": "robot"}).kind == "zettcode"
    assert SessionUpdate.parse({"session_id": "s", "kind": 5}).kind == "zettcode"


def test_the_kind_travels_with_a_session_in_the_roster():
    info = PeerInfo("a", "h", "t", "/w", "idle", "external")

    assert PeerInfo.from_wire(info.to_wire()) == info
    assert PeerInfo.from_wire({"session_id": "a", "handle": "h"}).kind == "zettcode"


def test_a_message_from_outside_starts_a_chain_like_one_a_reader_typed():
    assert send({"to": "b", "text": "hi", "via": "external", "hops": 99})[3] == 0
    assert send({"to": "b", "text": "hi", "via": "agent", "hops": 3})[3] == 3
