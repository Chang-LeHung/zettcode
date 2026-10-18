"""The import pipeline: what it warms, and what happens when nobody waits.

A module that sleeps while it imports stands in for a model SDK: it makes the
difference between running an import on a thread the process leaves behind and
running it on one the interpreter joins at shutdown measurable, at a test's
speed rather than a package's.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time
from pathlib import Path

from zettcode.app.pipeline import DaemonCall, ImportPipeline

#: ``time.sleep`` in the module body: an import that takes as long as we ask.
SLOW = "import time\ntime.sleep({delay})\nVALUE = 1\n"


def _write_module(directory: Path, name: str, delay: float = 0.0, *, announce: Path | None = None) -> None:
    """Write a module that sleeps while importing, optionally announcing that it started."""
    marker = f"open({str(announce)!r}, 'w').close()\n" if announce is not None else ""
    (directory / f"{name}.py").write_text(marker + SLOW.format(delay=delay), encoding="utf-8")


def _until(predicate, timeout: float = 5.0) -> bool:
    """Wait for a condition a thread is expected to bring about."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_start_returns_before_the_imports_finish(tmp_path, monkeypatch):
    """The thread is the point: whoever asks for the warm-up is not held by it."""
    monkeypatch.syspath_prepend(str(tmp_path))
    _write_module(tmp_path, "zettcode_pipeline_slow", delay=0.6)
    pipeline = ImportPipeline(("zettcode_pipeline_slow",))

    started = time.perf_counter()
    pipeline.start()
    elapsed = time.perf_counter() - started

    assert elapsed < 0.3, f"start blocked for {elapsed:.2f}s"
    assert pipeline.done is False
    assert pipeline.wait(0) is False

    assert pipeline.wait(5) is True
    assert pipeline.done is True
    assert "zettcode_pipeline_slow" in sys.modules


def test_a_module_that_cannot_be_imported_is_recorded_and_the_list_carries_on(tmp_path, monkeypatch):
    """A missing module is reported where it is used, not by stopping the warm-up."""
    monkeypatch.syspath_prepend(str(tmp_path))
    _write_module(tmp_path, "zettcode_pipeline_first", delay=0.05)
    _write_module(tmp_path, "zettcode_pipeline_second", delay=0.05)
    pipeline = ImportPipeline(("zettcode_pipeline_first", "zettcode_no_such_module", "zettcode_pipeline_second"))

    pipeline.start()

    assert pipeline.wait(5) is True
    assert set(pipeline.failures) == {"zettcode_no_such_module"}
    assert isinstance(pipeline.failures["zettcode_no_such_module"], ImportError)
    # The list carried on past the failure and finished what it could.
    assert "zettcode_pipeline_first" in sys.modules
    assert "zettcode_pipeline_second" in sys.modules


def test_stop_gives_up_at_the_next_module_boundary(tmp_path, monkeypatch):
    """A shutdown is noticed between two imports, never inside one."""
    monkeypatch.syspath_prepend(str(tmp_path))
    announce = tmp_path / "started"
    _write_module(tmp_path, "zettcode_pipeline_running", delay=0.6, announce=announce)
    _write_module(tmp_path, "zettcode_pipeline_never")
    pipeline = ImportPipeline(("zettcode_pipeline_running", "zettcode_pipeline_never"))
    pipeline.start()
    # The thread is inside the first import once it has announced itself.
    assert _until(announce.exists), "the pipeline never reached the first module"

    pipeline.stop()

    assert pipeline.done is True, "stopping has to release whoever waits"
    assert pipeline.wait(5) is True
    # The import that was already running finished rather than being cut in half.
    assert "zettcode_pipeline_running" in sys.modules
    assert "zettcode_pipeline_never" not in sys.modules


def test_a_finish_reported_to_a_closed_loop_is_not_an_error(capsys):
    """The thread can outlive the shell that asked for it, and that is not a failure.

    A quit that beats the imports leaves the thread running with nobody to tell:
    the loop it would have reported to is closed, and a traceback on the way out
    of a clean exit would be the one thing this design must not print.
    """

    def closed_loop() -> None:
        raise RuntimeError("Event loop is closed")

    pipeline = ImportPipeline(("json",))
    pipeline.start(on_finish=closed_loop)

    assert _until(lambda: not any(thread.name == "zettcode-imports" for thread in threading.enumerate()))
    assert pipeline.failures == {}
    assert capsys.readouterr().err == ""


async def test_a_daemon_call_answers_and_can_be_left_behind():
    """The three outcomes a caller has to be able to tell apart."""
    quick = DaemonCall(lambda: "an answer")
    quick.start()
    assert await quick.wait(5) == "an answer"
    assert quick.peek() == "an answer"

    slow = DaemonCall(lambda: (time.sleep(0.5), "late")[1])
    slow.start()
    assert await slow.wait(0.01) is None, "the deadline is what a panel cannot wait past"
    assert slow.peek() is None, "it has not answered yet"
    await asyncio.sleep(0.6)
    assert slow.peek() == "late", "and the answer is adopted rather than thrown away"

    failing = DaemonCall(lambda: 1 / 0)
    failing.start()
    assert await failing.wait(5) is None, "a failure is an answer of None, not a raise"


def test_a_process_does_not_wait_for_a_daemon_call_it_abandoned(tmp_path):
    """The reason this class exists beside ``asyncio.to_thread``.

    The default executor's threads are joined while the interpreter shuts down,
    so a call still running when the shell leaves delays the exit by its whole
    duration. A daemon thread is left behind, and the answer is nobody's.
    """
    slow = tmp_path / "slow_module.py"
    slow.write_text("import time\ntime.sleep(1.5)\n", encoding="utf-8")
    script = "\n".join(
        [
            "import asyncio, sys",
            "sys.path.insert(0, sys.argv[1])",
            "from zettcode.app.pipeline import DaemonCall",
            "async def main():",
            "    call = DaemonCall(lambda: __import__('slow_module'))",
            "    call.start()",
            "    await call.wait(0.01)",
            "    print('gave up', flush=True)",
            "asyncio.run(main())",
        ]
    )

    started = time.perf_counter()
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=20)
    elapsed = time.perf_counter() - started

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "gave up"
    assert elapsed < 1.0, f"the process waited {elapsed:.2f}s for a call it abandoned"
    assert result.stderr == "", "leaving a call behind is not an error"


def test_a_process_that_ends_mid_import_is_not_held_open(tmp_path):
    """A launch abandoned while warming exits at once, and without saying anything.

    The imports run on a daemon thread precisely so this holds: an executor's
    threads are joined while the interpreter shuts down, which would delay the
    same exit by the whole import — a second or so for a model SDK, which is
    what a reader who opens the shell and closes it again would sit through.
    """
    _write_module(tmp_path, "zettcode_pipeline_abandoned", delay=1.5)
    script = "\n".join(
        [
            "import sys",
            "sys.path.insert(0, sys.argv[1])",
            "from zettcode.app.pipeline import DaemonCall, ImportPipeline",
            "ImportPipeline(('zettcode_pipeline_abandoned',)).start()",
        ]
    )

    started = time.perf_counter()
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, timeout=20)
    elapsed = time.perf_counter() - started

    assert result.returncode == 0, result.stderr
    assert elapsed < 1.0, f"the process waited {elapsed:.2f}s for an import nobody wanted"
    assert result.stderr == "", "leaving an import behind is not an error"
