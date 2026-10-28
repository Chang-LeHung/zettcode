"""A turn as it happens: what the gateway keeps of one, what it tells the pages, and when it lets go."""

from __future__ import annotations

import asyncio

from test_gateway_service import DAEMON, make
from zettcode.sdk.types import Message


def drained(queue: asyncio.Queue) -> list[dict]:
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


async def test_every_session_that_is_listed_is_watched_so_its_turns_can_be_seen(tmp_path):
    gateway, backend = await make(tmp_path)

    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()

    assert backend.watched == {DAEMON}


async def test_a_turn_is_kept_while_it_runs_and_told_to_the_pages_piece_by_piece(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    queue = gateway.subscribe()
    drained(queue)

    backend.stream(DAEMON, "begin")
    backend.stream(DAEMON, "thinking")
    backend.stream(DAEMON, "tool", call_id="c1", name="bash", brief="pytest")
    backend.stream(DAEMON, "tool_end", call_id="c1", ok=True)
    backend.stream(DAEMON, "text", text="Hel")
    backend.stream(DAEMON, "text", text="lo")

    live = (await gateway.thread(DAEMON))["live"]
    assert live["text"] == "Hello" and live["thinking"] is False
    assert live["tools"] == [{"id": "c1", "name": "bash", "brief": "pytest", "ok": True}]
    kinds = [item["event"]["kind"] for item in drained(queue) if item["type"] == "stream"]
    assert kinds == ["begin", "thinking", "tool", "tool_end", "text", "text"]


async def test_when_the_turn_ends_the_stored_message_is_read_before_the_live_one_goes(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    queue = gateway.subscribe()
    backend.stream(DAEMON, "begin")
    backend.stream(DAEMON, "text", text="Done.")
    drained(queue)

    backend.say(DAEMON, Message("assistant", "Done."))
    backend.stream(DAEMON, "end")
    await asyncio.sleep(0.05)

    shown = await gateway.thread(DAEMON)
    assert shown["live"] is None and [item["text"] for item in shown["items"]] == ["Done."]
    seen = [(item["type"], item.get("event", {}).get("kind")) for item in drained(queue)]
    assert seen.index(("thread", None)) < seen.index(("stream", "end")), "stored first, then the live one goes"


async def test_a_turn_whose_session_went_away_or_fell_silent_is_dropped(tmp_path):
    clock = [1000.0]
    gateway, backend = await make(tmp_path)
    gateway.clock = lambda: clock[0]
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    backend.set_status(DAEMON, "working")
    backend.stream(DAEMON, "begin")
    await gateway.refresh()
    assert (await gateway.thread(DAEMON))["live"] is not None

    backend.set_status(DAEMON, "idle")
    clock[0] += 10
    await gateway.refresh()

    assert (await gateway.thread(DAEMON))["live"] is None


async def test_what_the_gateway_itself_streams_is_not_a_thread(tmp_path):
    gateway, backend = await make(tmp_path)
    from gateway_fakes import GATEWAY_ID

    backend.stream(GATEWAY_ID, "text", text="x")

    assert gateway._live == {}


async def test_the_end_of_one_turn_does_not_end_the_next_one_that_began_while_it_was_being_read(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    backend.stream(DAEMON, "begin")
    backend.stream(DAEMON, "text", text="first")
    queue = gateway.subscribe()
    drained(queue)

    backend.stream(DAEMON, "end")  # its reading has not finished...
    backend.stream(DAEMON, "begin")  # ...when the session starts its next turn
    backend.stream(DAEMON, "text", text="second")
    await asyncio.sleep(0.05)

    assert (await gateway.thread(DAEMON))["live"]["text"] == "second"
    kinds = [item["event"]["kind"] for item in drained(queue) if item["type"] == "stream"]
    assert kinds == ["begin", "text"], "no end was told for the first turn once the second had begun"


async def test_every_live_turn_is_dropped_when_the_broker_comes_back_because_pieces_were_missed(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    backend.stream(DAEMON, "begin")
    backend.stream(DAEMON, "text", text="half an ans")
    backend._reachable = False
    await gateway.refresh()
    backend._reachable = True
    await gateway.refresh()

    assert (await gateway.thread(DAEMON))["live"] is None


async def test_a_page_that_stopped_reading_is_told_to_go_instead_of_being_left_with_stale_data(tmp_path):
    gateway, _ = await make(tmp_path)
    queue = gateway.subscribe()
    while not queue.full():
        queue.put_nowait({"type": "thread", "id": "x"})

    gateway._publish({"type": "thread", "id": "y"})

    assert queue not in gateway._subscribers
    last = None
    while not queue.empty():
        last = queue.get_nowait()
    assert last == {"type": "close"}


async def test_a_session_that_is_no_longer_listed_is_let_go_of_so_the_brokers_cap_is_not_used_up(tmp_path):
    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    assert backend.watched == {DAEMON}

    del backend.peer_list[DAEMON]
    del backend.daemon_list[DAEMON]
    await gateway.refresh()

    assert backend.watched == set()


async def test_a_direct_turn_that_ended_without_an_answer_is_shown_as_a_note_until_the_person_writes_again(tmp_path):
    from zettcode.sdk.types import DIRECT_FAILED, IncomingMessage

    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d", direct=True)
    backend.say(DAEMON, Message("user", "run it"))
    await gateway.refresh()

    gateway._received(IncomingMessage(DAEMON, "d", f"{DIRECT_FAILED}the model stopped", via="agent"))

    shown = await gateway.thread(DAEMON)
    items = shown["items"]
    assert items[-1] == {"kind": "note", "text": f"{DIRECT_FAILED}the model stopped"}
    assert [item["text"] for item in items].count(f"{DIRECT_FAILED}the model stopped") == 1, "shown once, not twice"
    assert shown["total"] == len(items)
    await gateway.send(DAEMON, "try again")
    assert all(item["kind"] != "note" for item in (await gateway.thread(DAEMON))["items"])


async def test_the_end_of_a_live_turn_that_was_never_heard_is_told_after_what_was_stored(tmp_path):
    clock = [1000.0]
    gateway, backend = await make(tmp_path)
    gateway.clock = lambda: clock[0]
    backend.add_daemon(DAEMON, "/w", name="d")
    await gateway.refresh()
    backend.stream(DAEMON, "begin")
    queue = gateway.subscribe()
    drained(queue)

    backend.say(DAEMON, Message("assistant", "done"))
    clock[0] += 10
    await gateway.refresh()

    seen = [(item["type"], item.get("event", {}).get("kind")) for item in drained(queue)]
    assert seen.index(("thread", None)) < seen.index(("stream", "end"))


async def test_only_the_last_few_notes_about_a_session_are_kept(tmp_path):
    from zettcode.gateway.service import NOTE_LIMIT
    from zettcode.sdk.types import DIRECT_FAILED, IncomingMessage

    gateway, backend = await make(tmp_path)
    backend.add_daemon(DAEMON, "/w", name="d", direct=True)
    await gateway.refresh()

    for number in range(NOTE_LIMIT + 5):
        gateway._received(IncomingMessage(DAEMON, "d", f"{DIRECT_FAILED}{number}", via="agent"))

    notes = [item["text"] for item in (await gateway.thread(DAEMON))["items"] if item["kind"] == "note"]
    assert notes == [f"{DIRECT_FAILED}{number}" for number in range(5, NOTE_LIMIT + 5)]


async def test_a_failure_note_is_told_to_the_pages_like_a_message_so_it_is_noticed_and_is_forgotten_with_its_session(
    tmp_path,
):
    from zettcode.sdk.types import DIRECT_FAILED, IncomingMessage

    gateway, _ = await make(tmp_path)
    queue = gateway.subscribe()
    drained(queue)

    gateway._received(IncomingMessage("external:tool", "tool", f"{DIRECT_FAILED}x", via="agent"))

    assert [item["type"] for item in drained(queue)] == ["thread", "inbound"]
    await gateway.refresh()
    assert "external:tool" not in gateway._notes, "an id that is not listed keeps nothing"
