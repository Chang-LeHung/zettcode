"""What a caller hands ``preview``, and what it may not take away from the runtime."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.core import ZettCodeEngine
from zettcode.engine.delivery import DELIVERY
from zettcode.engine.extensions.compaction import OnDemandCompaction
from zettcode.engine.plugins import Plugins
from zettcode.engine.plugins.services import COMPACTION, PERSISTENCE


def _config(tmp_path: Path) -> ZettCodeConfig:
    return ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="m", token="t"),),
        harness_dir=tmp_path / "harness",
    )


def _state(shared: Mapping[str, object]) -> Plugins:
    """The bundle a preview needs to finish: whatever it was handed, plus a compaction policy."""
    return Plugins(services={**shared, COMPACTION: OnDemandCompaction(None)})


async def test_a_caller_service_reaches_the_plugins_and_the_runtime_keeps_its_own(tmp_path):
    seen: dict[str, object] = {}

    def load(config: ZettCodeConfig, shared: Mapping[str, object]) -> Plugins:
        seen.update(shared)
        return _state(shared)

    runtime = ZettCodeEngine.preview(_config(tmp_path), load, shared={"caller-thing": 7})
    try:
        assert seen["caller-thing"] == 7
        assert seen[DELIVERY] is not None, "the runtime's own delivery is still handed over"
    finally:
        await runtime.aclose()


async def test_a_caller_may_not_replace_a_service_the_runtime_keeps_using(tmp_path):
    before = Path.cwd()
    with pytest.raises(ValueError, match="persistence"):
        ZettCodeEngine.preview(_config(tmp_path), lambda config, shared: _state(shared), shared={PERSISTENCE: object()})
    assert Path.cwd() == before, "a refused shared mapping leaves the process where it was"


async def test_create_hands_shared_to_preview(tmp_path, monkeypatch):
    seen: dict[str, object] = {}

    class Started:
        async def start(self) -> Started:
            return self

    def preview(config, load=None, *, shared=None):
        seen.update(shared or {})
        return cast("ZettCodeEngine", Started())

    monkeypatch.setattr(ZettCodeEngine, "preview", staticmethod(preview))

    await ZettCodeEngine.create(_config(tmp_path), shared={"caller-thing": 7})

    assert seen["caller-thing"] == 7
