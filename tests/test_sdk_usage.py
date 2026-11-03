"""The SDK's view of what was spent, what a session holds, self-compaction, and whether the models answer."""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.messages import AssistantMessage, UserMessage
from zett_agent.model import ModelUsage

from zettcode.doctor import Probe
from zettcode.engine.storage import SessionStore
from zettcode.sdk import Client, ModelCheck, SessionStatsInfo, Totals

MODEL = {"model": "example", "token": "t"}


def usage(input_tokens: int, output_tokens: int, cache: int = 0) -> ModelUsage:
    return ModelUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache,
        cache_write_tokens=0,
        reasoning_tokens=0,
    )


async def spent(store: SessionStore, session: str, request: str, model: str, tokens: ModelUsage) -> None:
    await store.append(session, request, UserMessage(content="question"))
    await store.append(session, request, AssistantMessage(content="answer", model=model), usage=tokens)


async def test_the_workspace_ledger_is_read_back_from_the_stored_conversations(tmp_path: Path):
    store = SessionStore(tmp_path / "store", tmp_path)
    await spent(store, "a", "r1", "big", usage(1000, 100, cache=600))
    await spent(store, "a", "r2", "small", usage(300, 30))
    await spent(store, "b", "r3", "big", usage(500, 50, cache=100))
    client = Client(tmp_path, models=[MODEL], store=tmp_path / "store")
    try:
        ledger = await client.usage_ledger()
    finally:
        await client.aclose()

    assert ledger.total == Totals(requests=3, input_tokens=1800, output_tokens=180, cache_read_tokens=700)
    assert ledger.total.total_tokens == 1980
    assert [session.id for session in ledger.sessions] == ["b", "a"], "most recently active first"
    assert [model.model for model in ledger.models] == ["big", "small"]
    assert ledger.models[0].tokens.requests == 2
    assert len(ledger.days) >= 1
    assert sum(day.tokens.requests for day in ledger.days) == 3


async def test_a_workspace_that_never_ran_anything_has_an_empty_ledger(tmp_path: Path):
    client = Client(tmp_path, models=[MODEL], store=tmp_path / "store")
    try:
        ledger = await client.usage_ledger()
    finally:
        await client.aclose()

    assert ledger.total == Totals() and ledger.sessions == () and ledger.days == ()


async def test_session_stats_are_the_resume_panels_columns(tmp_path: Path):
    store = SessionStore(tmp_path / "store", tmp_path)
    await spent(store, "a", "r1", "big", usage(1000, 100, cache=600))
    await spent(store, "a", "r2", "big", usage(300, 30))
    client = Client(tmp_path, models=[MODEL], store=tmp_path / "store")
    try:
        (stats,) = await client.session_stats(["a"])
        none = await client.session_stats([])
        unknown = await client.session_stats(["nope"])
    finally:
        await client.aclose()

    assert isinstance(stats, SessionStatsInfo)
    assert (stats.entries, stats.requests) == (4, 2)
    assert (stats.input_tokens, stats.output_tokens) == (1300, 130)
    assert stats.total_tokens == 1430
    assert stats.cache_share == pytest.approx(600 / 1300)
    assert none == () and unknown == ()


async def test_without_ids_the_current_session_is_the_one_read(tmp_path: Path):
    client = Client(tmp_path, models=[MODEL], store=tmp_path / "store")
    try:
        stats = await client.session_stats()
    finally:
        await client.aclose()

    assert stats == (), "a session with no stored reply has no stats yet"


async def test_self_compaction_follows_the_default_until_the_session_chooses_and_the_choice_survives(tmp_path: Path):
    client = Client(tmp_path, models=[MODEL], store=tmp_path / "store")
    try:
        assert client.self_compaction_choice is None
        default = client.self_compaction
        session = client.session.id

        assert client.use_self_compaction(True) is True
        assert client.self_compaction_choice is True and client.self_compaction is True
    finally:
        await client.aclose()

    reopened = Client(tmp_path, models=[MODEL], store=tmp_path / "store", resume=session)
    try:
        assert reopened.self_compaction_choice is True
        assert reopened.use_self_compaction(None) is default
        assert reopened.self_compaction_choice is None
    finally:
        await reopened.aclose()


async def test_checking_the_models_reports_each_one_with_what_it_said(tmp_path: Path, monkeypatch):
    from zettcode import doctor

    async def fake(models, *, timeout=doctor.TIMEOUT, ask=doctor._ask):
        assert timeout == 7
        from zettcode.config import ModelConfig

        first = ModelConfig(model="m1", token="t", display_model="First")
        second = ModelConfig(model="m2", token="t")
        return [Probe(first, True, 0.4, "ok", (5, 1)), Probe(second, False, 9.0, "401 Unauthorized")]

    monkeypatch.setattr(doctor, "diagnose", fake)
    client = Client(tmp_path, models=[MODEL], store=tmp_path / "store")
    try:
        checks = await client.check_models(timeout=7)
    finally:
        await client.aclose()

    assert checks == (
        ModelCheck("First", "m1", True, 0.4, "ok", 5, 1),
        ModelCheck("m2", "m2", False, 9.0, "401 Unauthorized", None, None),
    )
