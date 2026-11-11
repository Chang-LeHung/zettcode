"""Small shims for the language versions this project supports.

ZettCode runs on Python 3.10 through 3.15, so the few things the standard
library grew in between live here instead of behind version checks at each use.
"""

from __future__ import annotations

import inspect
import sys
import typing
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


def _patch_typing_eval_type() -> None:
    """Give the pre-release 3.14 ``_eval_type`` the keyword pydantic already passes.

    Python 3.14.0b4 has no ``prefer_fwd_module`` argument; the final 3.14 release added it, and pydantic 2.13+
    calls with it. The beta is what some readers still have, and the difference is an unused hint, so the wrapper
    accepts it and calls the interpreter's own function without it. The final release is left alone.
    """
    if sys.version_info < (3, 14) or sys.version_info.releaselevel == "final":
        return
    original = getattr(typing, "_eval_type", None)
    if original is None or "prefer_fwd_module" in inspect.signature(original).parameters:
        return
    sentinel = getattr(typing, "_sentinel", None)

    def _eval_type(
        t: object,
        globalns: object,
        localns: object,
        type_params: object = sentinel,
        *,
        recursive_guard: frozenset[str] = frozenset(),
        format: object = None,
        owner: object = None,
        parent_fwdref: object = None,
        prefer_fwd_module: bool = False,
    ) -> object:
        del prefer_fwd_module
        return original(
            t,
            globalns,
            localns,
            type_params,
            recursive_guard=recursive_guard,
            format=format,
            owner=owner,
            parent_fwdref=parent_fwdref,
        )

    typing._eval_type = _eval_type


_patch_typing_eval_type()
