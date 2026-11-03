"""What the gateway is told at start: where it listens, who may use it, and where it may start agents."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: The environment variables the command reads.
TOKEN_VARIABLE = "ZETTCODE_GATEWAY_TOKEN"
DIRECTORY_VARIABLE = "ZETTCODE_GATEWAY_DIR"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def default_directory() -> Path:
    """Return the gateway's own folder: ``$ZETTCODE_GATEWAY_DIR``, or ``~/.zettcode/gateway``."""
    override = os.environ.get(DIRECTORY_VARIABLE)
    return Path(override).expanduser() if override else Path.home() / ".zettcode" / "gateway"


@dataclass(frozen=True, slots=True)
class Settings:
    """The gateway's configuration.

    Attributes:
        token: What a person types to sign in. Empty means no sign-in at all, which only a gateway listening on this
            machine alone may have (see :attr:`open`).
        host: The address to listen on. Anything but loopback puts the gateway on the network.
        port: The port.
        roots: The directories a daemon may be started in, or in any directory below one of them. Nothing else is
            allowed: a page that could name any path could start an agent anywhere.
        allow_full: Whether a daemon may be given the ``full`` shell level (no sandbox, no approval). Decided by the
            command line (``--no-full`` turns it off), never from the page.
        directory: The gateway's own folder: its workspace, the id of its session, and what the page remembers.
        log_level: uvicorn's log level.
    """

    token: str = ""
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    roots: tuple[Path, ...] = ()
    allow_full: bool = False
    directory: Path = field(default_factory=default_directory)
    log_level: str = "info"

    @property
    def open(self) -> bool:
        """Return whether anybody who can reach the gateway may use it, with no token."""
        return not self.token

    @property
    def workspace(self) -> Path:
        """Return the directory the gateway's own session works in: it has nothing to edit, and its name is public."""
        return self.directory / "gateway"

    @property
    def url(self) -> str:
        """Return the address the page is served at."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"
