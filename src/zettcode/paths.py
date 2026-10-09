"""Where ZettCode keeps its own files.

Constants only, and deliberately importable without the settings module: the
shell takes the terminal and points its diagnostics at the log before it has
read the config, so the paths cannot live behind that import.
"""

from __future__ import annotations

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

#: Anything written to stderr while the TUI owns the screen is kept here: a
#: child process — an MCP server announcing itself, say — cannot know that the
#: frame is the interface, and the renderer only repaints what it changed.
DEFAULT_LOG = Path.home() / ".zettcode" / "log" / "tui.log"
