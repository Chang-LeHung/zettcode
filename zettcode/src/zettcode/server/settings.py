"""What the server was started with: the workspace it serves and the level its runs start at.

One process serves one workspace. The SDK keeps the working directory of the process, so a second workspace in the
same process is a conflict rather than a feature; a second workspace is a second ``zettcode-server``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: The permission a run starts at. Shell commands are refused, which is what an HTTP endpoint can safely assume:
#: nobody is at a terminal to answer for one, and whoever calls it names the level they want.
DEFAULT_PERMISSION = "deny"

#: The interface to bind. Loopback, so starting the server does not put a shell on the network by accident.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3290

#: The environment variable that supplies the bearer token, when one is wanted.
TOKEN_VARIABLE = "ZETTCODE_SERVER_TOKEN"


@dataclass(frozen=True, slots=True)
class Settings:
    """The workspace, the socket, and how a run starts.

    Attributes:
        workspace: The directory the agent works in.
        host: The interface to bind.
        port: The port to bind.
        token: The bearer token every endpoint but ``/health`` requires; ``None`` requires none. It defaults to
            ``$ZETTCODE_SERVER_TOKEN``, so a token can be kept out of the command line.
        permission: The shell permission level a run starts at: ``deny``, ``ask``, ``safe`` (every command in a
            sandbox that writes only the workspace and ``/tmp``) or ``full``. ``auto`` is the old name of ``full``.
        harness: Whether the just-in-time harness, which lets the model write and run small Python tools, starts on.
        model: The model to start on, by name, or ``None`` for the first configured one.
        effort: The reasoning level to start on, or ``None`` for the model's own.
        config_path: A configuration file to read instead of ``~/.zettcode/config.toml``.
        title: The ``Server`` header, so a client can tell which server it is talking to.
        log_level: What uvicorn logs; ``info`` says which requests arrived.
    """

    workspace: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    token: str | None = field(default_factory=lambda: os.environ.get(TOKEN_VARIABLE) or None)
    permission: str = DEFAULT_PERMISSION
    harness: bool = False
    model: str | None = None
    effort: str | None = None
    config_path: Path | None = None
    title: str = "zettcode-server"
    log_level: str = "info"

    @property
    def url(self) -> str:
        """Return the address the server serves on, as a client writes it."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"
