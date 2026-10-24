"""The file system as the tools see it: paths taken from the working directory, text read in ranges, written whole."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

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


def read_lines(located: Located, start_line: int, line_count: int, start_column: int) -> str:
    """Return ``line_count`` lines of a UTF-8 file from ``start_line``, with a note on how to continue when more remains.

    The result is held to :data:`MAX_OUTPUT_BYTES`. A line that does not fit is cut, and the note then gives the
    column to resume from (``start_column``), so a single huge line can still be read in pieces. The file is read
    a fragment at a time and never whole.

    Args:
        located: The file; it has to exist.
        start_line: One-based first line.
        line_count: Most lines to return.
        start_column: One-based character column on ``start_line``, to continue a cut line.

    Raises:
        ValueError: When the file is not UTF-8 text.
    """
    selected: list[str] = []
    line_number, column = 1, 1
    used = 0
    next_line: int | None = None
    next_column: int | None = None
    truncated = False
    try:
        with located.path.open(encoding="utf-8") as source:
            while fragment := source.readline(FRAGMENT_CHARACTERS):
                if line_number >= start_line and next_line is None:
                    offset = max(0, start_column - column) if line_number == start_line else 0
                    available = fragment[offset:]
                    if line_number >= start_line + line_count:
                        next_line = line_number
                    elif available:
                        part = utf8_prefix(available, MAX_OUTPUT_BYTES - used)
                        selected.append(part)
                        used += len(part.encode("utf-8"))
                        if len(part) < len(available):
                            next_line, next_column = line_number, column + offset + len(part)
                            truncated = True
                if fragment.endswith("\n"):
                    line_number, column = line_number + 1, 1
                else:
                    column += len(fragment)
    except UnicodeDecodeError as error:
        raise ValueError(f"File is not UTF-8 text: {located.given}") from error
    content = "".join(selected)
    if truncated:
        content += f"\n... [line truncated; continue with start_line={next_line}, start_column={next_column}]"
    elif next_line is not None:
        content += f"\n... [more lines; continue with start_line={next_line}]"
    return content


# -- editing ------------------------------------------------------------------------------------------------------


class FileEdit(BaseModel):
    """One exact-text edit applied to a file.

    By default ``old_text`` must appear exactly once in the current text, so include the surrounding characters
    that make it unique. Set ``replace_all`` when every occurrence should change. ``new_text`` may be empty to
    delete the matched text.
    """

    model_config = ConfigDict(extra="forbid")

    old_text: Annotated[str, Field(min_length=1, description="Exact text to find")]
    new_text: str = Field(default="", description="Replacement text; an empty value deletes the match")
    replace_all: bool = Field(default=False, description="Whether every exact match should be replaced")


def apply_edits(content: str, edits: Sequence[FileEdit]) -> tuple[str, int]:
    """Apply exact-text edits in order, each checked against the text the edits before it left.

    Returns:
        The new text and how many occurrences were replaced.

    Raises:
        ValueError: Saying what to do, when an edit's text is not found or is not unique. Nothing has been
            written by then, since the caller writes once, after every edit has passed.
    """
    replacements = 0
    for number, change in enumerate(edits, start=1):
        label = f"Edit {number} of {len(edits)}: " if len(edits) > 1 else ""
        matches = content.count(change.old_text)
        if matches == 0:
            raise ValueError(
                f"{label}Text to replace was not found: {_excerpt(change.old_text)}. "
                f"{_miss_hint(content, change.old_text)}"
            )
        if matches > 1 and not change.replace_all:
            raise ValueError(
                f"{label}Text to replace is not unique; found {matches} matches "
                f"(include more surrounding lines, or set replace_all to change every one): "
                f"{_excerpt(change.old_text)}"
            )
        content = content.replace(change.old_text, change.new_text, -1 if change.replace_all else 1)
        replacements += matches if change.replace_all else 1
    return content, replacements


def _miss_hint(content: str, old_text: str) -> str:
    """Say why an exact match failed, so the model fixes ``old_text`` instead of leaving the tool."""
    if " ".join(content.split()).count(" ".join(old_text.split())) > 0:
        return (
            "A match exists that differs only in whitespace or indentation; "
            "read the file again and copy the lines exactly. Nothing was written."
        )
    return "Read the file again and copy old_text from its current content. Nothing was written."


def _excerpt(value: str, *, limit: int = 60) -> str:
    """Shorten one matched snippet for an error message."""
    collapsed = " ".join(value.split())
    return repr(f"{collapsed[:limit]}\u2026" if len(collapsed) > limit else collapsed)


__all__ = [
    "FRAGMENT_CHARACTERS",
    "MAX_FILE_BYTES",
    "FileEdit",
    "Located",
    "Pattern",
    "apply_edits",
    "read_lines",
    "read_text",
    "write_text",
]
