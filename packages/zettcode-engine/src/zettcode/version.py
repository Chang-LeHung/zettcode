"""The one place the version is written.

Every distribution in this repository is built from this file (`[tool.hatch.version]` in each `pyproject.toml` points
here), so a release is one edit and one `v<version>` tag, as it always was. It ships with the engine, which is the root
of the dependency graph: everything else may import `zettcode.version`, nothing has to be imported to read it.
"""

from __future__ import annotations

#: The version of the program and of every distribution built beside it.
__version__ = "0.3.3"
