"""A bare `pytest` from the root is not how this repository runs its suites.

Every distribution's tests live in its own `packages/<name>/tests`, written against that package's
`[tool.pytest.ini_options]`; `make test` runs them one at a time. One session over all of them would take one
configuration for eight suites written against eight, and — the reason this file exists — it would execute the shared
`support/conftest.py` once per suite, each time moving `HOME` to a new temporary directory under tests that have
already imported zettcode and cached the paths they computed from the previous one.
"""

from __future__ import annotations

import pytest

raise pytest.UsageError(
    "each distribution's tests run on their own: use `make test`, "
    "or `uv run pytest packages/<name>/tests` for one of them"
)
