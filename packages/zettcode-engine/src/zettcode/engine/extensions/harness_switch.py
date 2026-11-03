"""Whether the just-in-time harness is on. Nothing here imports the framework, so a launch can hold it for free."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["HarnessSwitch"]


@dataclass
class HarnessSwitch:
    """Whether the harness is on; the runtime owns it, the command flips it, the extension reads it.

    Attributes:
        on: ``True`` while the model is given the harness.
    """

    on: bool = False
