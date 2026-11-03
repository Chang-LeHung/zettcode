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

#: Plugins the reader switched off with ``/plugins disable``; read at the next start. Kept beside the store so the
#: reader's config file stays theirs, and a name here is an entry-point name, the same one ``[plugins] disable`` takes.
DEFAULT_PLUGINS_FILE = DEFAULT_STORE.parent / "plugins.json"

#: A plugin that is a single ``.py`` file lives here instead of being installed into site-packages: one file, one
#: module, loaded at the next start. ``$ZETTCODE_PLUGINS_DIR`` moves it, the way ``$ZETTCODE_CONFIG`` moves the config.
DEFAULT_PLUGINS_DIR = DEFAULT_STORE.parent / "plugins"
PLUGINS_DIR_VARIABLE = "ZETTCODE_PLUGINS_DIR"


def plugins_dir() -> Path:
    """Return the folder single-file plugins live in: ``$ZETTCODE_PLUGINS_DIR`` or ``~/.zettcode/plugins``."""
    override = os.getenv(PLUGINS_DIR_VARIABLE)
    return Path(override).expanduser() if override else DEFAULT_PLUGINS_DIR


#: MCP servers are ZettCode's own file, so they are configured independently of
#: whatever other zett tools read.
DEFAULT_MCP_CONFIG = Path.home() / ".zettcode" / "mcp.json"

#: Where the just-in-time harness keeps the tools a model wrote, one folder per session. Beside the sessions, not in
#: them: it is the model's own code, and clearing or moving the session store should not take it along.
DEFAULT_HARNESS_DIR = Path.home() / ".zettcode" / "harness"

#: What the background release check leaves behind: the newest version it saw
#: and the version the reader asked not to hear about again.
DEFAULT_UPDATE_FILE = Path.home() / ".zettcode" / "update.json"

#: Where the reader's own palettes live: one ``<name>.toml`` each, picked by name with ``/theme <name>``.
DEFAULT_THEMES_DIR = Path.home() / ".zettcode" / "themes"

#: The one palette file that is laid over whatever theme is in force.
DEFAULT_THEME_FILE = Path.home() / ".zettcode" / "theme.toml"

#: Where tiktoken keeps the vocabulary it downloads once. Deliberately not the
#: OS temp directory, which is cleaned whenever the system feels like it: a purge
#: turns the next token count into a 1.7 MB download, and `/context` waits behind
#: it. Under this program's own directory the fetch happens once.
DEFAULT_TOKENIZER_CACHE = Path.home() / ".zettcode" / "cache" / "tiktoken"

#: Anything written to stderr while the TUI owns the screen is kept here: a
#: child process — an MCP server announcing itself, say — cannot know that the
#: frame is the interface, and the renderer only repaints what it changed.
DEFAULT_LOG = Path.home() / ".zettcode" / "log" / "tui.log"

#: The commands typed in the ``/bash`` panel, one per line, so they are there next time.
DEFAULT_COMMAND_HISTORY = Path.home() / ".zettcode" / "command_history"


def config_path(path: str | Path | None = None) -> Path:
    """Return the config file to read: an explicit path, ``$ZETTCODE_CONFIG``, or the default.

    Here rather than beside the settings it loads because the frame drawn before
    those settings are read needs to name the same file without importing them.
    """
    if path is not None:
        return Path(path).expanduser()
    override = os.getenv("ZETTCODE_CONFIG")
    return Path(override).expanduser() if override else CONFIG_FILE


def check_config_path(path: str | Path | None = None) -> Path:
    """Return the config path, refusing one that exists and is not a file.

    A path that exists and is not a file — a directory from ``ZETTCODE_CONFIG=.``, a FIFO — is a configuration
    nobody can read, and it is not the fresh machine either: the terminal would start as if nothing were set up
    and then fail every setting on that path. So is a link whose target is gone, which is not a file for the same
    reason and would be replaced by the write rather than followed. A path with nothing at it is the fresh machine
    and is answered with the path as it is.

    Here, beside :func:`config_path`, because the command line asks this before it takes the terminal and before
    the settings module may be imported at all.

    Args:
        path: The path to check; ``$ZETTCODE_CONFIG`` or ``~/.zettcode/config.toml`` by default.

    Raises:
        ValueError: The path exists (or is a link) and is not a file.
    """
    source = config_path(path)
    if not source.is_file() and (source.exists() or source.is_symlink()):
        raise ValueError(f"{source} is not a file, so there is nothing to read there")
    return source


def resume_command(session_id: str, workspace: Path) -> str:
    """Return the command that reopens one stored session from anywhere.

    It is written down once because two places say it: the line printed on the way
    out, and the line a fork leaves in the conversation. The workspace is part of it
    because the store is keyed by workspace — the same id means nothing in another
    checkout — and it is quoted, because a path may hold a space.
    """
    return f"zettcode resume {shlex.quote(session_id)} --workspace {shlex.quote(str(workspace))}"
