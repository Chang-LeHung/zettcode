"""Pausing the cyclic collector for a burst of long-lived allocations, and putting it back as found."""

from __future__ import annotations

import gc
import threading

import pytest

from zettcode.collector import collector_paused


@pytest.fixture(autouse=True)
def _collector_as_found():
    """Leave the interpreter's collector exactly as the test found it, whatever the test did."""
    was = gc.isenabled()
    yield
    gc.enable() if was else gc.disable()


def test_the_collector_is_off_for_the_body_and_back_on_after():
    gc.enable()

    with collector_paused():
        assert not gc.isenabled()

    assert gc.isenabled()


def test_it_is_put_back_when_the_body_raises():
    gc.enable()

    with pytest.raises(RuntimeError):
        with collector_paused():
            raise RuntimeError("boom")

    assert gc.isenabled()


def test_a_collector_that_was_already_off_is_not_switched_on():
    """Someone who turned it off had a reason; a pause must not undo it on the way out."""
    gc.disable()

    with collector_paused():
        pass

    assert not gc.isenabled()


def test_overlapping_pauses_hold_it_off_until_the_last_one_ends():
    """The command line's build and an in-app resume can overlap; the first to finish must not turn it on."""
    gc.enable()
    outer = collector_paused()
    inner = collector_paused()

    outer.__enter__()
    inner.__enter__()
    inner.__exit__(None, None, None)
    assert not gc.isenabled(), "the outer pause is still running"
    outer.__exit__(None, None, None)

    assert gc.isenabled()


def test_pauses_from_two_threads_leave_it_on_when_both_are_done():
    gc.enable()
    entered = threading.Barrier(3)
    release = threading.Event()
    seen: list[bool] = []

    def hold() -> None:
        with collector_paused():
            entered.wait(2)
            seen.append(gc.isenabled())
            release.wait(2)

    threads = [threading.Thread(target=hold) for _ in range(2)]
    for thread in threads:
        thread.start()
    entered.wait(2)
    release.set()
    for thread in threads:
        thread.join(2)

    assert seen == [False, False]
    assert gc.isenabled()
