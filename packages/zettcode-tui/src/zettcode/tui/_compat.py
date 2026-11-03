"""The two version shims the framework needs, so `zettcode-tui` depends on nothing of ours.

The release notes of the framework say what it is: a widget toolkit that knows nothing of the agent. It needs the
string-valued enum (the standard library's is 3.11's, and its spelling is what the rows and the theme files rely on) and
a TOML reader for a theme file. Both are ten lines here rather than an import of another distribution, which would put
`zett-agent` behind a widget.
"""

from __future__ import annotations

import sys
from enum import Enum

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - the branch only the 3.10 runtime takes
    import tomli as tomllib

__all__ = ["StrEnum", "tomllib"]


class StrEnum(str, Enum):
    """A string-valued enum, for the versions before ``enum.StrEnum``.

    The standard library's version formats as its value, so ``f"{member}"`` is ``"ready"`` rather than
    ``"Activity.READY"``; the rows and the theme files rely on that, so every interpreter uses this class instead of the
    standard one and the wording cannot drift with the version.
    """

    def __str__(self) -> str:
        """Return the member's value, as ``enum.StrEnum`` does."""
        return str(self.value)
