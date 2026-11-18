"""What a plugin context accepts, and what a refusal leaves behind."""

from __future__ import annotations

from pathlib import Path

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import PluginContext
from zettcode.providers import ProvidedModel, Provider


def _context(tmp_path: Path, *models: ModelConfig) -> PluginContext:
    return PluginContext(
        ZettCodeConfig(
            workspace=tmp_path,
            store=tmp_path / "sessions",
            models=models or (ModelConfig(model="file", token="t"),),
            harness_dir=tmp_path / "harness",
        )
    )


def test_a_refused_host_leaves_no_model_name_claimed(tmp_path: Path):
    """A name that cannot be had refuses the whole host, and the names it would have used stay free."""
    context = _context(tmp_path, ModelConfig(model="file", token="t", display_model="Taken"))

    with pytest.raises(ValueError, match="already shown as 'Taken'"):
        context.register_provider(
            Provider(
                "acme",
                "Acme",
                base_url="https://a.example/v1",
                models=(ProvidedModel("a", display_model="Astra"), ProvidedModel("b", display_model="Taken")),
            )
        )

    context.register_provider(
        Provider(
            "other",
            "Other",
            base_url="https://o.example/v1",
            models=(ProvidedModel("x", display_model="Astra"),),
        )
    )

    assert [host.name for host in context.providers] == ["other"]


def test_one_host_cannot_offer_two_models_shown_by_one_name(tmp_path: Path):
    context = _context(tmp_path)

    with pytest.raises(ValueError, match="already shown as 'Same'"):
        context.register_provider(
            Provider(
                "acme",
                "Acme",
                base_url="https://a.example/v1",
                models=(ProvidedModel("a", display_model="Same"), ProvidedModel("b", display_model="Same")),
            )
        )

    # The name the refused host would have used is free, so a second host may still take it.
    context.register_provider(
        Provider(
            "other",
            "Other",
            base_url="https://o.example/v1",
            models=(ProvidedModel("x", display_model="Same"),),
        )
    )

    assert [host.name for host in context.providers] == ["other"]
