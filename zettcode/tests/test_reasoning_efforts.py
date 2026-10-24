"""Which reasoning levels a model takes, and what happens to a level it does not.

Not every endpoint takes every level the framework knows. A model entry may list the ones it does
(``reasoning_efforts``); the others are never sent. A level the *reader* types is refused with the list, so
nothing changes unannounced; a level that is only *inherited* — the one in force when the model changes, a
subagent profile's default — is moved to the nearest one the model takes.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from zett_agent.model import ReasoningEffort

from zettcode.app.agent.agent import ZettCodeAgent
from zettcode.config import ModelConfig, ZettCodeConfig, load_config
from zettcode.engine.core import ZettCodeEngine

OFF, MINIMAL, LOW, MEDIUM, HIGH, XHIGH, MAX, ULTRA = tuple(ReasoningEffort)


def _model(*levels: ReasoningEffort, name: str = "m") -> ModelConfig:
    return ModelConfig(model=name, token="t", reasoning_efforts=tuple(levels))


# -- the model entry ---------------------------------------------------------------------------------------


def test_a_model_that_lists_nothing_takes_every_level():
    assert _model().efforts == tuple(ReasoningEffort)


def test_the_levels_are_kept_cheapest_first_and_once_each():
    assert _model(HIGH, LOW, HIGH).efforts == (LOW, HIGH)


@pytest.mark.parametrize(
    ("taken", "asked", "sent"),
    [
        ((LOW, HIGH), HIGH, HIGH),
        ((LOW, HIGH), ULTRA, HIGH),
        ((LOW, HIGH), OFF, LOW),
        # Halfway between two: the cheaper one, which is the one an endpoint is known to serve.
        ((LOW, HIGH), MEDIUM, LOW),
        ((MEDIUM,), ULTRA, MEDIUM),
        ((), ULTRA, ULTRA),
    ],
)
def test_a_level_the_model_does_not_take_is_moved_to_the_nearest_one_it_does(taken, asked, sent):
    assert _model(*taken).accepted_effort(asked) == sent


def test_every_level_maps_to_one_the_model_takes():
    taken = _model(LOW, XHIGH)
    assert {taken.accepted_effort(level) for level in ReasoningEffort} <= set(taken.efforts)


# -- the config file ---------------------------------------------------------------------------------------


def _load(tmp_path: Path, extra: str) -> ZettCodeConfig:
    path = tmp_path / "config.toml"
    path.write_text(f'[[models]]\nmodel = "m"\ntoken = "t"\n{extra}\n', encoding="utf-8")
    return load_config(tmp_path, path=path)


def test_the_file_lists_the_levels_a_model_takes(tmp_path: Path):
    config = _load(tmp_path, 'reasoning_efforts = ["High", "low", "high"]')

    assert config.models[0].reasoning_efforts == (LOW, HIGH)


def test_a_model_without_the_key_takes_everything(tmp_path: Path):
    assert _load(tmp_path, "").models[0].reasoning_efforts == ()


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ('["extreme"]', "extreme"),
        ("[]", "at least one"),
        ('"high"', "array"),
        ("[1]", "array"),
    ],
)
def test_a_bad_list_is_refused_and_names_the_entry(tmp_path: Path, value, message):
    with pytest.raises(ValueError, match=message) as error:
        _load(tmp_path, f"reasoning_efforts = {value}")

    assert "models[1]" in str(error.value)


# -- the running session -----------------------------------------------------------------------------------


def _agent(tmp_path: Path, monkeypatch, *models: ModelConfig, effort: ReasoningEffort = MEDIUM) -> ZettCodeAgent:
    monkeypatch.setattr("zettcode.engine.core.os.chdir", lambda path: None)
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=models,
        reasoning_effort=effort,
        mcp_config=tmp_path / "absent-mcp.json",
    )
    return ZettCodeAgent(ZettCodeEngine.preview(config))


async def test_a_session_starts_on_a_level_its_model_takes(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch, _model(HIGH, MAX), effort=LOW)
    try:
        assert agent.effort == "high"
    finally:
        await agent.runtime.aclose()


async def test_the_picker_lists_only_what_the_active_model_takes(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch, _model(LOW, HIGH, name="a"), _model(name="b"))
    try:
        assert agent.efforts == ("low", "high")
        agent.use_model("b")
        assert agent.efforts == tuple(level.value for level in ReasoningEffort)
    finally:
        await agent.runtime.aclose()


async def test_typing_a_level_the_model_does_not_take_is_refused_with_the_ones_it_does(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch, _model(LOW, HIGH), effort=LOW)
    try:
        with pytest.raises(ValueError, match=r"does not take ultra.*low, high"):
            agent.use_effort("ultra")
        assert agent.effort == "low", "and nothing changed"
        assert agent.use_effort("high") == "high"
    finally:
        await agent.runtime.aclose()


async def test_an_unknown_word_is_still_reported_as_unknown(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path, monkeypatch, _model())
    try:
        with pytest.raises(ValueError, match="Unknown reasoning effort"):
            agent.use_effort("loud")
    finally:
        await agent.runtime.aclose()


async def test_switching_to_a_model_that_lacks_the_level_in_force_moves_it_and_back_does_not_restore_it(
    tmp_path: Path, monkeypatch
):
    agent = _agent(tmp_path, monkeypatch, _model(name="wide"), _model(OFF, LOW, name="narrow"), effort=HIGH)
    try:
        assert agent.effort == "high"

        agent.use_model("narrow")

        assert agent.effort == "low", "never sent a level the endpoint would reject"
        agent.use_model("wide")
        assert agent.effort == "low", "the level in force is what it is; the reader raises it again if they want"
    finally:
        await agent.runtime.aclose()
