"""The running turns, on their own: numbering, what is kept, and what ends one. No gateway, no queue."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from zettcode.gateway.live import STALE_SECONDS, TEXT_LIMIT, TOOL_LIMIT, LiveTurns
from zettcode.sdk.types import StreamEvent


def piece(kind: str, session: str = "s", **fields: Any) -> StreamEvent:
    return StreamEvent(session_id=session, kind=kind, **fields)


def peer(status: str) -> Any:
    return SimpleNamespace(status=status)


def make() -> tuple[LiveTurns, list[float]]:
    clock = [100.0]
    return LiveTurns(lambda: clock[0]), clock


def test_a_begin_numbers_a_turn_and_every_piece_of_it_says_which():
    live, _ = make()

    first = live.hear(piece("begin"))
    text = live.hear(piece("text", text="Hel"))
    live.hear(piece("text", text="lo"))

    assert first == {"kind": "begin", "turn": 1}
    assert text == {"kind": "text", "turn": 1, "text": "Hel"}
    assert live.view("s") == {"turn": 1, "text": "Hello", "thinking": False, "tools": []}
    assert live.number_of("s") == 1 and len(live) == 1


def test_a_second_begin_starts_afresh_and_numbers_are_shared_by_sessions_so_they_only_rise():
    live, _ = make()
    live.hear(piece("begin"))
    live.hear(piece("text", text="old"))

    live.hear(piece("begin"))
    live.hear(piece("begin", session="other"))

    assert live.view("s") == {"turn": 2, "text": "", "thinking": False, "tools": []}
    assert live.number_of("other") == 3


def test_a_piece_with_no_begin_before_it_still_starts_a_turn():
    live, _ = make()

    wire = live.hear(piece("thinking"))

    assert wire == {"kind": "thinking", "turn": 1}
    assert live.view("s") == {"turn": 1, "text": "", "thinking": True, "tools": []}


def test_an_end_is_not_applied_by_hearing_it_and_says_nothing_to_tell():
    live, _ = make()
    live.hear(piece("begin"))

    assert live.hear(piece("end")) is None
    assert live.number_of("s") == 1, "the turn stays until the caller has read what it wrote"


def test_tools_are_kept_with_their_result_and_only_the_last_ones():
    live, _ = make()
    wire = live.hear(piece("tool", call_id="c0", name="bash", brief="ls"))
    live.hear(piece("tool_end", call_id="c0", ok=True))

    assert wire == {"kind": "tool", "turn": 1, "id": "c0", "name": "bash", "brief": "ls"}
    assert live.view("s")["tools"] == [{"id": "c0", "name": "bash", "brief": "ls", "ok": True}]
    for number in range(1, TOOL_LIMIT + 5):
        live.hear(piece("tool", call_id=f"c{number}", name="bash", brief="x"))
    tools = live.view("s")["tools"]
    assert len(tools) == TOOL_LIMIT and tools[-1]["id"] == f"c{TOOL_LIMIT + 4}"


def test_only_the_tail_of_a_very_long_answer_is_kept_but_every_piece_is_passed_on():
    live, _ = make()
    live.hear(piece("text", text="a" * TEXT_LIMIT))

    wire = live.hear(piece("text", text="tail"))

    assert wire is not None and wire["text"] == "tail"
    kept = live.view("s")["text"]
    assert len(kept) == TEXT_LIMIT and kept.endswith("tail")


def test_the_view_is_what_a_page_reads_and_does_not_carry_when_the_turn_last_spoke():
    live, _ = make()
    live.hear(piece("begin"))

    assert set(live.view("s") or {}) == {"turn", "text", "thinking", "tools"}
    assert live.view("nobody") is None


def test_finishing_drops_only_the_turn_it_names():
    live, _ = make()
    live.hear(piece("begin"))
    ended = live.number_of("s")
    live.hear(piece("begin"))

    assert live.finish("s", ended) is False, "the next turn began while the end was being read"
    assert live.number_of("s") == 2
    assert live.finish("s", 2) is True and live.number_of("s") is None
    assert live.finish("s", 2) is False
    assert live.finish("s", None) is False


def test_dropping_forgets_a_session_or_all_of_them_and_says_what_it_dropped():
    live, _ = make()
    live.hear(piece("begin"))
    live.hear(piece("begin", session="b"))

    assert live.drop("s") == 1 and live.drop("s") is None
    assert live.drop_all() == [("b", 2)] and len(live) == 0


def test_a_turn_is_expired_when_its_session_is_gone_or_idle_and_silent_but_not_while_it_works():
    live, clock = make()
    for name in ("gone", "idle", "working", "recent"):
        live.hear(piece("begin", session=name))
    clock[0] += STALE_SECONDS + 1
    live.hear(piece("text", session="recent", text="still talking"))

    expired = live.expire({"idle": peer("idle"), "working": peer("working"), "recent": peer("idle")})

    assert sorted(expired) == [("gone", 1), ("idle", 2)]
    assert sorted(live) == ["recent", "working"]
