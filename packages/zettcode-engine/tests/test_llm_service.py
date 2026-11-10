"""The model service a plugin reaches without a shell."""

from __future__ import annotations

import pytest

from zettcode.config import ModelConfig
from zettcode.engine.plugins.llm import ModelAccess


def _models() -> tuple[ModelConfig, ModelConfig]:
    return (ModelConfig(model="gpt", token="t"), ModelConfig(model="claude", token="t"))


@pytest.mark.asyncio
async def test_model_access_lists_every_configured_model_and_delegates_the_question():
    models = _models()
    access = ModelAccess(models)
    asked: list[tuple[str, str, str]] = []

    async def ask(question: str, *, origin: str, cache: str, timeout: float | None) -> str:
        asked.append((question, origin, cache))
        return f"{origin}: {question}"

    access.bind(ask)

    assert access.models == models
    assert await access.ask("what changed?", origin="recap") == "recap: what changed?"
    assert asked == [("what changed?", "recap", "read")]


@pytest.mark.asyncio
async def test_model_access_says_the_conversation_is_not_ready_before_binding():
    with pytest.raises(RuntimeError, match="not ready"):
        await ModelAccess(_models()).ask("hello")


def test_model_access_takes_the_models_a_plugin_offered_too():
    access = ModelAccess(_models())
    provided = ModelConfig(model="acme-large", provider="acme")

    access.replace((*access.models, provided))

    assert access.models[-1] is provided
