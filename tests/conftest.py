"""Shared test isolation for the suite."""

from __future__ import annotations

import pytest


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
