"""The recap plugin, driven by the shell's two hooks and its own command."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from zettcode.app.commands import CommandContext
from zettcode.app.plugins import HOST_LINK, HostLink
from zettcode.app.plugins.loader import terminal_context
from zettcode.config import ModelConfig, ZettCodeConfig

from zettcode_recap import PROMPT, RecapPlugin

SESSION = "s-1"


class FakeSession:
    """What the shell's SDK client offers a recap: one side question, or a refusal."""

    def __init__(self, answer: str = "Fixing the parser; next, run the tests.") -> None:
        self.id = SESSION
        self.answer = answer
        self.asked: list[tuple[str, float | None, str]] = []
        self.locked = False
        self.refuse: Exception | None = None
        #: When set, ``ask`` waits for it, so a test can hold a recap in flight.
        self.gate: asyncio.Event | None = None
        #: When set, ``history`` waits for it, so a test can leave a seed reading while the session changes.
        self.history_gate: asyncio.Event | None = None
        self.history_messages: list[object] = []

    async def ask(self, question: str, *, on_event=None, timeout=None, cache="read") -> str:
        self.asked.append((question, timeout, cache))
        if self.gate is not None:
            await self.gate.wait()
        if self.refuse is not None:
            raise self.refuse
        return self.answer

    async def history(self):
        # The conversation is the one that was asked for when the call was made, even if the shell has moved on by
        # the time the store answers; only the one the test filled in has messages.
        asked_for = self.id
        if self.history_gate is not None:
            await self.history_gate.wait()
        return self.history_messages if asked_for == SESSION else []


class FakeTranscript:
    def __init__(self) -> None:
        self.notices: list[str] = []
        self.messages: list[str] = []

    def notice(self, text: str) -> None:
        self.notices.append(text)

    def markdown(self, text: str) -> None:
        self.messages.append(text)


class FakeUi:
    def markdown(self, text: str) -> None: ...

    def notice(self, text: str) -> None: ...

    def error(self, text: str) -> None: ...

    def notify(self, text: str, *, level: str = "info") -> None: ...


class FakeHost:
    def __init__(self, session: FakeSession | None = None) -> None:
        self.client = type("Client", (), {"session": session or FakeSession()})()
        self.transcript = FakeTranscript()
        self.redraws = 0

    def request_layout(self) -> None:
        self.redraws += 1


def build(tmp_path: Path, settings: dict[str, object] | None = None, host: FakeHost | None = None):
    """Activate the plugin against a config, with a shell attached when the test wants one."""
    config = ZettCodeConfig(
        workspace=tmp_path,
        models=(ModelConfig(model="m", token="t"),),
        plugin_settings={"recap": settings or {}},
    )
    link = HostLink()
    ctx = terminal_context(config, {HOST_LINK: link}, name="recap")
    plugin = RecapPlugin()
    plugin.activate(ctx)
    if host is not None:
        link.attach(host)  # type: ignore[arg-type]
    return plugin, ctx, link


async def settled(predicate, *, ticks: int = 200) -> None:
    """Let the plugin's background tasks run until the condition holds, or fail the test."""
    for _ in range(ticks):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("the plugin did not get where the test waited for")


async def test_coming_back_does_not_cancel_a_recap_the_reader_asked_for(tmp_path):
    """/recap is answered whatever the window does; only the unsolicited one is dropped when the reader returns."""
    session = FakeSession()
    session.gate = asyncio.Event()
    plugin, ctx, _link = build(tmp_path, {"after_seconds": 0}, host=FakeHost(session))
    (command,) = ctx.tui.registered_commands

    pending = await command.handler(CommandContext(argument="", ui=FakeUi()))
    asked = asyncio.ensure_future(pending.run)
    await settled(lambda: bool(session.asked))
    plugin.turn_started()
    session.gate.set()
    result = await asyncio.wait_for(asked, 1.0)

    assert result.notification == "Recap ready", "the command finished instead of being cancelled"
    plugin._cancel()


async def test_the_unsolicited_recap_is_dropped_when_a_turn_starts(tmp_path):
    session = FakeSession()
    session.gate = asyncio.Event()
    plugin, _ctx, _link = build(tmp_path, {"after_seconds": 0}, host=FakeHost(session))
    host = plugin._host()
    assert host is not None

    for _ in range(3):
        plugin.turn_ended(True)
    await settled(lambda: bool(session.asked))
    plugin.turn_started()
    session.gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert host.transcript.messages == [], "nothing is shown for a conversation that has moved on"


async def test_a_command_does_not_forget_the_automatic_recap_that_is_running(tmp_path):
    """Only the unsolicited recap is cancellable, so `/recap` must not take over — or drop — its handle."""
    session = FakeSession()
    session.gate = asyncio.Event()
    plugin, ctx, _link = build(tmp_path, host=FakeHost(session))
    (command,) = ctx.tui.registered_commands
    automatic = asyncio.ensure_future(asyncio.sleep(3600))
    plugin._asking = automatic

    pending = await command.handler(CommandContext(argument="", ui=FakeUi()))
    asked = asyncio.ensure_future(pending.run)
    await settled(lambda: bool(session.asked))
    assert plugin._asking is automatic, "the automatic recap can still be cancelled while a command's runs"

    session.gate.set()
    await asyncio.wait_for(asked, 1.0)
    automatic.cancel()
    plugin._cancel()


async def test_a_seed_read_before_a_session_change_does_not_count_for_the_new_one(tmp_path):
    """The reader can leave a conversation while its history is being read; those messages are not the new one's."""
    session = FakeSession()
    session.history_gate = asyncio.Event()
    session.history_messages = [type("Message", (), {"role": "user", "relay": None})()] * 10
    plugin, _ctx, _link = build(tmp_path, host=FakeHost(session))

    plugin.turn_ended(True)
    await asyncio.sleep(0)  # let the first seed ask the store, which is where it will be held
    session.id = "s-2"
    plugin.turn_ended(True)
    session.history_gate.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert plugin._turns == 1, "the old conversation's ten messages were dropped"
    plugin._cancel()


async def test_a_new_session_starts_its_own_count(tmp_path):
    """`/new` is a new conversation: the old one's three messages must not make the new one worth a recap."""
    session = FakeSession()
    plugin, _ctx, _link = build(tmp_path, host=FakeHost(session))

    for _ in range(3):
        plugin.turn_ended(True)
    assert plugin._turns == 3

    session.id = "s-2"
    plugin.turn_ended(True)

    assert plugin._turns == 1
    assert plugin.due() is False
    plugin._cancel()


async def test_a_resumed_conversation_is_measured_by_its_stored_messages(tmp_path):
    """One new turn in a long session can be worth a recap the moment the history is read, even if nobody looks away again."""
    session = FakeSession()
    session.history_messages = [
        type("Message", (), {"role": "user", "relay": None})(),
        type("Message", (), {"role": "assistant", "relay": None})(),
    ] * 10
    plugin, _ctx, _link = build(tmp_path, {"after_seconds": 0, "min_since_recap": 1}, host=FakeHost(session))

    plugin.turn_ended(True)
    await settled(lambda: bool(session.asked))

    assert plugin._turns == 10, "the stored user messages count"
    assert session.asked, "and the recap that count makes worthwhile was written"
    plugin._cancel()


def test_the_command_is_offered_and_both_hooks_are_taken(tmp_path):
    """`/recap` says words, so it is a plain command; the two hooks are the terminal's."""
    _plugin, ctx, _link = build(tmp_path)

    assert ctx.tui is not None
    assert [command.name for command in ctx.tui.registered_commands] == ["/recap"]
    assert ctx.commands.commands == ()
    assert ctx.tui.focus_handlers == (), "the wait is about turns, not the window"
    assert len(ctx.tui.turn_start_handlers) == 1 and len(ctx.tui.turn_end_handlers) == 1


def test_the_delay_is_the_shorter_of_its_own_seconds_and_the_cache_lifetime(tmp_path):
    plugin, _ctx, _link = build(tmp_path)

    assert plugin.delay == 180, "min(180, 0.8 × 300)"

    plugin.cache_ttl_seconds = 100
    assert plugin.delay == 80, "a short-lived cache is not worth waiting longer for"


async def test_a_conversation_that_is_too_short_arms_no_wait(tmp_path):
    session = FakeSession()
    plugin, _ctx, _link = build(tmp_path, host=FakeHost(session))

    for _ in range(2):
        plugin.turn_ended(True)
    await asyncio.sleep(0)

    assert plugin._timer is None and session.asked == []
    plugin._cancel()


async def test_a_reader_who_stayed_away_long_enough_gets_a_recap(tmp_path):
    session = FakeSession()
    plugin, _ctx, _link = build(tmp_path, {"after_seconds": 0}, host=FakeHost(session))
    host = plugin._host()
    assert host is not None

    for _ in range(3):
        plugin.turn_ended(True)
    await settled(lambda: bool(session.asked))

    assert session.asked == [(PROMPT, 60.0, "read")], "one side question, read-only, with a deadline"
    assert host.transcript.messages == ["> **Recap** \u00b7 Fixing the parser; next, run the tests."]
    assert host.redraws == 1, "the frame that shows it is asked for"
    plugin._cancel()


async def test_a_new_turn_drops_the_recap_that_was_waiting(tmp_path):
    """The reader asking again is the one thing that makes a recap about the past: it is dropped, not shown late."""
    session = FakeSession()
    plugin, _ctx, _link = build(tmp_path, host=FakeHost(session))

    for _ in range(3):
        plugin.turn_ended(True)
    assert plugin._timer is not None
    plugin.turn_started()
    await settled(lambda: plugin._timer is None)

    assert session.asked == []
    plugin._cancel()


async def test_two_recaps_are_not_made_from_the_same_two_turns(tmp_path):
    plugin, _ctx, _link = build(tmp_path, host=FakeHost())
    plugin._focused = False

    for _ in range(3):
        plugin.turn_ended(True)
    plugin._schedule()
    plugin._since_recap = 0  # as if a recap had just been made

    assert plugin.due() is False, "two more turns are needed before the next one"
    plugin._cancel()


async def test_the_command_summarises_now_and_shows_the_answer(tmp_path):
    session = FakeSession()
    plugin, ctx, _link = build(tmp_path, host=FakeHost(session))
    (command,) = ctx.tui.registered_commands

    pending = await command.handler(CommandContext(argument="", ui=FakeUi()))
    result = await pending.run

    assert result.notification == "Recap ready"
    assert result.message == "> **Recap** \u00b7 Fixing the parser; next, run the tests.", "words are the answer"
    assert session.asked[0][2] == "read"


async def test_the_command_tells_the_reader_why_there_is_no_recap(tmp_path):
    session = FakeSession()
    session.refuse = RuntimeError("the provider refused")
    plugin, ctx, _link = build(tmp_path, host=FakeHost(session))
    (command,) = ctx.tui.registered_commands

    pending = await command.handler(CommandContext(argument="", ui=FakeUi()))
    with pytest.raises(ValueError, match="Could not write a recap: the provider refused"):
        await pending.run


async def test_a_command_before_the_shell_exists_says_so_instead_of_crashing(tmp_path):
    _plugin, ctx, _link = build(tmp_path)
    (command,) = ctx.tui.registered_commands

    with pytest.raises(ValueError, match="not ready yet"):
        await command.handler(CommandContext(argument="", ui=FakeUi()))


async def test_the_settings_of_the_table_are_the_ones_the_recap_uses(tmp_path):
    plugin, _ctx, _link = build(
        tmp_path,
        {"after_seconds": 30, "cache_ttl_seconds": 600, "min_messages": 5, "min_since_recap": 1},
        host=FakeHost(),
    )

    assert plugin.after_seconds == 30 and plugin.cache_ttl_seconds == 600
    assert plugin.delay == 30, "min(30, 480)"
    assert (plugin.min_messages, plugin.min_since_recap) == (5, 1)

    for _ in range(4):
        plugin.turn_ended(True)
    assert plugin.due() is False, "the table asked for five messages"
    plugin.turn_ended(True)
    assert plugin.due() is True
    plugin._cancel()


def test_a_setting_that_could_never_be_meant_is_refused_when_the_plugin_activates(tmp_path):
    with pytest.raises(ValueError, match=r"\[plugins\.recap\] after_seconds must be at least 0"):
        build(tmp_path, {"after_seconds": -1})


def test_the_plugin_also_activates_without_a_screen(tmp_path):
    """Every process loads every plugin; one that only draws into a terminal must leave the others alone."""
    config = ZettCodeConfig(workspace=tmp_path, models=(ModelConfig(model="m", token="t"),))
    from zettcode.engine.plugins.context import PluginContext

    plugin = RecapPlugin()
    plugin.activate(PluginContext(config, {}))

    assert plugin._link is None
