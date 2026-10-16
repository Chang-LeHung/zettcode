"""Shared test isolation for the suite."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

import pytest

# The suite runs in a home directory of its own, set before anything from zettcode is imported.
# Every default the program has — the config file, the session store, the release check's state,
# the tokenizer's cache, the log, the theme — is `Path.home() / ".zettcode" / ...` evaluated when
# its module is imported, so this has to come first: patching a variable afterwards does not move
# a default that was already computed, and a test that builds a config without naming a store
# (`resolve_config(["-w", tmp_path])` does exactly that) would write into the developer's real
# `~/.zettcode`. That is what happened: every run left two workspace folders behind, and
# thousands piled up in a real store, each with a metadata file listing one throwaway session.
_HOME = tempfile.mkdtemp(prefix="zettcode-test-home-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME  # what `Path.home()` reads on Windows
atexit.register(shutil.rmtree, _HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def _no_broker_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a test run from starting the background session broker.

    A shell that starts connects to the broker and starts one when none answers, and a broker is a
    process that outlives whoever started it. No test of the shell wants one: the tests of the broker
    itself start theirs explicitly, on a directory of their own, and the tests of the shell hand it a
    fake.
    """
    from zettcode.broker import finder

    monkeypatch.setattr(finder, "spawn_broker", lambda directory: None)


@pytest.fixture(autouse=True)
def _no_installed_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic: an installed plugin must not join a test run.

    ``ZettCodeRuntime.preview`` loads every ``zettcode.plugins`` entry point the
    environment advertises, which would make tests depend on whatever the
    developer happens to have installed. The plugin tests inject their own entry
    points, so discovery is only stubbed here, never removed.
    """
    from zettcode.plugins import loader

    monkeypatch.setattr(loader, "installed_entry_points", lambda: ())


@pytest.fixture(autouse=True)
def _a_local_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test as if on the reader's own machine, outside tmux.

    Where a copy goes — and what the shell says about it — depends on whether the process was
    started over ``ssh``, and an escape sequence is wrapped when it is inside tmux. A developer
    who runs the suite over ssh, or in a tmux window, would otherwise see the wording and the
    route change under their feet. The tests that are *about* those say so with their own
    ``setenv``.
    """
    from zettcode.tui.clipboard import CLIPBOARD_ENV, SSH_VARIABLES

    for name in (*SSH_VARIABLES, "TMUX", CLIPBOARD_ENV):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _offline_tokenizers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every tokenizer in the suite off the network.

    Starting a runtime starts two background loads — the ``/context`` report's encoding and the one
    compaction counts with — and a vocabulary that is not in the cache is a download. A test that
    wants an encoder passes its own ``loader``; one that does not gets an answer as if the machine
    were offline, which both counters take as "estimate", exactly as a first run with no network
    would.
    """
    from zettcode.app.agent.extensions import context

    def offline(encoding: str):
        raise OSError(f"the {encoding} vocabulary is not fetched in tests")

    monkeypatch.setattr(context, "_tiktoken_encoder", offline)


@pytest.fixture(autouse=True)
def _keep_the_collector_as_it_was() -> None:
    """Give back the collector as it was: its thresholds, whether it is on, and what is frozen.

    ``cli.main`` raises the young-generation threshold; a test that calls it must not leave that
    behind for every test after it.
    """
    import gc

    before = gc.get_threshold()
    was_on = gc.isenabled()
    yield
    gc.set_threshold(*before)
    # The shell switches the collector with its busy state and freezes the heap once it has warmed; a
    # test that ran a shell must not leave the next one with the collector off or the heap frozen.
    (gc.enable if was_on else gc.disable)()
    gc.unfreeze()
