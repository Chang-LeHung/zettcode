"""The collector runs while the program works and never while the reader types.

(The burst pause a restore uses is ``test_collector.py``; this is the policy that sits above it.)
"""

from __future__ import annotations

import asyncio
import gc

import pytest

from zettcode.app.ui import app as app_module
from zettcode.app.ui.gc_policy import TYPING_GRACE, CollectorPolicy, freeze_long_lived
from zettcode.collector import collector_paused

# The conftest gives the collector back as it found it after every test, so these set it freely.

GRACE = 0.05


def _policy(**options) -> CollectorPolicy:
    return CollectorPolicy(grace=GRACE, **options)


# -- the three states ----------------------------------------------------------------------------------


def test_nothing_running_means_the_collector_is_off():
    gc.enable()

    _policy().rest()

    assert gc.isenabled() is False


def test_work_turns_the_collector_on_and_the_end_of_it_turns_it_off():
    policy = _policy()
    policy.rest()

    policy.work_started()
    assert gc.isenabled() is True

    policy.work_ended()
    assert gc.isenabled() is False


def test_a_keystroke_while_resting_changes_nothing_and_arms_nothing():
    policy = _policy()
    policy.rest()

    policy.typed()

    assert gc.isenabled() is False and policy._timer is None


async def test_a_keystroke_while_working_turns_it_off_at_once_and_back_on_after_the_pause():
    policy = _policy()
    policy.work_started()

    policy.typed()
    assert gc.isenabled() is False, "off before the keystroke's frame is painted, not after"

    await asyncio.sleep(GRACE * 3)

    assert gc.isenabled() is True and policy._timer is None


async def test_it_comes_back_only_after_the_last_of_several_keystrokes():
    policy = _policy()
    policy.work_started()
    policy.typed()

    for _ in range(4):
        await asyncio.sleep(GRACE * 0.6)  # a key every 30 ms keeps the pause going past the first deadline
        policy.typed()
        assert gc.isenabled() is False

    await asyncio.sleep(GRACE * 3)
    assert gc.isenabled() is True


async def test_a_burst_of_keystrokes_arms_one_timer_and_only_moves_its_deadline():
    policy = _policy()
    policy.work_started()
    policy.typed()
    timer = policy._timer

    for _ in range(200):
        policy.typed()

    assert policy._timer is timer and timer is not None, "a keystroke is a comparison and an assignment, not a timer"


async def test_work_that_ends_during_the_pause_leaves_it_off_for_good():
    policy = _policy()
    policy.work_started()
    policy.typed()

    policy.work_ended()
    assert policy._timer is None, "the wait for the reader to stop is dropped with the work"
    await asyncio.sleep(GRACE * 3)

    assert gc.isenabled() is False


async def test_work_that_starts_just_after_a_keystroke_waits_for_the_reader_to_pause():
    policy = _policy()
    policy.rest()
    policy.work_started()
    policy.typed()
    policy.work_ended()
    policy.work_started()  # the reader pressed Enter on a draft they were still editing, and a turn began

    assert gc.isenabled() is False
    await asyncio.sleep(GRACE * 3)

    assert gc.isenabled() is True


def test_with_no_loop_to_wake_it_a_keystroke_leaves_it_off_and_raises_nothing():
    policy = _policy()
    policy.work_started()

    policy.typed()

    assert gc.isenabled() is False and policy._timer is None


async def test_closing_puts_the_collector_back_on_and_drops_the_timer():
    policy = _policy()
    policy.work_started()
    policy.typed()

    policy.close()
    policy.close()  # leaving twice is still leaving

    assert gc.isenabled() is True and policy._timer is None
    await asyncio.sleep(GRACE * 3)
    assert gc.isenabled() is True


def test_a_clock_that_is_not_the_real_one_decides_when_the_pause_is_over():
    now = [100.0]
    policy = CollectorPolicy(grace=0.5, clock=lambda: now[0])
    policy.work_started()

    policy.typed()
    policy._apply()
    assert gc.isenabled() is False

    now[0] = 100.6
    policy._apply()
    assert gc.isenabled() is True


def test_the_default_pause_is_long_enough_to_bridge_two_words_and_short_enough_to_matter():
    assert 0.2 <= TYPING_GRACE <= 1.0


# -- freezing the heap once it has warmed -----------------------------------------------------------------


def test_freezing_takes_the_heap_out_of_the_collectors_reach_without_collecting_first(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(gc, "freeze", lambda: calls.append("freeze"))
    monkeypatch.setattr(gc, "collect", lambda *a: calls.append("collect") or 0)

    freeze_long_lived()

    assert calls == ["freeze"], "a collection first would cost the pause this exists to avoid"


def test_a_frozen_object_is_still_freed_when_its_last_reference_goes():
    """The reason freezing is safe: it only stops the *cyclic* collector from walking an object."""
    import weakref

    class Thing:
        pass

    thing = Thing()
    ref = weakref.ref(thing)
    gc.freeze()

    del thing

    assert ref() is None


# -- through the shell ---------------------------------------------------------------------------------------


def _shell():
    from test_zettcode_app import _harness, build_app

    app = build_app(block=True)
    app.collector.grace = GRACE
    return app, _harness(app)


async def test_the_collector_is_on_while_a_request_runs_and_off_when_it_is_over():
    app, harness = _shell()
    app.collector.rest()
    assert gc.isenabled() is False

    harness.write("a long task")
    harness.press("enter")
    await asyncio.sleep(0.01)
    assert app._busy and gc.isenabled() is True

    app.task.cancel()
    await asyncio.gather(app.task, return_exceptions=True)
    assert not app._busy and gc.isenabled() is False


async def test_typing_while_a_request_runs_pauses_the_collector_and_it_resumes_when_the_reader_stops():
    app, harness = _shell()
    harness.write("a long task")
    harness.press("enter")
    await asyncio.sleep(0.01)
    assert gc.isenabled() is True

    harness.write("and a follow-up I am still writing")
    assert gc.isenabled() is False, "the very keystroke that changed the draft switched it off"

    await asyncio.sleep(GRACE * 3)
    assert gc.isenabled() is True

    app.task.cancel()
    await asyncio.gather(app.task, return_exceptions=True)


async def test_typing_with_nothing_running_does_not_switch_the_collector_on():
    app, harness = _shell()
    app.collector.rest()

    harness.write("a message nobody has sent yet")
    await asyncio.sleep(GRACE * 3)

    assert gc.isenabled() is False


async def test_a_command_runs_with_the_collector_on_like_any_other_work():
    from zettcode.app.commands import Command, CommandResult

    app, harness = _shell()
    app.collector.rest()
    seen: list[bool] = []

    async def probe(context):
        seen.append(gc.isenabled())
        return CommandResult()

    app.commands = (*app.commands, Command("/probe", "probe", "plugin", probe))
    harness.write("/probe")
    harness.press("enter")
    await asyncio.wait_for(app.task, 2.0)

    assert seen == [True], "a command is work, and a restore or a compaction allocates as much as a turn"
    assert gc.isenabled() is False, "and it is off again when it is over"


async def test_starting_the_background_work_puts_the_collector_to_rest():
    app, _ = _shell()
    gc.enable()

    app.start_background()
    assert gc.isenabled() is False
    await asyncio.wait_for(app.stop_background(), 2.0)


async def test_the_heap_is_frozen_when_the_runtime_has_finished_warming(monkeypatch):
    app, _ = _shell()
    frozen: list[str] = []
    monkeypatch.setattr(app_module, "freeze_long_lived", lambda: frozen.append("frozen"))

    app.start_background()
    assert frozen == [], "not before the runtime is up: the SDKs are what is being waited for"
    await asyncio.wait_for(app._warm, 2.0)
    await asyncio.sleep(0)

    assert frozen == ["frozen"]
    await asyncio.wait_for(app.stop_background(), 2.0)


async def test_a_warm_up_that_failed_still_leaves_the_loaded_heap_frozen(monkeypatch):
    app, _ = _shell()
    frozen: list[str] = []
    monkeypatch.setattr(app_module, "freeze_long_lived", lambda: frozen.append("frozen"))

    async def broken():
        raise RuntimeError("no network")

    app.agent.runtime.start = broken  # type: ignore[method-assign]
    app.start_background()
    await asyncio.gather(app._warm, return_exceptions=True)
    await asyncio.sleep(0)

    assert frozen == ["frozen"]
    await asyncio.wait_for(app.stop_background(), 2.0)


async def test_leaving_puts_the_collector_back_on():
    app, _ = _shell()
    app.start_background()
    assert gc.isenabled() is False

    await asyncio.wait_for(app.stop_background(), 2.0)

    assert gc.isenabled() is True


@pytest.mark.parametrize("busy", [True, False])
def test_setting_the_busy_state_is_the_one_place_the_collector_follows_it(busy):
    app, _ = _shell()

    app._set_busy(busy)

    assert gc.isenabled() is busy


async def test_a_pause_that_was_extended_after_the_timer_was_armed_still_ends():
    """The timer fires at the first deadline, finds the reader typed since, and has to wait again.

    Without that the collector would stay off for good after a reader's last keystroke landed inside
    the first window: only a *later* keystroke would arm a timer, and there is none.
    """
    policy = _policy()
    policy.work_started()
    policy.typed()  # a timer is armed for GRACE from now
    await asyncio.sleep(GRACE * 0.6)
    policy.typed()  # the deadline moves out; the reader then stops for good

    await asyncio.sleep(GRACE * 0.7)  # the first deadline has passed, the second has not
    assert gc.isenabled() is False

    await asyncio.sleep(GRACE * 3)
    assert gc.isenabled() is True, "re-armed by the timer itself, not by a keystroke that never came"


# -- yielding to a burst that already holds the collector off -------------------------------------------------


def test_work_that_starts_during_a_burst_does_not_switch_the_collector_on_under_it():
    policy = _policy()
    policy.rest()

    with collector_paused():
        policy.work_started()
        assert gc.isenabled() is False, "the burst pause is what the restore was waiting for"


async def test_a_pause_that_ends_during_a_burst_does_not_end_the_burst():
    policy = _policy()
    policy.work_started()
    policy.typed()

    with collector_paused():
        await asyncio.sleep(GRACE * 3)  # the timer fires in the middle of the burst
        assert gc.isenabled() is False


def test_after_the_burst_the_policy_has_the_last_word():
    policy = _policy()
    policy.work_started()
    assert gc.isenabled() is True

    with collector_paused():
        assert gc.isenabled() is False
    assert gc.isenabled() is True, "the burst gave back what it found"

    policy.work_ended()
    assert gc.isenabled() is False, "and the end of the work turns it off, as it would have without the burst"
