"""Use the checkout's shared test isolation; an unpacked sdist remains independent."""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
SUPPORT = ROOT / "support"
if (ROOT / "pyproject.toml").is_file() and SUPPORT.is_dir():
    sys.path.insert(0, str(SUPPORT))
    for _suite in sorted((ROOT / "packages").glob("*/tests")):
        sys.path.append(str(_suite))
    _SHARED = SUPPORT / "conftest.py"
    exec(compile(_SHARED.read_text(encoding="utf-8"), str(_SHARED), "exec"), globals())
