"""What a plugin holds beyond a turn is released when the plugins are closed."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.core import ZettCodeEngine
from zettcode.engine.extensions.compaction import OnDemandCompaction
from zettcode.engine.plugins import Plugin, PluginExtension, Plugins, load_plugins
from zettcode.engine.plugins.services import COMPACTION


def _config(tmp_path: Path) -> ZettCodeConfig:
    return ZettCodeConfig(workspace=tmp_path, store=tmp_path / "sessions", models=(ModelConfig(model="m", token="t"),))


async def test_plugins_close_newest_activated_first_not_in_hook_order(tmp_path):
    closed: list[str] = []

    class Closing(Plugin):
        fails = False

        async def aclose(self) -> None:
            closed.append(self.name)
            if self.fails:
                raise RuntimeError("boom")

    # Hook order is by priority (`second` first); closing is by activation order, newest first. The two differ here,
    # which is what tells the two orders apart.
    first = type("First", (Closing,), {"name": "first", "priority": 0})()
    second = type("Second", (Closing,), {"name": "second", "priority": -10, "fails": True})()
    third = type("Third", (Closing,), {"name": "third", "priority": 0})()

    plugins = load_plugins(_config(tmp_path), builtins=[first, second, third], entry_points=())

    await plugins.aclose()

    assert closed == ["third", "second", "first"]


async def test_the_runtime_closes_its_plugins_before_it_closes_the_store(tmp_path):
    closed: list[str] = []

    class Closing(Plugin):
        name = "closing"

        async def aclose(self) -> None:
            closed.append("plugin")

    def load(config: ZettCodeConfig, shared: Mapping[str, object]) -> Plugins:
        bundle = Plugins(
            host=PluginExtension([Closing()]),
            services={COMPACTION: OnDemandCompaction(None)},
        )
        return bundle

    runtime = ZettCodeEngine.preview(_config(tmp_path), load)
    store = runtime.persistence
    original = store.close

    async def close() -> None:
        closed.append("store")
        await original()

    store.close = close  # type: ignore[method-assign]

    await runtime.aclose()

    assert closed == ["plugin", "store"]
