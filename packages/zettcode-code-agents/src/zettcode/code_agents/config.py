"""The settings of the Codex and Claude Code agents, which belong to this plugin and not to the gateway.

The gateway only starts an agent. Where it works, how far it is trusted and which command it runs are written in one
JSON file, ``~/.zettcode/code-agents/config.json`` (``$ZETTCODE_CODE_AGENTS_CONFIG`` names another), and the file is
read again when each message arrives, so an edit applies to the next message of every agent that is already running::

    {
      "cwd": "~/work",
      "permission": "full",
      "timeout": 900,
      "codex": {"cwd": "~/work/api", "permission": "workspace"},
      "claude": {"bin": "/opt/bin/claude"}
    }

A key inside ``"codex"`` or ``"claude"`` wins over the same key at the top; that wins over the environment variable
this plugin read before there was a file; that wins over the default. ``bin``, ``args`` and ``resume_args`` belong to
one tool and have no top-level form.

``permission`` is how far the agent is trusted, and the plugin turns it into the arguments each CLI takes:

* ``full`` (the default): the agent may do anything the user may, with nothing asked.
* ``workspace``: it may write inside its folder; the rest of the machine is read-only or closed.
* ``read``: it may look and not change.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The trust levels, safest last. Each tool maps every one of them to its own arguments.
PERMISSIONS = ("full", "workspace", "read")

#: What an agent is trusted with when nothing says otherwise: it runs on its own, and nobody is there to answer a prompt.
DEFAULT_PERMISSION = "full"

#: How long one CLI turn may take before it is stopped.
TIMEOUT = 900.0


class ConfigError(RuntimeError):
    """The settings cannot be used. The sentence names the file and the key, so it can be shown to the person as is."""


def state_directory() -> Path:
    """Return where the CLI session ids and the settings are kept."""
    return Path(os.environ.get("ZETTCODE_CODE_AGENTS_DIR", str(Path.home() / ".zettcode" / "code-agents"))).expanduser()


def work_directory() -> Path:
    """Return the directory the CLI runs in when the settings do not name one."""
    return Path(os.environ.get("ZETTCODE_CODE_AGENTS_CWD", str(Path.cwd()))).expanduser()


def config_path() -> Path:
    """Return the settings file."""
    return Path(os.environ.get("ZETTCODE_CODE_AGENTS_CONFIG", str(state_directory() / "config.json"))).expanduser()


@dataclass(frozen=True, slots=True)
class Tool:
    """What is known about one CLI before any settings: its name, its default command and what each trust level adds."""

    name: str
    #: The prefix of the environment variables that set this tool's command (``ZETTCODE_CODEX`` for ``_BIN``...).
    env: str
    binary: str
    args: str
    resume_args: str
    #: The arguments each permission adds to a new conversation, and to a resumed one (a CLI may differ).
    flags: Mapping[str, tuple[str, ...]]
    resume_flags: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class Settings:
    """Everything one CLI turn runs with, resolved from the file, the environment and the defaults at that moment."""

    cwd: Path
    permission: str
    timeout: float
    binary: str
    args: str
    resume_args: str


def read_config() -> dict[str, Any]:
    """Read the settings file now. A missing or empty file is no settings; one that cannot be used is a ConfigError."""
    path = config_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as error:
        raise ConfigError(f"{path} cannot be read: {error.strerror or error}") from error
    if not text.strip():
        return {}
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ConfigError(f"{path} is not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must hold one JSON object")
    return data


def _text(key: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f'"{key}" in {config_path()} must be a non-empty string')
    return value


def resolve(tool: Tool, *, timeout: float = TIMEOUT) -> Settings:
    """Return the settings of one tool as they are now.

    Args:
        tool: The CLI.
        timeout: The timeout when neither the file nor the tool's section sets one.

    Raises:
        ConfigError: The file cannot be read or parsed, a value has the wrong type, ``permission`` is not a level, or
            ``cwd`` is not a folder.
    """
    data = read_config()
    section = data.get(tool.name, {})
    if not isinstance(section, dict):
        raise ConfigError(f'"{tool.name}" in {config_path()} must be an object')

    def value(key: str, fallback: object, *, shared: bool = True) -> object:
        if key in section:
            return section[key]
        if shared and key in data:
            return data[key]
        return fallback

    folder = Path(_text("cwd", value("cwd", str(work_directory())))).expanduser().resolve()
    if not folder.is_dir():
        raise ConfigError(f'the folder {folder} ("cwd" in {config_path()}) does not exist')

    permission = _text("permission", value("permission", DEFAULT_PERMISSION))
    if permission not in tool.flags:
        raise ConfigError(f'"permission" in {config_path()} is full, workspace or read, not {permission!r}')

    limit = value("timeout", timeout)
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or limit <= 0:
        raise ConfigError(f'"timeout" in {config_path()} must be a positive number of seconds')

    return Settings(
        cwd=folder,
        permission=permission,
        timeout=float(limit),
        binary=_text("bin", value("bin", os.environ.get(f"{tool.env}_BIN", tool.binary), shared=False)),
        args=_text("args", value("args", os.environ.get(f"{tool.env}_ARGS", tool.args), shared=False)),
        resume_args=_text(
            "resume_args",
            value("resume_args", os.environ.get(f"{tool.env}_RESUME_ARGS", tool.resume_args), shared=False),
        ),
    )
