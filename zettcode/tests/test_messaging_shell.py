"""The shell and the other sessions: a message received becomes a turn, a draft addressed with ``@`` is sent.

Every test here runs a real shell against a real broker (run inside the test, as the broker tests do)
with a second client standing in for the other session, so what is checked is what crosses the wire and
what is left on screen, not what a stand-in said it would do.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
from zett_agent.events import AgentEvent, AgentEventType
from zett_agent.messages import AssistantMessage, UserMessage

from broker_helpers import Host, Inbox, client_for, eventually, session
from test_zettcode_app import FakeClient, FakeRuntime, _harness, _rendered, rows_and_commands
from zettcode.app import ZettCodeApp
from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.app.agent.conversation.entries import RelayEntry, TextEntry
from zettcode.app.agent.dialogue.relay import RELAY, Relayed
from zettcode.app.agent.extensions.messenger import Messenger
from zettcode.app.ui import updating as updating_module
from zettcode.app.ui.messaging import MAX_INBOX
from zettcode.broker.client import BrokerClient, Receipt, SendError

ME = "session-0001"
BOB = "02b20c86-bbbb-7000-8000-000000000002"
CAL = "03c30d97-cccc-7000-8000-000000000003"

DONE = [AgentEvent(AgentEventType.RUN_COMPLETED, "s", message=AssistantMessage(content="done"))]


@pytest.fixture(autouse=True)
def _no_release_check(monkeypatch):
    async def offline(path):
        return None

    monkeypatch.setattr(updating_module, "check_for_update", offline)


@pytest.fixture
async def host(tmp_path: Path):
    server = Host(tmp_path)
    await server.start()
    yield server
    await server.stop()


@dataclass
class Shell:
    """One running shell, the fake model behind it, and the connection it talks through."""

    app: ZettCodeApp
    harness: object
    model: FakeClient
    messenger: Messenger

    @property
    def entries(self):
        return self.app.transcript.entries

    def relays(self) -> list[RelayEntry]:
        return [entry for entry in self.entries if isinstance(entry, RelayEntry)]

    def users(self) -> list[str]:
        return [entry.text for entry in self.entries if isinstance(entry, TextEntry) and entry.kind == "user"]

    def notices(self) -> list[str]:
        return [entry.text for entry in self.entries if isinstance(entry, TextEntry) and entry.kind == "notice"]

    def sent_to_model(self) -> list[UserMessage]:
        return [message for message in self.model.messages if isinstance(message, UserMessage)]

    def rows(self, width: int = 80) -> list[str]:
        return _rendered(self.app.transcript, width)

    def type(self, text: str) -> None:
        self.harness.write(text)
        self.harness.press("enter")

    async def settle(self) -> None:
        while self.app.task is not None and not self.app.task.done():
            await asyncio.wait_for(asyncio.shield(self.app.task), 3)
        await asyncio.sleep(0.02)


@pytest.fixture
async def make(host: Host):
    """Build a shell on the host's broker; every shell and every other session is closed afterwards."""
    opened: list[Shell] = []
    others: list[BrokerClient] = []

    async def shell(*, events=None, hold: bool = False, block: bool = False, connect: bool = True) -> Shell:
        client = FakeClient(events if events is not None else DONE, hold=hold, block=block)
        runtime = FakeRuntime(client, plugins=rows_and_commands())
        messenger = Messenger(client_for(host.directory), workspace="/work")
        runtime.messenger = messenger
        app = ZettCodeApp(ZettCodeAgent(runtime))
        app.app.resize(80, 24)
        app.app.mount()
        opened.append(Shell(app, _harness(app), client, messenger))
        if connect:
            app.start_background()
            await eventually(lambda: any(e.session_id == ME for e in host.broker.roster.entries()), 3)
        return opened[-1]

    async def other(session_id: str = BOB, title: str = "bob", **options) -> tuple[BrokerClient, Inbox]:
        inbox = options.pop("inbox", None) or Inbox()
        client = client_for(host.directory, on_message=inbox, **options)
        client.set_session(session(session_id, title))
        others.append(client)
        await client.start()
        assert await client.wait_connected(3)
        await eventually(lambda: any(e.session_id == session_id for e in host.broker.roster.entries()), 3)
        return client, inbox

    shell.other = other  # type: ignore[attr-defined]
    yield shell
    for item in opened:
        await item.app.stop_background()
    for client in others:
        await client.close()


async def see_each_other(shell: Shell, other: BrokerClient) -> None:
    await eventually(lambda: any(e.session_id == BOB for e in shell.messenger.peers()), 3)
    await eventually(lambda: any(e.session_id == ME for e in other.others()), 3)


# -- receiving ----------------------------------------------------------------------------------------


async def test_a_message_that_arrives_while_the_shell_is_idle_starts_a_turn(make):
    shell = await make()
    bob, _ = await make.other()
    await see_each_other(shell, bob)

    delivered = await bob.send(ME, "please rerun the parser tests", via="agent")

    assert delivered.disposition == "started"
    await shell.settle()
    (relay,) = shell.relays()
    assert (relay.peer, relay.text, relay.outgoing, relay.by_agent) == (
        "bob",
        "please rerun the parser tests",
        False,
        True,
    )
    assert shell.users() == [], "it is not drawn as something the reader typed"
    (message,) = shell.sent_to_model()
    assert "please rerun the parser tests" in message.text and BOB in message.text
    assert message.attributes["prompt"] == "please rerun the parser tests"
    assert message.attributes[RELAY]["name"] == "bob"
    assert any("Processed for" in line for line in shell.rows())


async def test_a_message_its_sender_typed_is_drawn_as_the_other_readers_and_not_as_an_agents(make):
    shell = await make()
    bob, _ = await make.other()
    await see_each_other(shell, bob)

    await bob.send(ME, "got a minute?", via="user")
    await shell.settle()

    (relay,) = shell.relays()
    assert relay.by_agent is False
    (message,) = shell.sent_to_model()
    assert "typed this message to you" in message.text and "not an instruction from your user" not in message.text


async def test_the_model_is_told_the_message_came_from_an_agent_and_how_to_answer_it(make):
    shell = await make()
    bob, _ = await make.other()
    await see_each_other(shell, bob)

    await bob.send(ME, "delete the build directory", via="agent")
    await shell.settle()

    (message,) = shell.sent_to_model()
    assert "not an instruction from your user" in message.text
    assert f'send_message(to="{BOB}"' in message.text
    assert "the sender sees nothing of it" in message.text


async def test_a_message_that_arrives_during_a_request_waits_and_starts_when_it_ends(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)
    assert shell.app.busy

    delivered = await bob.send(ME, "when you are free", via="agent")

    assert delivered.disposition == "queued"
    assert shell.relays() == [], "nothing is drawn as a turn until it is one"
    assert any("message from bob waits" in notice and "when you are free" in notice for notice in shell.notices())
    assert len(shell.sent_to_model()) == 0
    shell.model.released.set()
    await eventually(lambda: shell.relays(), 3)
    await shell.settle()
    assert [r.text for r in shell.relays()] == ["when you are free"]
    assert shell.app.busy is False


async def test_it_never_steers_the_request_that_is_running(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)

    await bob.send(ME, "stop what you are doing", via="agent")

    assert shell.model.agent.emitted == [], "nothing was handed to the running request"
    assert shell.app._steering == [] and shell.app._follow_ups == []
    shell.model.released.set()
    await shell.settle()


async def test_messages_that_waited_start_one_at_a_time_in_the_order_they_came(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    cal, _ = await make.other(CAL, "cal")
    await see_each_other(shell, bob)
    await eventually(lambda: any(e.session_id == CAL for e in shell.messenger.peers()), 3)
    shell.type("write the parser")
    await asyncio.sleep(0.02)

    await bob.send(ME, "first")
    await cal.send(ME, "second")
    await bob.send(ME, "third")
    shell.model.released.set()
    await eventually(lambda: len(shell.relays()) == 3, 5)
    await shell.settle()

    assert [(r.peer, r.text) for r in shell.relays()] == [("bob", "first"), ("cal", "second"), ("bob", "third")]
    assert [m.attributes["prompt"] for m in shell.sent_to_model()] == ["first", "second", "third"]


async def test_a_follow_up_the_reader_queued_goes_before_a_message_that_arrived_later(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)
    shell.harness.write("then add tests")
    shell.harness.press("enter")
    shell.harness.write("f")
    await asyncio.sleep(0)
    await bob.send(ME, "from bob")

    shell.model.released.set()
    await eventually(lambda: shell.relays(), 5)
    await shell.settle()

    texts = [m if isinstance(m, str) else m.attributes.get("prompt") for m in shell.model.messages]
    assert texts.index("then add tests") < texts.index("from bob")


async def test_a_shell_with_a_full_inbox_refuses_with_a_reason_the_sender_can_read(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)

    for number in range(MAX_INBOX):
        await bob.send(ME, f"message {number}")
    with pytest.raises(SendError) as refused:
        await bob.send(ME, "one too many")

    assert "waiting" in str(refused.value)
    assert len(shell.app._inbox) == MAX_INBOX
    shell.model.released.set()
    await eventually(lambda: len(shell.relays()) == MAX_INBOX, 15)
    await shell.settle()


async def test_a_stopped_turn_started_by_a_message_ends_like_any_other_and_the_next_one_still_starts(make):
    shell = await make(block=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    await bob.send(ME, "long job")
    await eventually(lambda: shell.app.busy and shell.messenger.answering is not None, 3)
    assert shell.messenger.answering.text == "long job"

    shell.harness.press("ctrl+c")
    await shell.settle()

    assert shell.messenger.answering is None
    assert "stopped" in shell.notices()
    assert shell.app.busy is False
    shell.model.block = False
    delivered = await bob.send(ME, "second job")
    assert delivered.disposition == "started"
    await shell.settle()


async def test_a_failing_turn_started_by_a_message_reports_the_error_and_frees_the_shell(make):
    shell = await make()
    bob, _ = await make.other()
    await see_each_other(shell, bob)

    async def broken(message, **options):
        raise RuntimeError("the provider is down")
        yield  # pragma: no cover

    shell.model.stream = broken  # type: ignore[method-assign]
    delivered = await bob.send(ME, "hello")
    await shell.settle()

    assert delivered.disposition == "started"
    assert any("the provider is down" in row for row in shell.rows())
    assert shell.app.busy is False and shell.messenger.answering is None


async def test_the_answer_a_message_is_working_on_carries_its_hops_into_the_message_it_sends(make):
    shell = await make(hold=True)
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    await bob.send(ME, "question", hops=3, via="agent")
    await eventually(lambda: shell.messenger.answering is not None, 3)
    assert shell.messenger.answering.hops == 4

    await shell.messenger.send(BOB, "answer")

    assert inbox.messages[-1].hops == 5, "the message the turn sent is hop five"
    shell.model.released.set()
    await shell.settle()
    assert shell.messenger.answering is None


async def test_a_turn_the_reader_began_sends_with_no_hops_behind_it(make):
    shell = await make(hold=True)
    bob, inbox = await make.other()
    await see_each_other(shell, bob)
    shell.type("tell bob hello")
    await asyncio.sleep(0.02)

    await shell.messenger.send(BOB, "hello bob")

    assert inbox.messages[-1].hops == 1
    shell.model.released.set()
    await shell.settle()


async def test_a_message_after_the_shell_has_left_is_refused(make, host):
    shell = await make()
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    await shell.app.stop_background()

    receipt = shell.app._relay_received(Relayed(BOB, "bob", "late"))

    assert receipt.accepted is False and "closing" in receipt.reason
    await eventually(lambda: not any(e.session_id == ME for e in host.broker.roster.entries()), 3)


# -- sending ------------------------------------------------------------------------------------------


async def test_a_draft_that_begins_with_the_name_of_a_session_is_sent_there_and_not_to_the_model(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    shell.type("@bob can you review the parser change?")
    await eventually(lambda: shell.relays(), 3)
    await shell.settle()

    (message,) = inbox.messages
    assert message.text == "can you review the parser change?"
    assert (message.via, message.hops, message.sender.session_id) == ("user", 1, ME)
    (relay,) = shell.relays()
    assert (relay.peer, relay.outgoing, relay.note) == ("bob", True, "delivered")
    assert shell.model.messages == [], "the model was not asked anything"
    assert shell.app.composer.text == ""
    assert shell.app.busy is False


@pytest.mark.parametrize(
    ("draft", "sent"),
    [
        ("@bob: hello", "hello"),
        ("@bob, hello", "hello"),
        ("@bob;  hello  ", "hello"),
        ("   @bob hello", "hello"),
        ("@Bob hello", "hello"),
        ("@bob\nhello\nthere", "hello\nthere"),
    ],
)
async def test_how_the_name_is_separated_from_the_message_does_not_matter(make, draft, sent):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    shell.harness.write(draft)
    shell.harness.press("enter")
    await eventually(lambda: inbox.messages, 3)

    assert inbox.messages[0].text == sent


async def test_a_message_to_a_session_is_sent_while_this_one_is_busy_without_asking_what_it_is(make):
    shell = await make(hold=True)
    bob, inbox = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)
    assert shell.app.busy

    shell.type("@bob I am in the middle of something")
    await eventually(lambda: inbox.messages, 3)

    assert inbox.messages[0].text == "I am in the middle of something"
    assert shell.app._steering == [] and shell.app._follow_ups == []
    assert not any(page for page in shell.app.app.screens if getattr(page, "name", "") == "page")
    assert shell.app.busy, "the request in flight is untouched"
    shell.model.released.set()
    await shell.settle()


async def test_the_note_on_a_sent_message_says_when_the_other_session_queued_it(make):
    shell = await make()
    bob, inbox = await make.other(inbox=Inbox(Receipt(True, "", "queued")))
    await see_each_other(shell, bob)

    shell.type("@bob later is fine")
    await eventually(lambda: shell.relays(), 3)

    assert shell.relays()[0].note == "queued"


async def test_a_message_the_other_session_refuses_is_reported_with_its_reason_and_is_not_drawn_as_sent(make):
    shell = await make()
    bob, inbox = await make.other(inbox=Inbox(Receipt(False, "bob is shutting down")))
    await see_each_other(shell, bob)

    shell.type("@bob hello")
    await eventually(lambda: any("not sent to @bob" in row for row in shell.rows()), 3)

    assert any("bob is shutting down" in row for row in shell.rows())
    assert shell.relays() == []
    assert shell.app.busy is False


async def test_a_session_that_left_between_the_menu_and_enter_is_reported_not_silently_dropped(make, host):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)
    await bob.close()
    # The shell's list still holds bob for a moment: it has not heard yet.
    shell.messenger.client._roster = (*shell.messenger.client.roster, *[e for e in [_ghost()]])

    shell.type("@ghost are you there?")
    await eventually(lambda: any("not sent to @ghost" in row for row in shell.rows()), 3)

    assert shell.relays() == []


def _ghost():
    from zettcode.broker.client import RosterEntry

    return RosterEntry(session_id="ghost-id", handle="ghost", title="ghost", workspace="/work", status="idle")


async def test_a_draft_with_nothing_after_the_name_stays_in_the_composer(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    shell.type("@bob")
    await asyncio.sleep(0.05)

    assert shell.app.composer.text == "@bob"
    assert inbox.messages == [] and shell.model.messages == []
    assert "write the message after @bob" in shell.app._flash_text()


async def test_a_message_over_the_limit_stays_in_the_composer_and_says_so(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    shell.harness.write("@bob ")
    shell.harness.paste("x" * 32_001)
    shell.harness.press("enter")
    await asyncio.sleep(0.05)

    assert inbox.messages == []
    assert "limited to" in shell.app._flash_text()


async def test_a_name_nobody_has_is_an_ordinary_draft_for_the_model(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    shell.type("@nobody what does this do")
    await shell.settle()

    assert inbox.messages == []
    assert len(shell.model.messages) == 1


async def test_a_session_named_later_in_the_draft_is_a_reference_the_model_is_told_about(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    shell.type("ask @bob whether the build is green")
    await shell.settle()

    assert inbox.messages == [], "nothing is sent on a mention in passing"
    (message,) = shell.sent_to_model()
    assert "ask @bob whether the build is green" == message.attributes["prompt"]
    assert BOB in message.text and "send_message" in message.text


async def test_the_model_reads_the_session_in_place_of_the_at_sign_and_is_told_how_to_reach_it(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    shell.type("please ask @bob to rerun the parser tests")
    await shell.settle()

    (message,) = shell.sent_to_model()
    said, _, explained = message.text.partition("\n\n")
    assert said == 'please ask session "bob" to rerun the parser tests'
    assert "@bob" in explained and "not a file or a skill" in explained
    assert f'send_message(to="{BOB}", message=...)' in explained
    assert shell.users() == ["please ask @bob to rerun the parser tests"], "the reader sees what was typed"
    assert inbox.messages == [], "the shell itself sent nothing: whether to is the agent's decision"


async def test_a_queued_follow_up_names_the_session_as_it_is_when_it_starts_not_when_it_was_typed(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)
    shell.harness.write("then tell @bob it is done")
    shell.harness.press("enter")
    shell.harness.write("f")
    await asyncio.sleep(0)

    shell.model.released.set()
    await shell.settle()

    last = shell.sent_to_model()[-1]
    assert last.text.startswith('then tell session "bob" it is done\n\n')
    assert last.attributes["prompt"] == "then tell @bob it is done"


async def test_a_session_that_left_before_the_follow_up_started_is_left_as_typed(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)
    shell.harness.write("then tell @bob it is done")
    shell.harness.press("enter")
    shell.harness.write("f")
    await asyncio.sleep(0)
    await bob.close()
    await eventually(lambda: not shell.messenger.peers(), 3)

    shell.model.released.set()
    await shell.settle()

    assert shell.model.messages[-1] == "then tell @bob it is done", "nothing to explain, so it goes as typed"


async def test_a_message_that_steers_the_running_request_explains_the_at_sign_too(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)
    shell.harness.write("also tell @bob")

    taken = shell.app._steer_now("also tell @bob", shell.app.composer.parts())

    assert taken is True
    event, _ = shell.model.agent.emitted[-1]
    steered = event.payload["message"]
    assert steered.text.startswith('also tell session "bob"\n\n') and "send_message" in steered.text
    shell.model.released.set()
    await shell.settle()


async def test_a_file_that_is_named_like_a_session_is_still_a_file_when_no_session_has_the_name(make, tmp_path):
    shell = await make()
    shell.type("@README.md summarise this")
    await shell.settle()

    assert len(shell.model.messages) == 1


async def test_an_escape_sequence_in_a_message_never_reaches_the_other_session(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    await shell.messenger.send(BOB, "plain \x1b[31mred\x1b[0m text\x07", via="user")

    assert inbox.messages[0].text == "plain red text"


async def test_an_image_in_the_draft_is_refused_for_a_message_to_a_session(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)
    shell.harness.write("@bob look at ")
    shell.app.composer.attach_image(b"\x89PNG", "image/png")
    shell.harness.press("enter")
    await asyncio.sleep(0.05)

    assert inbox.messages == []
    assert "text only" in shell.app._flash_text()


async def test_slash_commands_are_not_mistaken_for_a_message_to_a_session(make):
    shell = await make()
    bob, inbox = await make.other()
    await see_each_other(shell, bob)

    shell.type("/help")
    await shell.settle()

    assert inbox.messages == []


# -- what the others see ------------------------------------------------------------------------------


async def test_the_session_is_registered_idle_and_follows_busy_and_back(make, host):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    mine = lambda: next(e for e in bob.others() if e.session_id == ME)  # noqa: E731
    await eventually(lambda: mine().status == "idle", 3)

    shell.type("write the parser")
    await eventually(lambda: mine().status == "working", 3)
    shell.model.released.set()
    await shell.settle()

    await eventually(lambda: mine().status == "idle", 3)


async def test_a_title_is_shown_to_the_others_when_it_is_set_and_when_it_changes(make):
    shell = await make()
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.app._session_title = "Fix the parser"
    shell.app._sync_messaging()

    await eventually(lambda: any(e.title == "Fix the parser" for e in bob.others()), 3)
    assert [e.handle for e in bob.others() if e.session_id == ME] == ["fix-the-parser"]

    shell.app._session_title = "Fix the lexer"
    shell.app._sync_messaging()
    await eventually(lambda: any(e.title == "Fix the lexer" for e in bob.others()), 3)


async def test_a_new_session_replaces_the_old_registration(make, host):
    shell = await make()
    bob, _ = await make.other()
    await see_each_other(shell, bob)

    shell.type("/new")
    await shell.settle()

    await eventually(lambda: [e.session_id for e in bob.others()] == ["session-0002"], 3)


async def test_messages_that_waited_when_the_session_changed_are_announced(make):
    shell = await make(hold=True)
    bob, _ = await make.other()
    await see_each_other(shell, bob)
    shell.type("write the parser")
    await asyncio.sleep(0.02)
    await bob.send(ME, "waiting")
    assert len(shell.app._inbox) == 1

    shell.app.agent.runtime.use_session("session-0009")
    shell.app._sync_messaging()

    assert any("1 message from other sessions was waiting" in n for n in shell.notices())
    shell.model.released.set()
    await shell.settle()


async def test_sessions_that_come_and_go_change_the_completion_menu_without_waiting_on_anything(make, host):
    shell = await make()
    assert shell.app.mentions.candidates("bo") == ()
    bob, _ = await make.other()
    await see_each_other(shell, bob)

    (found,) = [m for m in shell.app.mentions.candidates("bo") if m.kind == "session"]

    assert (found.token, found.name, found.description) == ("@bob", "bob", "bob \u00b7 work")
    await bob.close()
    await eventually(lambda: not shell.app.mentions.candidates("bo"), 3)


# -- with nobody to talk to ---------------------------------------------------------------------------


async def test_a_shell_with_no_broker_behaves_as_it_always_did(make, host):
    await host.stop()
    shell = await make(connect=False)
    shell.app.start_background()
    await asyncio.sleep(0.1)

    shell.type("@bob hello")
    await shell.settle()
    shell.type("plain question")
    await shell.settle()

    assert len(shell.model.messages) == 2
    assert shell.messenger.peers() == () and not shell.messenger.connected


async def test_a_shell_without_a_messenger_has_no_session_names_and_no_sending(tmp_path):
    client = FakeClient(DONE)
    runtime = FakeRuntime(client, plugins=rows_and_commands())
    app = ZettCodeApp(ZettCodeAgent(runtime))
    app.app.resize(80, 24)
    app.app.mount()
    harness = _harness(app)

    harness.write("@bob hello")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2)

    assert app.messenger is None
    assert [m for m in client.messages] == ["@bob hello"] or len(client.messages) == 1
    assert not any(m.kind == "session" for m in app.mentions.candidates(""))
    app.start_background()
    await app.stop_background()


async def test_the_header_says_what_this_session_is_called_so_the_reader_can_tell_others(make):
    """In the header, beside the title, so the status line keeps its room for the counters."""
    shell = await make()
    await eventually(lambda: shell.messenger.handle, 3)

    def header() -> str:
        return shell.harness.render().text.splitlines()[0]

    def status() -> str:
        return shell.harness.render().text.splitlines()[-1]

    assert shell.messenger.handle == "work"  # untitled: named for the folder it works in
    await eventually(lambda: "@work" in header(), 3)
    assert "New session \u00b7 @work" in header() and "@work" not in status()

    shell.app._session_title = "Fix the parser"
    shell.app._sync_messaging()
    await eventually(lambda: "@fix-the-parser" in header(), 3)
    assert "Fix the parser \u00b7 @fix-the-parser" in header()
    assert "@work" not in header() and "@fix-the-parser" not in status()


async def test_a_shell_with_messaging_off_shows_no_name(tmp_path):
    runtime = FakeRuntime(FakeClient(DONE), plugins=rows_and_commands())
    app = ZettCodeApp(ZettCodeAgent(runtime))
    app.app.resize(80, 24)
    app.app.mount()

    assert "@" not in _harness(app).render().text.splitlines()[-1]


# -- a session another process has open ---------------------------------------------------------------------------


def _lose_the_lock(shell: Shell) -> None:
    """The other terminal takes the session this shell was in, as far as this shell can tell."""
    runtime = shell.app.agent.runtime
    runtime.held_elsewhere.add(ME)
    runtime._claim()
    shell.app._sync_lock()


async def test_a_locked_session_does_not_register_so_nobody_can_send_it_a_message(make, host):
    shell = await make()
    bob, _ = await make.other()
    await see_each_other(shell, bob)

    _lose_the_lock(shell)

    await eventually(lambda: not any(e.session_id == ME for e in host.broker.roster.entries()), 3)
    await eventually(lambda: not any(e.session_id == ME for e in bob.others()), 3)
    with pytest.raises(SendError) as refused:
        await bob.send("work", "are you there?")
    assert refused.value.reason == "unknown"


async def test_a_message_that_arrives_anyway_is_refused_with_the_reason_and_starts_no_turn(make):
    shell = await make()
    _lose_the_lock(shell)

    receipt = shell.app._relay_received(Relayed(sender_id="x", sender="bob", text="please run it", via="agent", hops=1))

    assert receipt.accepted is False and "read-only" in receipt.reason
    assert shell.model.messages == [] and shell.relays() == []


async def test_when_the_lock_comes_back_the_session_registers_again(make, host):
    shell = await make()
    _lose_the_lock(shell)
    await eventually(lambda: not any(e.session_id == ME for e in host.broker.roster.entries()), 3)

    runtime = shell.app.agent.runtime
    runtime.held_elsewhere.discard(ME)
    assert runtime.retake_session() is True
    shell.app._sync_lock()

    await eventually(lambda: any(e.session_id == ME for e in host.broker.roster.entries()), 3)


async def test_the_header_of_a_locked_session_has_no_name_to_be_reached_by(make):
    shell = await make()
    await eventually(lambda: shell.messenger.handle, 3)

    _lose_the_lock(shell)
    await eventually(lambda: not shell.messenger.handle, 3)

    assert "@work" not in shell.harness.render().text.splitlines()[0]
