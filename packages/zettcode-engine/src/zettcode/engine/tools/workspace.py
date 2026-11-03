"""The file system as the tools see it: paths taken from the working directory, text read in ranges, written whole."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .output import MAX_OUTPUT_BYTES, utf8_prefix

#: The largest text file a tool reads whole, writes, or searches.
MAX_FILE_BYTES = 2 * 1024 * 1024

#: How much of a line is read at a time, so one enormous line cannot use the memory of a whole file.
FRAGMENT_CHARACTERS = 4096


# -- where a path points ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Located:
    """A path a tool was asked about, resolved against the directory the process is in.

    Attributes:
        given: The path as the model wrote it, which is what an error message quotes back.
        directory: The working directory, resolved.
        path: Where ``given`` points: absolute paths and ``~`` are taken as they are, anything else is relative to
            ``directory``; symbolic links are followed.
    """

    given: str
    directory: Path
    path: Path

    @classmethod
    def of(cls, given: str) -> Located:
        """Resolve ``given`` against the working directory."""
        directory = Path.cwd().resolve()
        candidate = Path(given).expanduser()
        target = candidate.resolve() if candidate.is_absolute() else (directory / candidate).resolve()
        return cls(given, directory, target)

    @property
    def shown(self) -> str:
        """Return the path as a result should name it: relative to the working directory for a relative ``given``."""
        if Path(self.given).expanduser().is_absolute():
            return self.path.as_posix()
        return Path(os.path.relpath(self.path, self.directory)).as_posix()

    def require_file(self) -> Path:
        """Return the path, which has to be an existing regular file.

        Raises:
            ValueError: With the path as given, when there is no such file.
        """
        if not self.path.is_file():
            raise ValueError(f"File does not exist: {self.given}")
        return self.path


@dataclass(frozen=True, slots=True)
class Pattern:
    """A glob pattern, split into the directory to search from and the expression to match below it.

    Attributes:
        root: Where the search starts: the filesystem root for an absolute pattern, else the working directory.
        expression: What is matched below ``root``, as ``Path.glob`` takes it.
        absolute: Whether matches are reported as absolute paths (the pattern was one) or relative to ``directory``.
        directory: The working directory, resolved.
    """

    root: Path
    expression: str
    absolute: bool
    directory: Path

    @classmethod
    def parse(cls, pattern: str) -> Pattern:
        """Split ``pattern`` the way ``glob`` and ``grep`` take it."""
        directory = Path.cwd().resolve()
        candidate = Path(pattern).expanduser()
        if candidate.is_absolute():
            root = Path(candidate.anchor)
            return cls(root, candidate.relative_to(root).as_posix(), True, directory)
        return cls(directory, candidate.as_posix(), False, directory)

    def matches(self) -> list[Path]:
        """Return everything the pattern matches, in sorted order."""
        return sorted(self.root.glob(self.expression))

    def render(self, match: Path) -> str:
        """Return a match in the style the pattern was written in."""
        if self.absolute:
            return match.absolute().as_posix()
        return Path(os.path.relpath(match.absolute(), self.directory)).as_posix()


# -- reading and writing text ------------------------------------------------------------------------------------


def read_text(path: Path) -> str:
    """Return a whole text file.

    Raises:
        ValueError: When the file is over :data:`MAX_FILE_BYTES`.
        UnicodeDecodeError: When it is not UTF-8.
    """
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"File exceeds the {MAX_FILE_BYTES}-byte limit")
    return path.read_text(encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    """Replace a file with ``content`` atomically: it is written beside the file and renamed over it.

    A reader of the file sees the old text or the new text, never half of it, and a failed write leaves the old
    text and no stray file behind. Missing parent directories are made.

    Raises:
        ValueError: When the text is over :data:`MAX_FILE_BYTES`.
    """
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_FILE_BYTES:
        raise ValueError(f"Content exceeds the {MAX_FILE_BYTES}-byte limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as handle:
            handle.write(encoded)
            temporary = Path(handle.name)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_lines(located: Located, offset: int, limit: int) -> str:
    """Return ``limit`` lines of a UTF-8 file from line ``offset``, with a note on how to continue when more remains.

    The result is held to :data:`MAX_OUTPUT_BYTES`. A line longer than that is cut, and the note says so: the
    reader has no column to resume from, because one 2 MB line is not what the tool is for — the shell reads it.
    A cut inside an ordinary line is not that: the budget was used up before it, and the note then names the line
    to start again from. The file is read a fragment at a time and never whole.

    Args:
        located: The file; it has to exist.
        offset: One-based first line.
        limit: Most lines to return.

    Raises:
        ValueError: When the file is not UTF-8 text.
    """
    selected: list[str] = []
    number, used, line_start = 1, 0, 0
    next_offset: int | None = None
    cut_at: int | None = None
    oversized = False
    try:
        with located.path.open(encoding="utf-8") as source:
            while fragment := source.readline(FRAGMENT_CHARACTERS):
                if number >= offset + limit:
                    next_offset = number
                    break
                if number >= offset:
                    part = utf8_prefix(fragment, MAX_OUTPUT_BYTES - used)
                    selected.append(part)
                    used += len(part.encode("utf-8"))
                    if len(part) < len(fragment):
                        # Whether this line could fill a call of its own decides what the note says, and only
                        # what is left of the line knows that. Reading on is bounded by one budget.
                        cut_at = number
                        oversized = _line_longer_than_budget(
                            source, used - line_start, fragment[len(part) :], MAX_OUTPUT_BYTES
                        )
                        break
                if fragment.endswith("\n"):
                    number, line_start = number + 1, used
    except UnicodeDecodeError as error:
        raise ValueError(f"File is not UTF-8 text: {located.given}") from error
    content = "".join(selected)
    if cut_at is not None and oversized:
        content += (
            f"\n... [line truncated; line {cut_at} is longer than the {MAX_OUTPUT_BYTES // 1024} KB output limit "
            "and was cut here; read it with the shell]"
        )
    elif cut_at is not None:
        content += f"\n... [output truncated; continue with offset={cut_at}]"
    elif next_offset is not None:
        content += f"\n... [more lines; continue with offset={next_offset}]"
    return content


def _line_longer_than_budget(source: TextIO, seen: int, tail: str, budget: int) -> bool:
    """Return whether the line continues for more than ``budget`` bytes in all.

    Args:
        source: The file, positioned just after the fragment the cut happened in.
        seen: How many bytes of this line are already in the result.
        tail: The rest of the fragment the cut happened in, which is not in the result yet.
        budget: What one result may carry.

    The line is read on to its end, but never past ``budget`` bytes: past that point the answer is known, and
    the rest of a runaway line is what the shell is for.
    """
    fragment = tail
    while True:
        seen += len(fragment.encode("utf-8"))
        if seen > budget:
            return True
        if not fragment or fragment.endswith("\n"):
            return False
        fragment = source.readline(FRAGMENT_CHARACTERS)


# -- editing ------------------------------------------------------------------------------------------------------


def apply_edit(content: str, old_string: str, new_string: str, replace_all: bool = False) -> tuple[str, int]:
    """Replace ``old_string`` in ``content`` once, or everywhere when ``replace_all`` says so.

    By default ``old_string`` must appear exactly once in the text, so include the surrounding characters that
    make it unique; ``new_string`` may be empty, which deletes the match.

    Returns:
        The new text and how many occurrences were replaced.

    Raises:
        ValueError: Saying what to do, when the old text is not found or is not unique. Nothing has been written
            by then, since the caller writes once, after the replacement has passed.
    """
    matches = content.count(old_string)
    if matches == 0:
        raise ValueError(f"Text to replace was not found: {_excerpt(old_string)}. {_miss_hint(content, old_string)}")
    if matches > 1 and not replace_all:
        raise ValueError(
            f"Text to replace is not unique; found {matches} matches "
            f"(include more surrounding lines, or set replace_all to change every one): {_excerpt(old_string)}"
        )
    updated = content.replace(old_string, new_string, -1 if replace_all else 1)
    return updated, matches if replace_all else 1


def _miss_hint(content: str, old_string: str) -> str:
    """Say why an exact match failed, so the model fixes ``old_string`` instead of leaving the tool."""
    if " ".join(content.split()).count(" ".join(old_string.split())) > 0:
        return (
            "A match exists that differs only in whitespace or indentation; "
            "read the file again and copy the lines exactly. Nothing was written."
        )
    return "Read the file again and copy old_string from its current content. Nothing was written."


def _excerpt(value: str, *, limit: int = 60) -> str:
    """Shorten one matched snippet for an error message."""
    collapsed = " ".join(value.split())
    return repr(f"{collapsed[:limit]}\u2026" if len(collapsed) > limit else collapsed)


__all__ = [
    "FRAGMENT_CHARACTERS",
    "MAX_FILE_BYTES",
    "Located",
    "Pattern",
    "apply_edit",
    "read_lines",
    "read_text",
    "write_text",
]
