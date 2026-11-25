"""Discover selectable literal aliases without executing SSH configuration directives."""

from __future__ import annotations

import glob
import shlex
from pathlib import Path

from .transport import HOST

MAX_FILES = 64
MAX_BYTES = 256 * 1024
MAX_ALIASES = 200


def host_aliases(config: Path | None = None) -> tuple[str, ...]:
    """Read literal Host aliases and bounded Includes; ignore wildcard/negated patterns and Match sections.

    Authentication and connection settings remain OpenSSH's responsibility. Match exec is never executed.
    """
    root = config if config is not None else Path.home() / ".ssh" / "config"
    aliases: dict[str, None] = {}
    visited: set[Path] = set()
    remaining = MAX_BYTES

    def read(path: Path, matching: bool = False) -> bool:
        nonlocal remaining
        try:
            path = path.expanduser().resolve()
            if path in visited or len(visited) >= MAX_FILES or remaining <= 0:
                return matching
            visited.add(path)
            with path.open("rb") as handle:
                data = handle.read(remaining + 1)
            if len(data) > remaining:
                remaining = 0
                return matching
            remaining -= len(data)
            lines = data.decode("utf-8").splitlines()
        except (OSError, UnicodeError, RuntimeError):
            return matching
        for line in lines:
            try:
                words = shlex.split(line, comments=True)
            except ValueError:
                continue
            if not words:
                continue
            key, _, inline = words[0].partition("=")
            args = ([inline] if inline else []) + words[1:]
            if args and args[0] == "=":
                args = args[1:]
            key = key.lower()
            if key == "match":
                matching = True
            elif key == "host":
                matching = False
                for alias in args:
                    if len(aliases) < MAX_ALIASES and len(alias) <= 255 and HOST.fullmatch(alias):
                        aliases.setdefault(alias, None)
            elif key == "include" and not matching:
                for expression in args:
                    candidate = Path(expression).expanduser()
                    if not candidate.is_absolute():
                        candidate = root.expanduser().parent / candidate
                    # Limit expansion as well as reads; never traverse an unbounded Include tree.
                    for index, included in enumerate(glob.iglob(str(candidate))):
                        if index >= MAX_FILES:
                            break
                        matching = read(Path(included), matching)
        return matching

    read(root)
    return tuple(aliases)
