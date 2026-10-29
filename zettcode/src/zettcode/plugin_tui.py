"""The interface of ``ctx.tui``: what a plugin may register when the process has a screen.

The terminal's group implements this; the context is typed with it so a plugin author sees the surface from the type
checker, and the guard ``if ctx.tui is None`` narrows it. It lives here, in a leaf module both layers may import, so the
engine can name it without importing the terminal — and the terminal can implement it without the engine importing the
terminal's own types.

The parameter types are deliberately loose: a command handler, a theme, a pet, a presenter and a row builder are the
terminal's own classes, which this module does not import. The docstrings say what each argument is, and
:class:`zettcode.app.plugins.groups.TuiGroups` is the implementation that takes the real ones.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

__all__ = ["TuiGroup"]


class TuiGroup(ABC):
    """What only the terminal can hold, as ``ctx.tui``.

    A process without a screen has ``ctx.tui is None``; a plugin that only adds these starts its ``activate`` with
    ``if ctx.tui is None: return``.
    """

    @property
    @abstractmethod
    def registered_commands(self) -> Any:
        """Return the commands registered so far, in registration order."""

    @property
    @abstractmethod
    def themes(self) -> Any:
        """Return the palettes registered so far, in registration order."""

    @property
    @abstractmethod
    def pets(self) -> Any:
        """Return the pets registered so far, in registration order."""

    @property
    @abstractmethod
    def presenters(self) -> Any:
        """Return the presenters registered so far, in registration order."""

    @property
    @abstractmethod
    def turn_segments(self) -> Any:
        """Return the items of the line a request ends on, in the order they stand."""

    @abstractmethod
    def register_command(
        self,
        name: str,
        description: str,
        handler: Any,
        *,
        when_busy: str = "refuse",
        subcommands: Any = (),
    ) -> Any:
        """Add a command that may open a page, ask the shell to act, or wait for a request to end.

        ``handler`` is called with a :class:`~zettcode.app.commands.CommandContext` and returns a
        :class:`~zettcode.app.commands.CommandResult`. A command whose whole answer is text belongs on
        ``ctx.commands`` instead, where a process without a screen can run it too.
        """

    @abstractmethod
    def register_command_provider(self, provider: Any) -> Any:
        """Add commands that are worked out when the menu is built, from the current state."""

    @abstractmethod
    def register_theme(self, name: str, theme: Any, *, description: Any = "") -> Any:
        """Offer a palette under its name; ``/theme`` lists, previews and switches to it."""

    @abstractmethod
    def register_pet(self, name: str, pet: Any, *, description: Any = "") -> Any:
        """Offer a companion under its name; ``/pet`` lists, previews and switches to it."""

    @abstractmethod
    def register_presenter(self, presenter: Any) -> Any:
        """Draw a kind of entry, or one family inside a kind, instead of the way it is drawn now."""

    @abstractmethod
    def register_header_left(self, builder: Any, *, name: str = "", override: bool = False) -> tuple[Any, bool]:
        """Draw a segment on the header's left side."""

    @abstractmethod
    def register_header_right(self, builder: Any, *, name: str = "", override: bool = False) -> tuple[Any, bool]:
        """Draw a segment on the header's right side."""

    @abstractmethod
    def register_status_left(self, builder: Any, *, name: str = "", override: bool = False) -> tuple[Any, bool]:
        """Draw a segment on the status line's left side."""

    @abstractmethod
    def register_status_right(self, builder: Any, *, name: str = "", override: bool = False) -> tuple[Any, bool]:
        """Draw a segment on the status line's right side."""

    @abstractmethod
    def register_turn_segment(self, name: str, summary: str, builder: Any) -> Any:
        """Add one item to the line a request ends on."""
