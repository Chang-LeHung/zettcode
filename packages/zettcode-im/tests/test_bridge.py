"""One message in, one turn, one answer out — and the pictures that travel with it."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from zettcode.broker.protocol import MAX_IMAGE_BYTES, MAX_IMAGES
from zettcode.im.bridge import Bridge, BridgeSettings, _identity, split
from zettcode.im.guard import DaemonUnavailable
from zettcode.im.link import LinkError
from zettcode.im.state import BridgeState

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 40


@dataclass
class Media:
    kind: str
    media_type: str
    data: bytes


@dataclass
class Message:
    event_id: str = "e1"
    chat_id: str = "chat"
    user_id: str = "u1"
    text: str = ""
    media: list[Any] = field(default_factory=list)
    rejected_media: list[Any] = field(default_factory=list)
    reply_token: str | None = "token"


@dataclass
class Result:
    message: Message
    cursor: str = "cur-1"


class Im:
    """The platform client, with as many messages as the test put in."""

    def __init__(self, results: list[Result] | None = None) -> None:
        self.results = list(results or [])
        self.sent: list[tuple[str, str, str | None]] = []

    async def receive(self, cursor: str | None = None):
        if not self.results:
            await asyncio.sleep(3600)
        return self.results.pop(0)

    async def send(self, chat_id: str, text: str, *, context_token: str | None = None) -> None:
        self.sent.append((chat_id, text, context_token))


class Guard:
    def __init__(self, session: str = "01a1", error: Exception | None = None) -> None:
        self.session = session
        self.error = error
        self.ensured = 0

    async def ensure(self) -> str:
        self.ensured += 1
        if self.error is not None:
            raise self.error
        return self.session

    def wait_left(self) -> float:
        return 0.0


class Link:
    def __init__(self, answer: str = "the answer", error: Exception | None = None) -> None:
        self.answer = answer
        self.error = error
        self.asked: list[tuple[str, str, list[Any]]] = []
        self.statuses: list[str] = []

    async def ask(self, session: str, text: str, *, images: Any = ()) -> str:
        self.asked.append((session, text, list(images)))
        if self.error is not None:
            raise self.error
        return self.answer

    def status(self, status: str) -> None:
        self.statuses.append(status)


def bridge(
    tmp_path: Path,
    *,
    settings: BridgeSettings | None = None,
    im: Im | None = None,
    link: Link | None = None,
    guard: Guard | None = None,
) -> Bridge:
    state = BridgeState.load(tmp_path / "state.json")
    return Bridge(
        im=im or Im(),
        guard=guard or Guard(),  # type: ignore[arg-type]
        link=link or Link(),  # type: ignore[arg-type]
        state=state,
        path=tmp_path / "state.json",
        settings=settings or BridgeSettings(allow_all=True),
        error=lambda said: None,
    )


def test_a_message_becomes_one_turn_and_the_answer_goes_back_to_its_chat(tmp_path: Path) -> None:
    im, link = Im(), Link(answer="done")
    opened = bridge(tmp_path, im=im, link=link)

    asyncio.run(opened._turn(Message(text="list the files"), "cur-9"))

    session, prompt, images = link.asked[0]
    assert session == "01a1" and "list the files" in prompt and "u1" in prompt, "who wrote and what"
    assert images == []
    assert im.sent == [("chat", "done", "token")], "the answer goes back with the chat's context token"
    assert link.statuses == ["working", "idle"]
    assert opened.state.cursor == "cur-9" and opened.state.answered(_identity(Message(text="list the files")))


def test_a_picture_travels_with_the_prompt_and_an_image_only_message_runs_a_turn(tmp_path: Path) -> None:
    im, link = Im(), Link()
    opened = bridge(tmp_path, im=im, link=link)

    asyncio.run(opened._turn(Message(text="", media=[Media("image", "image/png", PNG)]), "c"))

    _, prompt, images = link.asked[0]
    assert [picture.media_type for picture in images] == ["image/png"]
    assert images[0].data == PNG
    assert "not forwarded" not in prompt, "a picture that fits is not hedged about"


def test_pictures_that_cannot_go_are_named_in_the_prompt_instead_of_being_lost(tmp_path: Path) -> None:
    link = Link()
    opened = bridge(tmp_path, link=link)
    too_big = Media("image", "image/png", b"x" * (MAX_IMAGE_BYTES + 1))
    many = [Media("image", "image/jpeg", PNG) for _ in range(MAX_IMAGES + 1)]
    wrong = Media("image", "image/tiff", PNG)
    voice = Media("voice", "audio/amr", b"\x00")

    asyncio.run(opened._turn(Message(text="look", media=[too_big, wrong, voice, *many]), "c"))

    _, prompt, images = link.asked[0]
    assert len(images) == MAX_IMAGES, "the broker takes four; the fifth waits for another message"
    assert "over the 4 MiB limit" in prompt
    assert "is not one the agent takes" in prompt
    assert "1 voice not forwarded" in prompt
    assert "at most 4 go with one message" in prompt


def test_a_sender_who_is_not_allowed_is_refused_with_the_id_to_allow(tmp_path: Path) -> None:
    im, link = Im(), Link()
    opened = bridge(tmp_path, im=im, link=link, settings=BridgeSettings(allow=frozenset({"someone-else"})))

    asyncio.run(opened._turn(Message(text="rm -rf", user_id="stranger"), "c"))

    assert link.asked == [], "nothing reaches the agent"
    assert "stranger" in im.sent[0][1] and "not allowed" in im.sent[0][1]


def test_a_daemon_that_cannot_start_is_explained_and_the_message_is_not_asked_again(tmp_path: Path) -> None:
    im, link = Im(), Link()
    guard = Guard(error=DaemonUnavailable("the model rejected the key"))
    opened = bridge(tmp_path, im=im, link=link, guard=guard)

    asyncio.run(opened._turn(Message(text="hello"), "c"))

    assert link.asked == []
    assert "the model rejected the key" in im.sent[0][1]
    assert opened.state.answered(_identity(Message(text="hello"))), "the message is behind us; no second answer"


def test_a_link_that_fails_says_so_in_the_chat(tmp_path: Path) -> None:
    im = Im()
    opened = bridge(tmp_path, im=im, link=Link(error=LinkError("the session broker is not reachable")))

    asyncio.run(opened._turn(Message(text="hello"), "c"))

    assert "not reachable" in im.sent[0][1]


def test_an_answer_that_arrives_empty_is_still_an_answer(tmp_path: Path) -> None:
    im = Im()
    opened = bridge(tmp_path, im=im, link=Link(answer="   "))

    asyncio.run(opened._turn(Message(text="hello"), "c"))

    assert im.sent and "without an answer" in im.sent[0][1]


def test_the_same_event_delivered_twice_is_answered_once(tmp_path: Path) -> None:
    """A restart mid-batch re-delivers the batch; the state, not the agent, is what stops the second answer."""
    im = Im(
        [Result(Message(event_id="e1", text="hello"), "cur-1"), Result(Message(event_id="e1", text="hello"), "cur-2")]
    )
    opened = bridge(tmp_path, im=im, link=Link(answer="hi"))

    async def scenario() -> None:
        running = asyncio.ensure_future(opened.run())
        for _ in range(200):
            if im.sent:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        opened.stop()
        await running

    asyncio.run(scenario())

    assert len(im.sent) == 1, "one answer for one message, however many times the platform hands it over"
    assert BridgeState.load(tmp_path / "state.json").cursor == "cur-2", "the cursor still moves past it"


def test_the_bridge_runs_a_message_end_to_end_and_stops_when_asked(tmp_path: Path) -> None:
    im = Im([Result(Message(text="hello"), "cur-2")])
    link = Link(answer="hi there")
    opened = bridge(tmp_path, im=im, link=link)

    async def scenario() -> None:
        running = asyncio.ensure_future(opened.run())
        for _ in range(200):
            if im.sent:
                break
            await asyncio.sleep(0.01)
        opened.stop()
        await running

    asyncio.run(scenario())

    assert im.sent == [("chat", "hi there", "token")]
    assert BridgeState.load(tmp_path / "state.json").cursor == "cur-2"


def test_a_long_answer_is_split_on_line_breaks_below_the_limit() -> None:
    text = "\n".join(["line " * 10 for _ in range(20)])

    pieces = split(text, 100)

    assert all(len(piece) <= 100 for piece in pieces)
    assert "".join(pieces).replace("\n", "") == text.replace("\n", ""), "nothing is lost between the pieces"
    assert split("x" * 250, 100) == ["x" * 100, "x" * 100, "x" * 50], "a line with no break is cut at the limit"


def test_a_picture_that_did_not_fit_still_sends_the_text(tmp_path: Path) -> None:
    """The broker refuses the whole message over its picture limit, so the text must not carry the picture."""
    link = Link()
    opened = bridge(tmp_path, link=link)
    huge = Media("image", "image/png", b"x" * (MAX_IMAGE_BYTES + 1))

    asyncio.run(opened._turn(Message(text="read this", media=[huge]), "c"))

    _, prompt, images = link.asked[0]
    assert images == [] and "read this" in prompt


def test_an_answer_the_chat_will_not_take_is_not_run_again_for_ever(tmp_path: Path) -> None:
    """A send that keeps failing must not turn into a new agent turn every time the message is re-delivered."""

    class Blocked(Im):
        async def send(self, chat_id, text, *, context_token=None):
            raise RuntimeError("this contact does not accept messages")

    im, link = Blocked(), Link()
    opened = bridge(tmp_path, im=im, link=link)
    for attempt in range(3):
        asyncio.run(opened._turn(Message(text="hello"), f"cur-{attempt}"))

    assert len(link.asked) == 2, "one answer, then one retry; not a turn per delivery"
    assert opened.state.answered(_identity(Message(text="hello"))), "then the message is behind us, reason in the log"


def test_a_chat_is_answered_with_the_context_it_last_had(tmp_path: Path) -> None:
    """A message that arrives without a context token is still answered inside its conversation."""
    im, link = Im(), Link()
    opened = bridge(tmp_path, im=im, link=link)
    opened.state.chats["chat"] = "older-context"

    asyncio.run(opened._turn(Message(text="hello", reply_token=None), "c"))

    assert im.sent[0][2] == "older-context"


def test_a_poll_that_hangs_is_abandoned_and_asked_again(tmp_path: Path) -> None:
    """A dropped connection looks exactly like a quiet chat; the bridge must not wait on it for ever."""
    said: list[str] = []

    class Stuck(Im):
        calls = 0

        async def receive(self, cursor=None):
            Stuck.calls += 1
            await asyncio.sleep(3600)

    opened = bridge(
        tmp_path,
        im=Stuck(),
        settings=BridgeSettings(allow_all=True, poll_timeout=0.05),
    )
    opened.error = said.append

    async def scenario() -> None:
        running = asyncio.ensure_future(opened.run())
        for _ in range(300):
            if Stuck.calls >= 2:
                break
            await asyncio.sleep(0.01)
        opened.stop()
        await running

    asyncio.run(scenario())

    assert Stuck.calls >= 2, "it asks again rather than staying on the dead connection"
    assert said == [], "and a quiet chat is not reported as a fault"


def test_a_new_message_with_a_reused_sequence_number_is_not_taken_for_an_answered_one(tmp_path: Path) -> None:
    """The platform's fallback id is a per-chat counter that starts at 1 again after every login.

    Remembered alone, "1" named the first message for ever, and every later "1" was silently dropped as a repeat.
    """
    im, link = Im(), Link(answer="hi")
    opened = bridge(tmp_path, im=im, link=link)

    asyncio.run(opened._turn(Message(event_id="1", text="first, before the re-login"), "c1"))
    asyncio.run(opened._turn(Message(event_id="1", text="a different message with the same number"), "c2"))

    assert len(link.asked) == 2, "the second message ran a turn"
    assert len(im.sent) == 2


def test_a_genuine_redelivery_of_the_same_message_is_still_answered_once(tmp_path: Path) -> None:
    im, link = Im(), Link(answer="hi")
    opened = bridge(tmp_path, im=im, link=link)

    asyncio.run(opened._turn(Message(event_id="7", text="hello"), "c1"))
    asyncio.run(opened._turn(Message(event_id="7", text="hello"), "c1"))

    assert len(link.asked) == 1 and len(im.sent) == 1


def test_the_same_number_in_another_chat_is_another_message(tmp_path: Path) -> None:
    im, link = Im(), Link(answer="hi")
    opened = bridge(tmp_path, im=im, link=link)

    asyncio.run(opened._turn(Message(event_id="1", chat_id="alice", text="hello"), "c1"))
    asyncio.run(opened._turn(Message(event_id="1", chat_id="bob", text="hello"), "c2"))

    assert len(link.asked) == 2
