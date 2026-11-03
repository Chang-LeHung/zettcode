"""The repository's shared isolation, when these tests run from it: see `support/conftest.py`.

A plugin's sdist carries its tests, and an unpacked sdist has no repository beside them: there the suite runs as it
did before the repository's suites shared one setup. From the checkout — where `make test` and the release job run
— the `HOME` redirect and the fixtures are the same as every other suite's.
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
SUPPORT = ROOT / "support"

# The checkout, not merely a directory called `support`: an unpacked sdist sits anywhere, and running a
# stranger's conftest would be worse than running without the shared isolation.
if (ROOT / "pyproject.toml").is_file() and SUPPORT.is_dir():
    sys.path.insert(0, str(SUPPORT))
    for _suite in sorted((ROOT / "packages").glob("*/tests")):
        sys.path.append(str(_suite))
    _SHARED = SUPPORT / "conftest.py"
    exec(compile(_SHARED.read_text(encoding="utf-8"), str(_SHARED), "exec"), globals())
