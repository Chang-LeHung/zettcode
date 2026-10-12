"""Where ZettCode keeps its own files.

Constants only, and deliberately importable without the settings module: the
shell takes the terminal and points its diagnostics at the log before it has
read the config, so the paths cannot live behind that import.
"""

from __future__ import annotations

import os
import shlex
from pathlib import Path

#: The conventional config file, read when the user has created one.
CONFIG_FILE = Path.home() / ".zettcode" / "config.toml"

#: Session storage is an application default, not a model setting.
DEFAULT_STORE = Path.home() / ".zettcode" / "sessions"

#: MCP servers are ZettCode's own file, so they are configured independently of
#: whatever other zett tools read.
DEFAULT_MCP_CONFIG = Path.home() / ".zettcode" / "mcp.json"

#: What the background release check leaves behind: the newest version it saw
#: and the version the reader asked not to hear about again.
DEFAULT_UPDATE_FILE = Path.home() / ".zettcode" / "update.json"

#: Where tiktoken keeps the vocabulary it downloads once. Deliberately not the
#: OS temp directory, which is cleaned whenever the system feels like it: a purge
#: turns the next token count into a 1.7 MB download, and `/context` waits behind
#: it. Under this program's own directory the fetch happens once.
DEFAULT_TOKENIZER_CACHE = Path.home() / ".zettcode" / "cache" / "tiktoken"

#: Anything written to stderr while the TUI owns the screen is kept here: a
#: child process — an MCP server announcing itself, say — cannot know that the
#: frame is the interface, and the renderer only repaints what it changed.
DEFAULT_LOG = Path.home() / ".zettcode" / "log" / "tui.log"


def config_path(path: str | Path | None = None) -> Path:
    """Return the config file to read: an explicit path, ``$ZETTCODE_CONFIG``, or the default.

    Here rather than beside the settings it loads because the frame drawn before
    those settings are read needs to name the same file without importing them.
    """
    if path is not None:
        return Path(path).expanduser()
    override = os.getenv("ZETTCODE_CONFIG")
    return Path(override).expanduser() if override else CONFIG_FILE


def resume_command(session_id: str, workspace: Path) -> str:
    """Return the command that reopens one stored session from anywhere.

    It is written down once because two places say it: the line printed on the way
    out, and the line a fork leaves in the conversation. The workspace is part of it
    because the store is keyed by workspace — the same id means nothing in another
    checkout — and it is quoted, because a path may hold a space.
    """
    return f"zettcode --resume {shlex.quote(session_id)} --workspace {shlex.quote(str(workspace))}"
