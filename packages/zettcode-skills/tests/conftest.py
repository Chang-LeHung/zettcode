"""The suite's shared isolation, one copy for every distribution: see `support/conftest.py`."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]

#: Where the fakes and the shared setup live, and where the other suites are: a few tests share a harness with the
#: tests of the distribution that owns it, so every suite is importable by name. Each distribution still runs its own
#: tests, with its own pytest configuration; nothing here collects another suite's files.
sys.path.insert(0, str(ROOT / "support"))
for _suite in sorted((ROOT / "packages").glob("*/tests")):
    sys.path.append(str(_suite))

# Executed into this module, so the fixtures it defines are this conftest's and pytest collects them as usual.
_SHARED = ROOT / "support" / "conftest.py"
exec(compile(_SHARED.read_text(encoding="utf-8"), str(_SHARED), "exec"), globals())
