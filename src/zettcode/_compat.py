"""Small shims for the language versions this project supports.

ZettCode runs on Python 3.10 through 3.14, so the few things the standard
library grew in between live here instead of behind version checks at each use.
"""

from __future__ import annotations

import sys
from enum import Enum

if sys.version_info >= (3, 11):
    from builtins import BaseExceptionGroup, ExceptionGroup

    import tomllib
else:  # pragma: no cover - the branch only the 3.10 runtime takes
    import tomli as tomllib
    from exceptiongroup import BaseExceptionGroup, ExceptionGroup


__all__ = ["BaseExceptionGroup", "ExceptionGroup", "StrEnum", "tomllib"]


class StrEnum(str, Enum):
    """A string-valued enum, for the versions before ``enum.StrEnum``.

    The standard library's version formats as its value, so ``f"{member}"`` is
    ``"ready"`` rather than ``"Activity.READY"``; the status line and the stored
    metadata rely on that, so every interpreter uses this class instead of the
    standard one and the wording cannot drift with the version.
    """

    def __str__(self) -> str:
        """Return the member's value, as ``enum.StrEnum`` does."""
        return str(self.value)
