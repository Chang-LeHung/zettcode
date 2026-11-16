"""One word a command takes first, kept apart from the widgets the rest of the command contract names.

The completion menu uses it, and so does a plain command registered for a process with no screen; importing this
module must not import the terminal, which is why it is not defined beside ``Widget`` in :mod:`.commands`.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Subcommand"]


@dataclass(frozen=True, slots=True)
class Subcommand:
    """One word a command takes first, offered by the completion menu once the command is typed.

    Attributes:
        name: The word as typed (``"add"``); it replaces what the reader has typed after the command.
        description: One-line summary shown beside it in the menu.
        needs_more: The word is only the start of an argument (``/config add`` still asks which
            provider). Enter on it fills it in and leaves the rest to the reader; without this,
            Enter on it runs the command with it, as for a model or a level that says everything.
        current: The word names what is in force now. The menu marks it and opens with it highlighted,
            so Enter straight after the space changes nothing.
    """

    name: str
    description: str = ""
    needs_more: bool = False
    current: bool = False
