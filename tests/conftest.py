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
