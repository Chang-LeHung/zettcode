"""The bridge's own session: who may answer it, and what a lost connection is called."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from zettcode.broker.models import Incoming
from zettcode.broker.protocol import PeerInfo
from zettcode.im.link import LinkError, SessionLink


class FakeBroker:
    """The slice of `BrokerClient` the link uses."""

    def __init__(self, fail: Exception | None = None) -> None:
        self.limits = SimpleNamespace(max_text=10_000)
        self.sent: list[tuple[str, str, dict]] = []
        self.fail = fail
        self.session = None

    async def send(self, to: str, text: str, **kwargs) -> None:
        self.sent.append((to, text, kwargs))
        if self.fail is not None:
            raise self.fail

    def set_session(self, info) -> None:
        self.session = info

    async def wait_connected(self, timeout: float = 0.0) -> bool:
        return True

    async def close(self) -> None:
        return None


def peer(session_id: str, handle: str = "daemon") -> PeerInfo:
    return PeerInfo(session_id, handle, "", "", "working", direct=True)


def incoming(session_id: str, text: str = "answer", *, group: str = "") -> Incoming:
    return Incoming(sender=peer(session_id), text=text, hops=1, via="agent", direct=True, group=group)


def link(broker: FakeBroker, *, timeout: float = 5.0) -> SessionLink:
    made = SessionLink(session_id="im-weixin-1", timeout=timeout)
    made._client = broker
    return made


def test_only_the_daemon_that_was_asked_may_answer() -> None:
    made = link(FakeBroker())
    made._waiting, made._asking = True, "01daemon"

    refused = made._heard(incoming("01someone-else"))
    grouped = made._heard(incoming("01daemon", group="team"))
    taken = made._heard(incoming("01daemon", "the answer"))

    assert refused.accepted is False and "not for another session" in refused.reason
    assert grouped.accepted is False, "a group message is not this chat's answer"
    assert taken.accepted is True and made._answers.get_nowait() == "the answer"


def test_a_message_while_no_turn_is_waiting_is_refused_rather_than_queued() -> None:
    made = link(FakeBroker())

    assert made._heard(incoming("01daemon")).accepted is False
    assert made._answers.empty()


def test_a_lost_connection_is_reported_as_one_not_as_a_silent_agent() -> None:
    made = link(FakeBroker())

    async def scenario() -> None:
        asking = asyncio.ensure_future(made.ask("01daemon", "hello"))
        for _ in range(200):
            if made._waiting:
                break
            await asyncio.sleep(0.01)
        assert made._waiting, "the turn is waiting for an answer before the broker goes away"
        made._trouble("the session broker is out of reach")
        with pytest.raises(LinkError) as failed:
            await asking
        assert "out of reach" in str(failed.value)
        assert "finished without an answer" not in str(failed.value)

    asyncio.run(scenario())


def test_an_answer_that_never_comes_is_a_timeout_and_not_a_claim_that_it_is_still_working() -> None:
    made = link(FakeBroker(), timeout=0.05)

    with pytest.raises(LinkError) as failed:
        asyncio.run(made.ask("01daemon", "hello"))

    assert "did not answer in" in str(failed.value)
    assert "is still working on it" not in str(failed.value)


def test_a_refused_send_says_which_refusal_it_was() -> None:
    from zettcode.broker.models import SendError

    made = link(FakeBroker(fail=SendError("gone", "nobody there")))

    with pytest.raises(LinkError) as failed:
        asyncio.run(made.ask("01daemon", "hello"))

    assert "not connected to the session broker" in str(failed.value)


def test_a_message_is_shortened_to_what_the_broker_takes() -> None:
    broker = FakeBroker()
    broker.limits = SimpleNamespace(max_text=100)

    with pytest.raises(LinkError):  # nothing answers it; what was sent is the point
        asyncio.run(link(broker, timeout=0.01).ask("01daemon", "x" * 500))

    text = broker.sent[0][1]
    assert len(text) <= 100 and "not sent" in text
