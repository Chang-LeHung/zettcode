"""What a workspace has spent, read back from the conversations the store wrote."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from zett_agent.messages import AssistantMessage, UserMessage
from zett_agent.model import ModelUsage

from zettcode.app.agent.storage import SessionStore
from zettcode.app.agent.storage.ledger import UNKNOWN_MODEL, LedgerReader, Tally, parse_time

WORK = "work"


def spent(input_tokens: int, output_tokens: int, cache: int = 0, reasoning: int = 0) -> ModelUsage:
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache,
        cache_write_tokens=0,
        reasoning_tokens=reasoning,
    )


async def answer(store: SessionStore, session: str, request: str, model: str, usage: ModelUsage, **options) -> str:
    """Append one question and the reply to it, as a turn does."""
    await store.append(session, request, UserMessage(content="question"), **options)
    return await store.append(session, request, AssistantMessage(content="answer", model=model), usage=usage, **options)


def reader(tmp_path: Path) -> LedgerReader:
    return LedgerReader(tmp_path, tmp_path / WORK)


def test_a_workspace_that_never_had_a_session_has_an_empty_ledger_and_nothing_is_created(tmp_path: Path):
    ledger = reader(tmp_path).read()

    assert ledger.empty
    assert ledger.sessions == [] and ledger.models == {} and ledger.days == {}
    assert list(tmp_path.iterdir()) == [], "looking must not make the folder"


async def test_tokens_add_up_by_model_by_session_and_by_day(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "big", spent(1000, 100, cache=600, reasoning=40))
    await answer(store, "a", "r2", "small", spent(300, 30))
    await answer(store, "b", "r3", "big", spent(500, 50, cache=100))

    ledger = reader(tmp_path).read()

    assert ledger.total == Tally(
        requests=3, input_tokens=1800, output_tokens=180, cache_read_tokens=700, reasoning_tokens=40
    )
    assert ledger.models["big"] == Tally(
        requests=2, input_tokens=1500, output_tokens=150, cache_read_tokens=700, reasoning_tokens=40
    )
    assert ledger.models["small"].total == 330
    assert {row.session_id: row.tally.total for row in ledger.sessions} == {"a": 1430, "b": 550}
    (today,) = ledger.days
    assert today == datetime.now().astimezone().date()
    assert ledger.days[today].total == ledger.total.total, "the three ways of adding up agree"
    assert ledger.total.cache_share == 700 / 1800


async def test_a_reply_that_names_no_model_is_filed_as_unknown(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "", spent(10, 1))

    assert list(reader(tmp_path).read().models) == [UNKNOWN_MODEL]


async def test_a_fork_is_charged_only_for_what_it_spent_after_the_fork(tmp_path: Path):
    """``/fork`` copies the replies with their usage; adding both would charge the same answer twice."""
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(1000, 100))
    await answer(store, "a", "r2", "m", spent(2000, 200))
    forked = store.fork("a")
    await answer(store, forked, "r3", "m", spent(50, 5))

    ledger = reader(tmp_path).read()
    by_session = {row.session_id: row.tally.total for row in ledger.sessions}

    assert by_session == {"a": 3300, forked: 55}
    assert ledger.total.total == 3355
    assert ledger.total.requests == 3
    assert ledger.models["m"].total == 3355


async def test_a_subagents_session_is_not_counted(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(100, 10))
    await answer(store, "sub", "r2", "m", spent(9000, 900), parent_session_id="a", agent_name="coding")

    ledger = reader(tmp_path).read()

    assert [row.session_id for row in ledger.sessions] == ["a"]
    assert ledger.total.total == 110


async def test_sessions_are_listed_newest_first_with_their_title(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(1, 1))
    await answer(store, "b", "r2", "m", spent(1, 1))
    await store.set_title("a", "First thing")

    rows = reader(tmp_path).read().sessions

    assert [row.session_id for row in rows] == ["b", "a"]
    assert [row.title for row in rows] == [None, "First thing"]
    assert rows[0].models == ("m",)


async def test_a_second_read_only_reads_the_files_that_changed(tmp_path: Path, monkeypatch):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(100, 10))
    await answer(store, "b", "r2", "m", spent(200, 20))
    ledgers = reader(tmp_path)
    ledgers.read()

    opened: list[str] = []
    real = Path.open

    def watching(self, *args, **kwargs):
        if self.name == "data.jsonl":
            opened.append(self.parent.name)
        return real(self, *args, **kwargs)

    await answer(store, "b", "r3", "m", spent(1, 1))
    monkeypatch.setattr(Path, "open", watching)
    ledger = ledgers.read()

    assert opened == ["b"], "only the session that changed is read again"
    assert ledger.total.total == 110 + 220 + 2


async def test_a_deleted_session_leaves_the_ledger(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(100, 10))
    await answer(store, "b", "r2", "m", spent(200, 20))
    ledgers = reader(tmp_path)
    assert ledgers.read().total.total == 330

    (store.session_path("b")).unlink()

    assert ledgers.read().total.total == 110


async def test_damaged_lines_and_bad_counters_are_skipped_not_fatal(tmp_path: Path):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(100, 10))
    path = store.session_path("a")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            '{"kind": "message", "usage": {"input_tokens": "lots", "output_tokens": -5}, "created_at": "nope"}\n'
        )
        handle.write('{"kind": "message", "usage": {"input_tokens": 7\n')  # torn
        handle.write('not json at all, but it mentions "usage": {\n')

    assert reader(tmp_path).read().total.total == 110


def test_stored_times_are_read_with_or_without_the_zone_suffix():
    assert parse_time("2026-10-16T01:39:14.637213Z") == parse_time("2026-10-16T01:39:14.637213+00:00")
    assert parse_time("2026-10-16T01:39:14").tzinfo is not None
    assert parse_time("yesterday") is None and parse_time(None) is None


# -- the index kept on disk ---------------------------------------------------
INDEX = "usage.json"


def index_of(tmp_path: Path) -> Path:
    return reader(tmp_path).index_path


def counting_scans(monkeypatch) -> list[int]:
    """Record how many lines each parse of a conversation looked at."""
    from zettcode.app.agent.storage import ledger as module

    looked: list[int] = []
    real = module._row_of

    def counting(line):
        looked.append(len(line))
        return real(line)

    monkeypatch.setattr(module, "_row_of", counting)
    return looked


async def two_sessions(tmp_path: Path) -> SessionStore:
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(100, 10, cache=40))
    await answer(store, "b", "r2", "n", spent(200, 20))
    return store


async def test_the_index_is_written_beside_the_sessions_and_gives_the_same_answer(tmp_path: Path):
    await two_sessions(tmp_path)

    with_index = reader(tmp_path).read()
    without = LedgerReader(tmp_path, tmp_path / WORK, index=False).read()

    assert index_of(tmp_path).parent == SessionStore(tmp_path, tmp_path / WORK).workspace_dir
    assert index_of(tmp_path).is_file()
    assert with_index.total == without.total and with_index.models == without.models and with_index.days == without.days
    assert [row.tally for row in with_index.sessions] == [row.tally for row in without.sessions]
    assert not any(index_of(tmp_path).parent.glob("*.tmp")), "no temporary file is left behind"


async def test_an_index_that_is_off_writes_nothing(tmp_path: Path):
    await two_sessions(tmp_path)

    LedgerReader(tmp_path, tmp_path / WORK, index=False).read()

    assert not index_of(tmp_path).exists()


async def test_a_new_process_reads_no_conversation_when_none_has_changed(tmp_path: Path, monkeypatch):
    await two_sessions(tmp_path)
    first = reader(tmp_path).read()
    opened: list[str] = []
    real = Path.open

    def watching(self, *args, **kwargs):
        if self.name == "data.jsonl":
            opened.append(self.parent.name)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", watching)
    second = reader(tmp_path).read()  # a fresh reader: what a program that has just started has

    assert opened == []
    assert second.total == first.total and second.models == first.models


async def test_a_conversation_that_grew_is_read_from_where_it_stopped(tmp_path: Path, monkeypatch):
    store = await two_sessions(tmp_path)
    reader(tmp_path).read()
    await answer(store, "b", "r3", "n", spent(7, 3))  # one question and one reply: two new lines
    looked = counting_scans(monkeypatch)

    ledger = reader(tmp_path).read()

    assert len(looked) == 2, "only the two lines written since, not the whole conversation"
    assert ledger.total.total == 110 + 220 + 10
    assert {row.session_id: row.tally.requests for row in ledger.sessions} == {"a": 1, "b": 2}


async def test_a_line_still_being_written_is_left_until_it_has_its_newline(tmp_path: Path):
    store = await two_sessions(tmp_path)
    path = store.session_path("a")
    complete = [line for line in path.read_text(encoding="utf-8").splitlines() if '"usage": {' in line][-1]
    reader(tmp_path).read()
    ledgers = reader(tmp_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(complete.replace('"r1"', '"r9"'))  # no newline yet
    assert ledgers.read().total.requests == 2

    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n")

    assert ledgers.read().total.requests == 3
    assert reader(tmp_path).read().total.requests == 3


async def test_a_file_replaced_under_the_same_name_is_read_afresh(tmp_path: Path):
    store = await two_sessions(tmp_path)
    reader(tmp_path).read()
    other = SessionStore(tmp_path, tmp_path / "elsewhere")
    await answer(other, "x", "q1", "other", spent(5000, 500))
    await answer(other, "x", "q2", "other", spent(5000, 500))
    replacement = other.session_path("x").read_bytes()
    store.session_path("a").write_bytes(replacement)

    ledger = reader(tmp_path).read()

    assert {row.session_id: row.tally.total for row in ledger.sessions} == {"a": 11000, "b": 220}
    assert set(ledger.models) == {"other", "n"}


async def test_an_edit_in_the_part_already_read_is_noticed(tmp_path: Path):
    store = await two_sessions(tmp_path)
    reader(tmp_path).read()
    path = store.session_path("a")
    text = path.read_text(encoding="utf-8")
    # The edit sits in the last bytes read, which the index fingerprints, and the file is no longer.
    path.write_text(text.replace('"input_tokens": 100', '"input_tokens": 999') + "\n", encoding="utf-8")

    assert reader(tmp_path).read().models["m"].input_tokens == 999


@pytest.mark.parametrize(
    "damage",
    [
        "not json",
        "[]",
        '{"version": 99, "sessions": {}}',
        '{"version": 1, "sessions": []}',
        '{"version": 1, "sessions": {"a": {"size": "big"}}}',
        '{"version": 1, "sessions": {"a": {"size": 1, "mtime_ns": 1, "offset": 1, "head": 1, "tail": 1, '
        '"started": null, "counted": true, "rows": [["r", "t", 1, "m", 1, 1, 1]]}}}',
        '{"version": 1, "sessions": {"a": {"size": true, "mtime_ns": 1, "offset": 1, "head": 1, "tail": 1, '
        '"started": null, "counted": true, "rows": []}}}',
    ],
)
async def test_an_index_that_cannot_be_trusted_is_ignored_and_rewritten(tmp_path: Path, damage: str):
    await two_sessions(tmp_path)
    expected = LedgerReader(tmp_path, tmp_path / WORK, index=False).read().total
    index_of(tmp_path).write_text(damage, encoding="utf-8")

    assert reader(tmp_path).read().total == expected
    assert reader(tmp_path).read().total == expected, "and the one it wrote in its place is good"


async def test_a_store_whose_index_cannot_be_written_still_answers(tmp_path: Path):
    await two_sessions(tmp_path)
    index_of(tmp_path).mkdir()  # a directory where the file would go: reading and replacing both fail

    ledger = reader(tmp_path).read()

    assert ledger.total.total == 330
    assert not any(index_of(tmp_path).parent.glob("*.tmp"))


async def test_nothing_is_rewritten_when_nothing_changed(tmp_path: Path):
    await two_sessions(tmp_path)
    reader(tmp_path).read()
    stamp = index_of(tmp_path).stat().st_mtime_ns

    reader(tmp_path).read()
    ledgers = reader(tmp_path)
    ledgers.read()
    ledgers.read()

    assert index_of(tmp_path).stat().st_mtime_ns == stamp


async def test_a_deleted_session_leaves_the_index_too(tmp_path: Path):
    store = await two_sessions(tmp_path)
    reader(tmp_path).read()
    store.session_path("b").unlink()

    reader(tmp_path).read()

    assert list(json.loads(index_of(tmp_path).read_text(encoding="utf-8"))["sessions"]) == ["a"]


async def test_a_subagents_conversation_is_never_read_again_as_it_grows(tmp_path: Path, monkeypatch):
    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(100, 10))
    await answer(store, "sub", "r2", "m", spent(9000, 900), parent_session_id="a", agent_name="coding")
    reader(tmp_path).read()
    await answer(store, "sub", "r3", "m", spent(9000, 900), parent_session_id="a", agent_name="coding")
    looked = counting_scans(monkeypatch)

    ledger = reader(tmp_path).read()

    assert looked == [] and ledger.total.total == 110


@pytest.mark.skipif(sys.platform == "win32", reason="the time zone is set through the C library's tzset")
async def test_the_index_keeps_the_moment_so_a_new_time_zone_moves_the_day(tmp_path: Path, monkeypatch):
    import time

    store = SessionStore(tmp_path, tmp_path / WORK)
    await answer(store, "a", "r1", "m", spent(100, 10))
    path = store.session_path("a")
    lines = path.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines):
        if '"usage": {' in line:
            record = json.loads(line)
            record["created_at"] = "2026-10-15T23:30:00.000000Z"
            lines[number] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def day_in(zone: str):
        monkeypatch.setenv("TZ", zone)
        time.tzset()
        return next(iter(reader(tmp_path).read().days))

    try:
        assert str(day_in("UTC")) == "2026-10-15"
        assert str(day_in("Asia/Tokyo")) == "2026-10-16", "09:00 the next morning in Tokyo, from the same index"
        assert str(day_in("America/Los_Angeles")) == "2026-10-15"
    finally:
        monkeypatch.undo()
        time.tzset()
