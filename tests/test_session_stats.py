"""What the sessions panel shows for each session: how many entries it holds and what it cost, kept in ``sessions.json``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from zett_agent.messages import AssistantMessage, UserMessage
from zett_agent.model import ModelUsage

from zettcode.app.agent.storage import SessionStats, SessionStore
from zettcode.app.agent.storage import ledger as ledger_module
from zettcode.app.agent.storage.ledger import SUMMARY_FILE, LedgerReader

WORK = "work"


def spent(input_tokens: int, output_tokens: int, cache: int = 0) -> ModelUsage:
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache,
        cache_write_tokens=0,
        reasoning_tokens=0,
    )


async def answer(
    store: SessionStore, session: str, request: str, usage: ModelUsage, text: str = "answer", **kw
) -> None:
    """Append one question and the reply to it, as a turn does."""
    await store.append(session, request, UserMessage(content="question"), **kw)
    await store.append(session, request, AssistantMessage(content=text, model="m"), usage=usage, **kw)


def reader(tmp_path: Path, **options) -> LedgerReader:
    return LedgerReader(tmp_path, tmp_path / WORK, **options)


def summary_of(tmp_path: Path) -> Path:
    return reader(tmp_path).summary_path


def scans(monkeypatch) -> list[Path]:
    """Record every conversation file a read opens."""
    opened: list[Path] = []
    real = ledger_module._scan

    def counting(path, previous):
        opened.append(path)
        return real(path, previous)

    monkeypatch.setattr(ledger_module, "_scan", counting)
    return opened


async def two_sessions(tmp_path: Path) -> SessionStore:
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", spent(1000, 100, cache=600))
    await answer(store, "b", "r2", spent(200, 20))
    await store.append("b", "r3", UserMessage(content="and another"))
    return store


# -- the entries ------------------------------------------------------------------------------------


async def test_a_sessions_entries_are_its_message_records(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", spent(10, 1))
    await answer(store, "a", "r2", spent(10, 1))

    stats = reader(tmp_path).stats(["a"])["a"]

    parsed = sum(
        1
        for line in store.session_path("a").read_text(encoding="utf-8").splitlines()
        if json.loads(line)["kind"] == "message"
    )
    assert stats.entries == parsed and parsed >= 4, "counted without parsing, and the same as parsing"


async def test_text_that_looks_like_a_message_record_is_not_one(tmp_path: Path):
    """A conversation about this very format must not inflate its own count: the text inside a line is escaped."""
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", spent(10, 1), text='a record is {"kind": "message"} and {"kind":"message"}')
    before = reader(tmp_path).stats(["a"])["a"].entries

    plain = SessionStore(tmp_path, tmp_path / "other")
    await answer(plain, "a", "r1", spent(10, 1), text="a record is something")
    other = LedgerReader(tmp_path, tmp_path / "other").stats(["a"])["a"].entries

    assert before == other


async def test_entries_follow_a_conversation_as_it_grows_without_reading_it_again(tmp_path: Path, monkeypatch):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", spent(10, 1))
    first = reader(tmp_path).stats(["a"])["a"]
    await answer(store, "a", "r2", spent(10, 1))
    opened = scans(monkeypatch)

    second = reader(tmp_path).stats(["a"])["a"]

    assert second.entries == first.entries + 2 and second.requests == 2
    assert opened == [store.session_path("a")], "the grown file is read, from where it stopped"


async def test_an_index_from_before_entries_were_counted_is_read_again_for_them(tmp_path: Path):
    """An older ``usage.json`` has no ``entries``: each file it names is rescanned, and nothing else is lost."""
    await two_sessions(tmp_path)
    ledger = reader(tmp_path)
    ledger.read()
    data = json.loads(ledger.index_path.read_text(encoding="utf-8"))
    for item in data["sessions"].values():
        del item["entries"]
    ledger.index_path.write_text(json.dumps(data), encoding="utf-8")

    fresh = reader(tmp_path, index=True).read()

    assert {row.session_id: row.entries for row in fresh.sessions} == {"a": 2, "b": 3}
    assert fresh.total.total == 1320


# -- the summary file -------------------------------------------------------------------------------


async def test_the_totals_of_each_session_are_what_the_ledger_says(tmp_path: Path):
    await two_sessions(tmp_path)

    stats = reader(tmp_path).stats(["a", "b"])

    assert stats["a"] == SessionStats(
        "a", entries=2, requests=1, input_tokens=1000, output_tokens=100, cache_read_tokens=600
    )
    assert stats["a"].total == 1100 and stats["a"].cache_share == 0.6
    assert stats["b"].entries == 3 and stats["b"].cache_share == 0.0
    assert SessionStats("x").cache_share is None, "before any input there is nothing to be a share of"


async def test_the_summary_is_written_beside_the_sessions_and_is_small(tmp_path: Path):
    await two_sessions(tmp_path)
    ledger = reader(tmp_path)

    ledger.stats(["a", "b"])

    written = json.loads(summary_of(tmp_path).read_text(encoding="utf-8"))
    assert summary_of(tmp_path).name == SUMMARY_FILE == "sessions.json"
    assert summary_of(tmp_path).parent == ledger.index_path.parent
    assert written["version"] == 1 and set(written["sessions"]) == {"a", "b"}
    assert all(len(item) == 8 for item in written["sessions"].values()), "a stamp and six numbers; no reply rows"
    assert summary_of(tmp_path).stat().st_size < ledger.index_path.stat().st_size


async def test_an_unchanged_workspace_is_answered_without_opening_a_conversation_or_the_index(
    tmp_path: Path, monkeypatch
):
    await two_sessions(tmp_path)
    expected = reader(tmp_path).stats(["a", "b"])
    opened = scans(monkeypatch)

    def refuse(self):
        raise AssertionError("the index was read")

    monkeypatch.setattr(LedgerReader, "_load_index", refuse)
    monkeypatch.setattr(LedgerReader, "read", refuse)

    assert reader(tmp_path).stats(["a", "b"]) == expected
    assert opened == []


async def test_a_session_that_changed_is_read_again_and_the_summary_follows(tmp_path: Path, monkeypatch):
    store = await two_sessions(tmp_path)
    reader(tmp_path).stats(["a", "b"])
    await answer(store, "a", "r9", spent(50, 5))
    opened = scans(monkeypatch)

    stats = reader(tmp_path).stats(["a", "b"])

    assert stats["a"].requests == 2 and stats["a"].input_tokens == 1050
    assert opened == [store.session_path("a")], "only the one that changed"
    assert reader(tmp_path).stats(["a", "b"]) == stats, "and the next ask is answered from the summary again"
    assert json.loads(summary_of(tmp_path).read_text(encoding="utf-8"))["sessions"]["a"][3] == 2


async def test_a_session_the_summary_does_not_know_is_read_in(tmp_path: Path):
    store = await two_sessions(tmp_path)
    reader(tmp_path).stats(["a", "b"])
    await answer(store, "c", "r5", spent(7, 1))

    assert reader(tmp_path).stats(["a", "b", "c"])["c"].input_tokens == 7


async def test_a_session_that_went_away_makes_the_rest_be_worked_out_again(tmp_path: Path):
    """A fork shows only what it spent after the fork; if the session that held the copied replies is deleted, the
    fork is the first to hold them, and its summary is no longer right."""
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "origin", "r1", spent(1000, 100))
    store.fork("origin")
    forked = next(sid for sid in store.session_ids() if sid != "origin")
    before = reader(tmp_path).stats(["origin", forked])
    assert before[forked].requests == 0, "the copy is charged to the session that held it first"

    import shutil

    shutil.rmtree(store.session_dir("origin"))
    after = reader(tmp_path).stats([forked])

    assert after[forked].requests == 1 and after[forked].input_tokens == 1000


async def test_a_subagents_session_has_no_totals(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", spent(100, 10))
    await answer(store, "sub", "r2", spent(9000, 900), parent_session_id="a", agent_name="coding")

    stats = reader(tmp_path).stats(["a", "sub"])

    assert set(stats) == {"a"}


async def test_nothing_is_asked_of_a_workspace_that_has_no_sessions(tmp_path: Path):
    assert reader(tmp_path).stats(["a"]) == {}
    assert list(tmp_path.iterdir()) == [], "and looking made no folder"


@pytest.mark.parametrize("bad", ["../escape", "a/b", "", ".."])
async def test_an_id_that_could_leave_the_store_is_not_looked_up(tmp_path: Path, bad: str):
    await two_sessions(tmp_path)

    assert reader(tmp_path).stats([bad]) == {}


@pytest.mark.parametrize(
    "damage",
    [
        "not json",
        "[]",
        '{"version": 99, "sessions": {}}',
        '{"version": 1, "sessions": []}',
        '{"version": 1, "sessions": {"a": [1, 2, 3]}}',
        '{"version": 1, "sessions": {"a": ["x", 1, 1, 1, 1, 1, 1, 1]}}',
        '{"version": 1, "sessions": {"a": [-1, 1, 1, 1, 1, 1, 1, 1]}}',
        '{"version": 1, "sessions": {"a": [true, 1, 1, 1, 1, 1, 1, 1]}}',
    ],
)
async def test_a_summary_that_cannot_be_trusted_is_ignored_and_rewritten(tmp_path: Path, damage: str):
    await two_sessions(tmp_path)
    expected = reader(tmp_path).stats(["a", "b"])
    summary_of(tmp_path).write_text(damage, encoding="utf-8")

    assert reader(tmp_path).stats(["a", "b"]) == expected
    assert json.loads(summary_of(tmp_path).read_text(encoding="utf-8"))["sessions"].keys() == {"a", "b"}


async def test_a_store_whose_summary_cannot_be_written_still_answers(tmp_path: Path):
    await two_sessions(tmp_path)
    summary_of(tmp_path).mkdir()  # a directory where the file would go: reading and replacing both fail

    stats = reader(tmp_path).stats(["a", "b"])

    assert stats["a"].input_tokens == 1000
    assert not any(summary_of(tmp_path).parent.glob("*.tmp"))


async def test_a_reader_with_the_index_off_keeps_no_summary(tmp_path: Path):
    await two_sessions(tmp_path)

    stats = reader(tmp_path, index=False).stats(["a"])

    assert stats["a"].requests == 1 and not summary_of(tmp_path).exists()


async def test_the_stamp_is_the_one_taken_before_reading_so_a_file_that_grew_is_not_mistaken_for_current(
    tmp_path: Path, monkeypatch
):
    store = await two_sessions(tmp_path)
    real = ledger_module._scan
    grown = []

    def growing(path, previous):
        found = real(path, previous)
        if not grown:  # the file grows after the read looked at it, before the summary is written
            grown.append(path)
            asyncio_free_append(store, path)
        return found

    def asyncio_free_append(store: SessionStore, path: Path) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(path.read_text(encoding="utf-8").splitlines()[-1] + "\n")

    monkeypatch.setattr(ledger_module, "_scan", growing)
    reader(tmp_path).stats(["a", "b"])
    monkeypatch.setattr(ledger_module, "_scan", real)
    opened = scans(monkeypatch)

    reader(tmp_path).stats(["a", "b"])

    assert grown and grown[0] in opened, "the summary did not claim to describe the larger file"


# -- through the store ------------------------------------------------------------------------------


async def test_the_store_answers_for_the_sessions_it_lists(tmp_path: Path):
    store = await two_sessions(tmp_path)
    listed = await store.list_sessions()

    stats = await store.session_stats([row.session_id for row in listed])

    assert {sid: row.input_tokens for sid, row in stats.items()} == {"a": 1000, "b": 200}
    assert summary_of(tmp_path).is_file()
