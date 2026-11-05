"""The runtime starts the plugins' triggers with itself and stops them when it closes."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path

from sdk_helpers import config_for
from zettcode.engine.core import ZettCodeEngine
from zettcode.engine.plugins import Trigger, TriggerScope, TriggerState
from zettcode.engine.plugins.triggers import TriggerRegistration
from zettcode.sdk.builtins import load_agent_plugins


class Watcher(Trigger):
    name = "watcher"
    scope = TriggerScope.MACHINE

    def __init__(self) -> None:
        self.cleaned = False

    async def run(self, fire) -> None:
        try:
            await fire({"hello": "world"})
            await asyncio.Event().wait()
        finally:
            self.cleaned = True


async def test_the_runtime_runs_the_triggers_from_start_and_stops_them_on_close(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    watcher = Watcher()
    events: list[object] = []
    registration = TriggerRegistration(watcher, events.append)
    config = config_for(tmp_path)

    def load(config, shared):
        return dataclasses.replace(load_agent_plugins(config, shared), triggers=(registration,))

    runtime = ZettCodeEngine.preview(config, load)
    assert runtime.trigger_statuses() == (), "nothing watches before the runtime starts"
    await runtime.start()
    try:
        for _ in range(200):
            if events:
                break
            await asyncio.sleep(0.01)
        assert [event.payload for event in events] == [{"hello": "world"}]  # type: ignore[attr-defined]
        (status,) = runtime.trigger_statuses()
        assert status.state is TriggerState.RUNNING and status.scope is TriggerScope.MACHINE
        assert (config.store.parent / "triggers" / "watcher.lock").exists(), "the machine lock lives beside the store"
    finally:
        await runtime.aclose()

    assert watcher.cleaned, "closing the runtime stops its triggers"
    assert runtime.trigger_statuses() == ()
