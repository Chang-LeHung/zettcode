"""Triggers: a plugin's watcher, one instance per process or one per machine."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.engine.plugins import (
    Plugin,
    PluginContext,
    Trigger,
    TriggerEvent,
    TriggerHost,
    TriggerScope,
    TriggerState,
    load_plugins,
)
from zettcode.engine.plugins.triggers import TriggerRegistration
from zettcode.filelock import SingletonLock


class Ticker(Trigger):
    """Fires ``count`` events, then idles until it is stopped."""

    name = "ticker"

    def __init__(self, count: int = 2, *, scope: TriggerScope = TriggerScope.PROCESS, name: str | None = None) -> None:
        self.count = count
        self.scope = scope
        if name is not None:
            self.name = name
        self.stopped = False

    async def run(self, fire) -> None:
        try:
            for index in range(self.count):
                await fire({"n": index})
            await asyncio.Event().wait()
        finally:
            self.stopped = True


class Exploding(Trigger):
    name = "exploding"

    async def run(self, fire) -> None:
        raise RuntimeError("boom")


def _config(tmp_path: Path) -> ZettCodeConfig:
    return ZettCodeConfig(workspace=tmp_path, store=tmp_path / "sessions", models=(ModelConfig(model="m", token="t"),))


async def _until(predicate, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "the condition never became true"
        await asyncio.sleep(0.01)


def _host(tmp_path: Path, *triggers: tuple[Trigger, object], retry: float = 0.02) -> TriggerHost:
    return TriggerHost([TriggerRegistration(t, h) for t, h in triggers], tmp_path / "locks", retry=retry)  # type: ignore[arg-type]


def _state(host: TriggerHost, name: str) -> TriggerState:
    return next(status.state for status in host.statuses if status.name == name)


# -- registering -------------------------------------------------------------------------------------------------


def test_a_plugin_registers_a_trigger_with_a_handler_and_the_bundle_carries_it(tmp_path: Path):
    seen: list[TriggerEvent] = []

    class Watching(Plugin):
        name = "watching"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_trigger(Ticker(), seen.append)

    plugins = load_plugins(_config(tmp_path), builtins=[Watching()], entry_points=())

    assert [reg.name for reg in plugins.triggers] == ["ticker"]
    assert plugins.failed == ()


@pytest.mark.parametrize("name", ["", "Has Space", "UPPER", "../escape", "a/b"])
def test_a_trigger_name_that_cannot_be_a_lock_file_is_refused(tmp_path: Path, name: str):
    context = PluginContext(_config(tmp_path))

    with pytest.raises(ValueError, match="needs a name"):
        context.register_trigger(Ticker(name=name), lambda event: None)


def test_one_plugin_cannot_register_a_name_twice_and_two_plugins_cannot_share_one(tmp_path: Path):
    context = PluginContext(_config(tmp_path))
    context.register_trigger(Ticker(), lambda event: None)
    with pytest.raises(ValueError, match="already registered"):
        context.register_trigger(Ticker(), lambda event: None)

    class First(Plugin):
        name = "first"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_trigger(Ticker(), lambda event: None)

    class Second(Plugin):
        name = "second"

        def activate(self, ctx: PluginContext) -> None:
            ctx.agent.register_trigger(Ticker(), lambda event: None)

    plugins = load_plugins(_config(tmp_path), builtins=[First(), Second()], entry_points=())

    assert [reg.name for reg in plugins.triggers] == ["ticker"]
    assert any("trigger ticker is already registered" in why for _, why in plugins.failed)


# -- running ---------------------------------------------------------------------------------------------------


async def test_events_reach_the_handler_plain_or_async_and_a_bad_handler_costs_only_its_event(tmp_path: Path):
    got: list[object] = []

    async def handler(event: TriggerEvent) -> None:
        got.append(event.payload["n"])
        if event.payload["n"] == 0:
            raise RuntimeError("this event only")

    host = _host(tmp_path, (Ticker(3), handler))
    host.start()
    try:
        await _until(lambda: got == [0, 1, 2])
        assert _state(host, "ticker") is TriggerState.RUNNING
    finally:
        await host.stop()


async def test_stopping_cancels_the_trigger_and_it_cleans_up(tmp_path: Path):
    ticker = Ticker(0)
    host = _host(tmp_path, (ticker, lambda event: None))
    host.start()
    await _until(lambda: _state(host, "ticker") is TriggerState.RUNNING)

    await host.stop()

    assert ticker.stopped and _state(host, "ticker") is TriggerState.STOPPED


async def test_a_trigger_that_raises_is_failed_and_not_restarted(tmp_path: Path):
    host = _host(tmp_path, (Exploding(), lambda event: None))
    host.start()
    try:
        await _until(lambda: _state(host, "exploding") is TriggerState.FAILED)
        assert "boom" in host.statuses[0].detail
        await asyncio.sleep(0.1)
        assert _state(host, "exploding") is TriggerState.FAILED
    finally:
        await host.stop()


# -- one per process -------------------------------------------------------------------------------------------


async def test_a_process_runs_a_trigger_once_even_with_two_runtimes(tmp_path: Path):
    first = _host(tmp_path, (Ticker(0), lambda event: None))
    second = _host(tmp_path, (Ticker(0), lambda event: None))
    first.start()
    await _until(lambda: _state(first, "ticker") is TriggerState.RUNNING)
    second.start()
    try:
        await _until(lambda: _state(second, "ticker") is TriggerState.SKIPPED)
    finally:
        await second.stop()
        await first.stop()

    third = _host(tmp_path, (Ticker(0), lambda event: None))
    third.start()
    try:
        await _until(lambda: _state(third, "ticker") is TriggerState.RUNNING)
    finally:
        await third.stop()


# -- one per machine -------------------------------------------------------------------------------------------


async def test_a_machine_trigger_runs_where_the_lock_is_held_and_waits_where_it_is_not(tmp_path: Path):
    lock = SingletonLock(tmp_path / "locks" / "ticker.lock")
    assert lock.acquire()  # another holder, as another process would be
    host = _host(tmp_path, (Ticker(0, scope=TriggerScope.MACHINE), lambda event: None))
    host.start()
    try:
        await _until(lambda: _state(host, "ticker") is TriggerState.STANDBY)

        lock.release()  # the holder went away

        await _until(lambda: _state(host, "ticker") is TriggerState.RUNNING)
    finally:
        await host.stop()
    assert SingletonLock(tmp_path / "locks" / "ticker.lock").acquire(), "stopping let the machine's lock go"


async def test_a_trigger_that_a_killed_process_held_is_taken_over(tmp_path: Path):
    """The lock is the operating system's, so a process that dies without cleaning up leaves nothing stale."""
    lock_file = tmp_path / "locks" / "ticker.lock"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                import sys, time
                from pathlib import Path
                from zettcode.filelock import SingletonLock
                lock = SingletonLock(Path({str(lock_file)!r}))
                assert lock.acquire()
                print("held", flush=True)
                time.sleep(60)
                """
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        host = _host(tmp_path, (Ticker(0, scope=TriggerScope.MACHINE), lambda event: None))
        host.start()
        try:
            await _until(lambda: _state(host, "ticker") is TriggerState.STANDBY)

            holder.kill()
            holder.wait()

            await _until(lambda: _state(host, "ticker") is TriggerState.RUNNING)
        finally:
            await host.stop()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()


async def test_two_machine_triggers_with_different_names_do_not_wait_for_each_other(tmp_path: Path):
    host = _host(
        tmp_path,
        (Ticker(0, scope=TriggerScope.MACHINE, name="one"), lambda event: None),
        (Ticker(0, scope=TriggerScope.MACHINE, name="two"), lambda event: None),
    )
    host.start()
    try:
        await _until(lambda: {s.state for s in host.statuses} == {TriggerState.RUNNING})
    finally:
        await host.stop()


async def test_a_lock_file_that_cannot_be_opened_fails_the_trigger_and_says_so(tmp_path: Path):
    blocker = tmp_path / "locks"
    blocker.write_text("a file where the directory should be", encoding="utf-8")
    host = _host(tmp_path, (Ticker(0, scope=TriggerScope.MACHINE), lambda event: None))
    host.start()
    try:
        await _until(lambda: _state(host, "ticker") is TriggerState.FAILED)
        assert "machine lock" in host.statuses[0].detail
    finally:
        await host.stop()


def test_a_name_longer_than_a_file_name_can_be_is_refused(tmp_path: Path):
    context = PluginContext(_config(tmp_path))

    with pytest.raises(ValueError, match="needs a name"):
        context.register_trigger(Ticker(name="a" * 65), lambda event: None)


def test_a_runtime_abandoned_with_its_loop_does_not_keep_the_name_for_ever(tmp_path: Path):
    async def abandon() -> None:
        host = _host(tmp_path, (Ticker(0), lambda event: None))
        host.start()
        await _until(lambda: _state(host, "ticker") is TriggerState.RUNNING)
        # no stop(): the script drops the runtime and its loop ends

    loop = asyncio.new_event_loop()
    loop.run_until_complete(abandon())
    loop.close()

    async def later() -> TriggerState:
        host = _host(tmp_path, (Ticker(0), lambda event: None))
        host.start()
        try:
            await _until(lambda: _state(host, "ticker") is not TriggerState.PENDING)
            return _state(host, "ticker")
        finally:
            await host.stop()

    assert asyncio.run(later()) is TriggerState.RUNNING
