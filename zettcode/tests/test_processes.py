"""Asking whether a process exists, on both platforms: the probe the gateway's stop and start decide from."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Iterator

import pytest

from zettcode import processes


@pytest.fixture
def running() -> Iterator[Callable[..., subprocess.Popen[bytes]]]:
    """Start `python` children and end any this test leaves running."""
    started: list[subprocess.Popen[bytes]] = []

    def start(*arguments: str) -> subprocess.Popen[bytes]:
        child = subprocess.Popen([sys.executable, *arguments])
        started.append(child)
        return child

    yield start
    for child in started:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_a_running_process_is_still_there_and_a_reaped_one_is_not(running):
    child = running("-c", "import time; time.sleep(30)")

    assert processes.still_there(child.pid) is True

    child.kill()
    child.wait()
    assert processes.still_there(child.pid) is False


@pytest.mark.parametrize("pid", [0, -1, os.getpid()])
def test_still_there_never_probes_this_process_or_a_negative_id(pid):
    assert processes.still_there(pid) is False
