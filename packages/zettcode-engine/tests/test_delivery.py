"""The runtime's delivery: what counts as a request, and who is told when the last one ends."""

from __future__ import annotations

from pathlib import Path

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.core import ZettCodeEngine
from zettcode.engine.delivery import DELIVERY, Delivery
from zettcode.engine.extensions.compaction import OnDemandCompaction
from zettcode.engine.plugins import Plugins
from zettcode.engine.plugins.services import COMPACTION


def _state(shared: dict[str, object]) -> Plugins:
    """The plugins a runtime preview needs to finish: the delivery it is handed and a compaction policy."""
    return Plugins(services={**shared, COMPACTION: OnDemandCompaction(None)})


def _runtime(tmp_path: Path) -> ZettCodeEngine:
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="m", token="t"),),
        harness_dir=tmp_path / "harness",
    )
    return ZettCodeEngine.preview(config, lambda config, shared: _state(shared))


def test_a_request_is_counted_only_while_it_runs_and_the_last_end_frees_the_inbox(tmp_path: Path):
    runtime = _runtime(tmp_path)
    seen: list[str] = []

    assert runtime.running is False
    runtime.on_idle(lambda: seen.append("first"))  # nothing runs: told at once
    assert seen == ["first"]

    runtime.run_started()
    runtime.run_started()
    runtime.on_idle(lambda: seen.append("later"))
    assert runtime.running is True

    runtime.run_finished()
    assert seen == ["first"], "a second request is still running"
    runtime.run_finished()

    assert seen == ["first", "later"]
    assert runtime.running is False


def test_a_waiter_can_stop_waiting(tmp_path: Path):
    runtime = _runtime(tmp_path)
    runtime.run_started()
    seen: list[str] = []
    forget = runtime.on_idle(lambda: seen.append("idle"))

    forget()
    runtime.run_finished()

    assert seen == []


def test_the_runtime_provides_the_delivery_by_name(tmp_path: Path):
    runtime = _runtime(tmp_path)
    delivery = runtime.plugins.service(DELIVERY, Delivery)

    assert isinstance(delivery, Delivery)
    assert delivery.busy is False, "nothing runs before start()"
    assert delivery.steer("hello") is None, "a request that is not running takes nothing"


def test_a_callback_registered_before_the_runtime_was_bound_is_called_at_once(tmp_path: Path):
    """``preview`` makes the delivery before the runtime exists; a plugin that asks it something gets a safe answer."""
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="m", token="t"),),
        harness_dir=tmp_path / "harness",
    )
    seen: list[Delivery] = []

    def load(config, shared):
        delivery = shared[DELIVERY]
        assert isinstance(delivery, Delivery)
        seen.append(delivery)
        delivery.when_idle(lambda: None)  # nothing runs yet: called at once, not crashed
        return _state(shared)

    ZettCodeEngine.preview(config, load)

    assert len(seen) == 1
