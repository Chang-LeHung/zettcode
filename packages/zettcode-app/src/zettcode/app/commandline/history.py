"""The commands the reader has typed before, read from the shells that kept them.

Each shell writes its history in a format of its own: bash a line per command, zsh a line per command with a time
stamp in front and a backslash to continue a long one, fish a small YAML-like list, PowerShell a line per command
in a file under the profile. :class:`HistorySource` is the one thing the rest of the program knows about them: a
source says where its file may be and how to read it, and a subclass is the answer for one shell. Adding another
shell is adding a class and a name in :data:`SOURCES`.

:class:`CommandHistory` puts them in order for one reader: the shell they use most, last, so that it is what Up
reaches first, and the commands typed in ZettCode's own panel after all of them, in a file of its own.
"""

from __future__ import annotations

import os
import re
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from pathlib import Path

#: Commands kept when everything is merged; the oldest are dropped.
LIMIT = 5000

#: The most of a history file that is read: its tail, which is where the commands that matter are. A history
#: that has grown to hundreds of megabytes must not make the panel wait.
TAIL_BYTES = 4 * 1024 * 1024

#: The time stamp zsh writes in front of a command when extended history is on: ``: 1690000000:0;``.
ZSH_STAMP = re.compile(r"^: \d+:\d+;")

#: The two escapes in the file ZettCode keeps for itself.
PLAIN_ESCAPE = re.compile(r"\\([\\n])")


class HistorySource(ABC):
    """One shell's history: where it keeps it and how it is written.

    Subclass it with the file names and the parser; the reading, the choice of file and the tolerance for
    a file that is missing, unreadable or in another encoding are shared.

    Attributes:
        name: The shell's name, which is also what ``$SHELL`` ends in.
    """

    name = ""

    @abstractmethod
    def paths(self, home: Path, env: Mapping[str, str]) -> Iterable[Path]:
        """Return the places the history may be, most likely first."""

    @abstractmethod
    def parse(self, text: str) -> Iterator[str]:
        """Yield the commands in the file's text, oldest first."""

    def decode(self, raw: bytes) -> str:
        """Return the file's bytes as text; a byte that is not UTF-8 is replaced, not refused.

        A history written by a shell in another locale is still worth the commands that survive.
        """
        return raw.decode("utf-8", errors="replace")

    def load(self, home: Path | None = None, env: Mapping[str, str] | None = None) -> list[str]:
        """Return the commands in the first history file that can be read; empty when there is none."""
        home = Path.home() if home is None else home
        env = os.environ if env is None else env
        for path in self.paths(home, env):
            raw = read_tail(path)
            if raw is not None:
                return [command for command in self.parse(self.decode(raw)) if command.strip()]
        return []


def read_tail(path: Path) -> bytes | None:
    """Return the last :data:`TAIL_BYTES` of a file, or ``None`` when it cannot be read."""
    try:
        with path.open("rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            cut = size > TAIL_BYTES
            handle.seek(max(0, size - TAIL_BYTES))
            raw = handle.read()
    except OSError:
        return None
    if cut:
        # The first line of a tail is usually half of one.
        raw = raw.partition(b"\n")[2]
    return raw


class BashHistory(HistorySource):
    """bash: one command per line; a line starting with ``#`` and digits is a time stamp, not a command."""

    name = "bash"

    def paths(self, home: Path, env: Mapping[str, str]) -> Iterable[Path]:
        """Return ``$HISTFILE`` and ``~/.bash_history``."""
        if env.get("HISTFILE"):
            yield Path(env["HISTFILE"]).expanduser()
        yield home / ".bash_history"

    def parse(self, text: str) -> Iterator[str]:
        """Yield each line that is not a time stamp."""
        for line in text.splitlines():
            if line.startswith("#") and line[1:].isdigit():
                continue
            yield line.strip()


def unmetafy(raw: bytes) -> bytes:
    """Undo zsh's escaping: a byte of 0x83 means "the next byte, xor 0x20" (zsh marks its own control bytes so)."""
    if b"\x83" not in raw:
        return raw
    out = bytearray()
    following = iter(raw)
    for byte in following:
        out.append(next(following, 0) ^ 0x20 if byte == 0x83 else byte)
    return bytes(out)


class ZshHistory(HistorySource):
    """zsh: ``: <time>:<seconds>;<command>`` with extended history on, a bare command otherwise.

    A command that ran over several lines is written with a backslash at the end of each but the last, and
    zsh escapes some bytes of non-ASCII text, which :func:`unmetafy` takes back.
    """

    name = "zsh"

    def paths(self, home: Path, env: Mapping[str, str]) -> Iterable[Path]:
        """Return ``$HISTFILE``, then ``.zsh_history`` in ``$ZDOTDIR`` and in the home directory."""
        if env.get("HISTFILE"):
            yield Path(env["HISTFILE"]).expanduser()
        if env.get("ZDOTDIR"):
            yield Path(env["ZDOTDIR"]).expanduser() / ".zsh_history"
        yield home / ".zsh_history"

    def decode(self, raw: bytes) -> str:
        """Take back zsh's escaping before reading the bytes as text."""
        return super().decode(unmetafy(raw))

    def parse(self, text: str) -> Iterator[str]:
        """Yield each command, joining the lines of one that continues."""
        pending: list[str] = []
        for line in text.splitlines():
            if not pending:
                line = ZSH_STAMP.sub("", line, count=1)
            if line.endswith("\\"):
                pending.append(line[:-1])
                continue
            pending.append(line)
            yield "\n".join(pending).strip()
            pending = []
        if pending:
            yield "\n".join(pending).strip()


class FishHistory(HistorySource):
    """fish: a list of ``- cmd: <command>`` entries, each followed by indented ``when:`` and ``paths:`` lines.

    Inside a command fish writes a backslash as ``\\\\`` and a newline as ``\\n``.
    """

    name = "fish"

    def paths(self, home: Path, env: Mapping[str, str]) -> Iterable[Path]:
        """Return fish's history under ``$XDG_DATA_HOME``, then under ``~/.local/share``."""
        if env.get("XDG_DATA_HOME"):
            yield Path(env["XDG_DATA_HOME"]).expanduser() / "fish" / "fish_history"
        yield home / ".local" / "share" / "fish" / "fish_history"

    def parse(self, text: str) -> Iterator[str]:
        """Yield the ``cmd`` of every entry."""
        for line in text.splitlines():
            if line.startswith("- cmd: "):
                yield self._unescape(line[len("- cmd: ") :]).strip()

    @staticmethod
    def _unescape(value: str) -> str:
        out: list[str] = []
        index = 0
        while index < len(value):
            character = value[index]
            if character == "\\" and index + 1 < len(value):
                following = value[index + 1]
                if following in ("\\", "n"):
                    out.append("\n" if following == "n" else "\\")
                    index += 2
                    continue
            out.append(character)
            index += 1
        return "".join(out)


class PowerShellHistory(HistorySource):
    """PowerShell: the PSReadLine file, one command per line (a backtick continues a long one)."""

    name = "pwsh"

    def paths(self, home: Path, env: Mapping[str, str]) -> Iterable[Path]:
        """Return the PSReadLine history under ``%APPDATA%`` on Windows and under the data directory elsewhere."""
        if env.get("APPDATA"):
            yield (
                Path(env["APPDATA"]) / "Microsoft" / "Windows" / "PowerShell" / "PSReadLine" / "ConsoleHost_history.txt"
            )
        data = Path(env["XDG_DATA_HOME"]).expanduser() if env.get("XDG_DATA_HOME") else home / ".local" / "share"
        yield data / "powershell" / "PSReadLine" / "ConsoleHost_history.txt"

    def parse(self, text: str) -> Iterator[str]:
        """Yield each command."""
        pending = ""
        for line in text.splitlines():
            if line.endswith("`"):
                pending += line[:-1] + "\n"
                continue
            yield (pending + line).strip()
            pending = ""
        if pending:
            yield pending.strip()


class PlainHistory(HistorySource):
    """The file ZettCode keeps for itself: one command per line, appended to as they are run."""

    name = "zettcode"

    def __init__(self, path: Path) -> None:
        self.path = path

    def paths(self, home: Path, env: Mapping[str, str]) -> Iterable[Path]:
        """Return the one file."""
        yield self.path

    def parse(self, text: str) -> Iterator[str]:
        """Yield each line; a command that had a newline in it was written with it escaped."""
        for line in text.splitlines():
            yield PLAIN_ESCAPE.sub(lambda found: "\n" if found.group(1) == "n" else "\\", line).strip()


#: The shells ZettCode can read, in the order they are tried when ``$SHELL`` names none of them.
SOURCES: tuple[HistorySource, ...] = (BashHistory(), ZshHistory(), FishHistory(), PowerShellHistory())


def preferred(env: Mapping[str, str], platform: str = sys.platform) -> str:
    """Return the name of the shell the reader most likely uses: what ``$SHELL`` ends in, else the platform's own."""
    shell = Path(env.get("SHELL", "")).name.lower().removesuffix(".exe")
    if shell == "pwsh" or shell == "powershell":
        return PowerShellHistory.name
    if shell in {source.name for source in SOURCES}:
        return shell
    return PowerShellHistory.name if platform == "win32" else BashHistory.name


class CommandHistory:
    """Every command the reader has typed that is worth offering again, oldest first.

    The histories of the shells are read and laid end to end with the one the reader uses *last*, then the
    commands typed in ZettCode's panel; a command that appears twice is kept once, at its newest place, so Up
    reaches each command once and the freshest first.

    Args:
        own: The file the commands typed in the panel are appended to.
        sources: The shells to read; every shell ZettCode knows by default.
        home: The home directory; the real one by default.
        env: The environment; the real one by default.
        platform: ``sys.platform``, for choosing the reader's shell.
    """

    def __init__(
        self,
        own: Path,
        *,
        sources: Sequence[HistorySource] = SOURCES,
        home: Path | None = None,
        env: Mapping[str, str] | None = None,
        platform: str = sys.platform,
    ) -> None:
        self.own = own
        self.sources = tuple(sources)
        self.home = Path.home() if home is None else home
        self.env = os.environ if env is None else env
        self.platform = platform

    def load(self) -> list[str]:
        """Return the merged history, oldest first."""
        favourite = preferred(self.env, self.platform)
        ordered = sorted(self.sources, key=lambda source: source.name == favourite)
        merged: list[str] = []
        for source in ordered:
            merged.extend(source.load(self.home, self.env))
        merged.extend(PlainHistory(self.own).load(self.home, self.env))
        kept: dict[str, None] = {}
        for command in merged:
            kept.pop(command, None)
            kept[command] = None
        return list(kept)[-LIMIT:]

    def record(self, command: str) -> None:
        """Append a command to ZettCode's own file; a file that cannot be written is not an error."""
        line = command.replace("\\", "\\\\").replace("\n", "\\n")
        try:
            self.own.parent.mkdir(parents=True, exist_ok=True)
            with self.own.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
