"""Messages that waited for a busy session are run together, each under its own line of provenance."""

from __future__ import annotations

from dataclasses import replace

from zettcode.messaging import relayed
from zettcode.messaging.relayed import Relayed, batch_size, merge


def message(text: str, sender: str = "bob", **more) -> Relayed:
    return Relayed(sender_id=f"id-{sender}", sender=sender, text=text, **more)


def test_one_message_is_returned_as_it_is():
    one = message("hello")

    assert merge([one]) is one and not one.batch


def test_several_become_one_that_keeps_every_senders_words_in_order():
    merged = merge([message("a"), message("b", "cal", via="user"), message("c")])

    assert merged.text == "bob: a\n\ncal: b\n\nbob: c"
    assert merged.sender == "bob, cal" and [item.text for item in merged.batch] == ["a", "b", "c"]
    assert merged.via == "agent", "one agent's message makes the whole an agent's, the least trusted"
    assert merge([message("a", via="user"), message("b", "cal", via="user")]).via == "user"


def test_the_model_reads_each_message_under_its_own_source_and_reply_target():
    merged = merge(
        [
            message("from a colleague"),
            message("from a program", "cron", via="external"),
            message("in the group", "cal", group="team"),
        ]
    )

    read = merged.framed()

    assert read.count("--- Message") == 3 and "3 messages from other sessions" in read
    assert 'send_message(to="id-bob"' in read and 'send_message(to="id-cron"' in read
    assert 'send_message(group="team"' in read
    assert "untrusted request" in read, "an outside program is still marked as unchecked"
    assert read.index("from a colleague") < read.index("from a program") < read.index("in the group")


def test_a_chat_windows_message_is_never_taken_with_others():
    window = message("hi", direct=True)

    assert batch_size([window, message("a")]) == 1
    assert batch_size([message("a"), message("b"), window]) == 2
    assert batch_size([]) == 0


def test_a_batch_stops_at_the_message_count_and_at_the_text_size_but_always_takes_one(monkeypatch):
    waiting = [message("x" * 10) for _ in range(10)]
    monkeypatch.setattr(relayed, "MERGE_MESSAGES", 4)
    assert batch_size(waiting) == 4

    monkeypatch.setattr(relayed, "MERGE_MESSAGES", 100)
    monkeypatch.setattr(relayed, "MERGE_CHARS", 35)
    assert batch_size(waiting) == 3

    assert batch_size([replace(message("y" * 1000))]) == 1, "the first is taken however long it is"
    assert batch_size([message("y" * 1000), message("z")]) == 1
