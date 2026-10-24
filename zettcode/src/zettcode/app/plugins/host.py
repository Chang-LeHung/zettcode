"""The way from a plugin to the shell, which does not exist yet when the plugin is activated."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.app.commands import CommandHost

#: Provided by the terminal's loader to every plugin: the link a plugin follows to the shell once there is one.
HOST_LINK = "host-link"


class HostLink:
    """The way from a plugin to the shell, which does not exist yet when the plugin is activated.

    A plugin is activated before the shell is built, so a command cannot capture the shell the way it captures a
    setting. What it needs *while it runs* it gets from ``CommandContext.host``; what it needs *before it runs* — the
    words its completion menu offers, which depend on the models configured now and not when the program started —
    it reads through this link, which the shell attaches itself to once it is built.

    ::

        link = container.service(HOST_LINK, HostLink)
        container.register_command("model", "choose a model", handler, subcommands=lambda: words(link.host))

    Attributes:
        host: The shell, or ``None`` until it is attached (and in a program that has no shell, such as a test).
    """

    def __init__(self) -> None:
        self.host: CommandHost | None = None

    def attach(self, host: CommandHost) -> None:
        """Point the link at the shell."""
        self.host = host
