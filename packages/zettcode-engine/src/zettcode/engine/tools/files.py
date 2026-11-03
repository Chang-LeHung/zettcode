"""The file tools: read, search, write and edit.

Each tool is a typed function whose signature is its input schema and whose docstring is what the model is told:
the first paragraph is the description, ``Args`` the parameters, ``Snippet`` the call shapes, ``Guidelines`` the rules
that go in the prompt. ``zett_agent.tools.base.tool`` turns one into an :class:`~zett_agent.tools.base.AgentTool`;
the work is done here, in this repository, and by nothing else.

There are two readers and no more. ``read`` returns UTF-8 text as a line range and a PNG, JPEG, GIF or WebP file as an
image, so one tool covers both. ``read_file`` is the same reader without the pictures, for a model that cannot take
an image (see :class:`~zettcode.engine.extensions.capabilities.ModelCapabilities`, which swaps one for the other).
There is no ``view_image``, because ``read`` already shows a picture, and no ``delete_file``: removing a file is a
shell command and goes through the shell's permission like any other, with no second path around it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from pydantic import Field
from zett_agent.messages import ImageBytesSource, ImageContent, TextContent
from zett_agent.tools.base import tool

from .images import MAX_IMAGE_BYTES, SIGNATURE_BYTES, image_media_type
from .output import MAX_MATCH_BYTES, MAX_OUTPUT_BYTES, utf8_prefix
from .workspace import (
    MAX_FILE_BYTES,
    Located,
    Pattern,
    apply_edit,
    read_lines,
    read_text,
    write_text,
)

# The parameter types, named once so that the tools that share one agree on its limits and its schema.
FilePath = Annotated[str, Field(min_length=1)]
Expression = Annotated[str, Field(min_length=1)]
Offset = Annotated[int, Field(ge=1)]
Limit = Annotated[int, Field(ge=1, le=2_000)]
MaxResults = Annotated[int, Field(ge=1, le=5_000)]
OldString = Annotated[str, Field(min_length=1)]

#: What a reader hands back: text, or a text line and the picture it describes.
ReadResult = str | list[TextContent | ImageContent]


def _image_type_of(path: Path) -> str | None:
    """Return the media type of a local image file, or ``None`` when it is not a PNG, JPEG, GIF or WebP."""
    with path.open("rb") as source:
        return image_media_type(source.read(SIGNATURE_BYTES))


@tool
def read(file_path: FilePath, offset: Offset = 1, limit: Limit = 200) -> ReadResult:
    """Read a local file: UTF-8 text as a line range, or a PNG, JPEG, GIF, or WebP image as an image.

    Args:
        file_path: Absolute path or a path relative to the current working directory.
        offset: One-based line number to start reading from; ignored for images.
        limit: Maximum number of lines to return; ignored for images.

    Snippet:
        read(file_path="docs/diagram.png")

    Guidelines:
        - Use for any local file when you do not know whether it is text or an image.
        - A text file comes back as a line range; use line ranges for large files.
        - A trailing hint says how to go on: the next offset when more lines remain, or the shell when one line is
          longer than the output limit.
        - An image comes back as an image with a one-line description; the range arguments do not apply to it.
        - PDF and SVG files are not supported.
    """
    located = Located.of(file_path)
    target = located.require_file()
    media_type = _image_type_of(target)
    if media_type is None:
        return read_lines(located, offset, limit)
    size = target.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds the {MAX_IMAGE_BYTES}-byte limit: {file_path}")
    return [
        TextContent(text=f"Image {target.name}: {media_type}, {size} bytes"),
        ImageContent(source=ImageBytesSource(data=target.read_bytes(), media_type=media_type), alt_text=target.name),
    ]


@tool
def read_file(file_path: FilePath, offset: Offset = 1, limit: Limit = 200) -> str:
    """Read a line range from a UTF-8 text file.

    Args:
        file_path: Absolute path or a path relative to the current working directory.
        offset: One-based line number to start reading from.
        limit: Maximum number of lines to return.

    Snippet:
        read_file(file_path="src/app.py", offset=1, limit=200)

    Guidelines:
        - Use line ranges for large files.
        - Inspect the current content before editing a file.
        - A trailing hint says how to go on: the next offset when more lines remain, or the shell when one line is
          longer than the output limit.
    """
    located = Located.of(file_path)
    located.require_file()
    return read_lines(located, offset, limit)


@tool
def glob(pattern: Expression, max_results: MaxResults = 200) -> str:
    """Find paths matching a relative or absolute glob pattern.

    Args:
        pattern: Glob pattern such as **/*.py, ../tests/*.py, or /work/src/**/*.py.
        max_results: Maximum number of sorted paths to return.

    Snippet:
        glob(pattern="src/**/*.py", max_results=200)

    Guidelines:
        - Use glob to discover files before reading or searching them.
        - Narrow the pattern when the result is truncated.
        - The result lists one path per line and is empty when nothing matches.
    """
    spec = Pattern.parse(pattern)
    paths: list[str] = []
    used = 0
    truncated = False
    for match in spec.matches():
        rendered = spec.render(match)
        size = len(rendered.encode("utf-8"))
        if len(paths) == max_results or used + size > MAX_OUTPUT_BYTES:
            truncated = True
            break
        paths.append(rendered)
        used += size
    result = "\n".join(paths)
    if truncated:
        result += "\n... [truncated; narrow the pattern or increase max_results]"
    return result


@tool
def grep(
    pattern: Expression,
    file_pattern: Expression = "**/*",
    case_sensitive: bool = True,
    max_results: MaxResults = 200,
) -> str:
    """Search UTF-8 text files selected by a relative or absolute glob pattern.

    Args:
        pattern: Python regular expression to search for on each line.
        file_pattern: Relative or absolute glob selecting files to search.
        case_sensitive: Whether letter case must match exactly.
        max_results: Maximum number of matching lines to return.

    Snippet:
        grep(pattern="class\\s+Agent", file_pattern="src/**/*.py", max_results=200)

    Guidelines:
        - Use a narrow file_pattern to avoid scanning unrelated files.
        - Escape regular-expression characters when searching for literal text.
        - Each match is one path:line:text line; use the read tool for surrounding context.
    """
    spec = Pattern.parse(file_pattern)
    try:
        expression = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
    except re.error as error:
        raise ValueError(f"Invalid regular expression: {error}") from error
    lines: list[str] = []
    used = 0
    truncated = False
    for candidate in spec.matches():
        if not candidate.is_file() or candidate.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            content = candidate.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        shown = spec.render(candidate)
        for number, line in enumerate(content.splitlines(), start=1):
            found = expression.search(line)
            if found is None:
                continue
            if len(lines) == max_results:
                truncated = True
                break
            first = max(0, found.start() - 100) if len(line.encode("utf-8")) > MAX_MATCH_BYTES else 0
            rendered = f"{shown}:{number}: {utf8_prefix(line[first:], MAX_MATCH_BYTES)}"
            size = len(rendered.encode("utf-8"))
            if used + size > MAX_OUTPUT_BYTES:
                truncated = True
                break
            lines.append(rendered)
            used += size
        if truncated:
            break
    result = "\n".join(lines)
    if truncated:
        result += "\n... [truncated; narrow the search or increase max_results]"
    return result


@tool
def write_file(file_path: FilePath, content: str, overwrite: bool = True) -> str:
    """Atomically write a UTF-8 text file.

    Args:
        file_path: Absolute path or a path relative to the current working directory.
        content: Complete UTF-8 text to write.
        overwrite: Whether an existing file may be replaced.

    Snippet:
        write_file(file_path="notes/plan.md", content="# Plan\\n")

    Guidelines:
        - Use for new files or intentional full-file replacement.
        - Prefer edit for a small change to an existing file.
    """
    located = Located.of(file_path)
    exists = located.path.exists()
    if exists and not located.path.is_file():
        raise ValueError(f"Path is not a file: {file_path}")
    if exists and not overwrite:
        raise ValueError(f"File already exists: {file_path}")
    write_text(located.path, content)
    return f"{'Wrote' if exists else 'Created'} {located.shown}"


@tool
def edit(file_path: FilePath, old_string: OldString, new_string: str, replace_all: bool = False) -> str:
    """Edit an existing UTF-8 file by replacing exact text; always use this tool to modify a file.

    Args:
        file_path: Absolute path or a path relative to the current working directory.
        old_string: The exact text to replace, copied from the file as it is now.
        new_string: The text to put in its place; an empty string deletes the match.
        replace_all: Replace every occurrence of old_string instead of insisting it appears once.

    Snippet:
        edit(file_path="notes/plan.md", old_string="Draft", new_string="Final")
        edit(file_path="notes/plan.md", old_string="Total", new_string="Sum", replace_all=True)

    Guidelines:
        - Always use this tool when you need to modify an existing file, instead of sed, awk, perl -i, python -c, tee, or shell redirection. Reserve those for bulk or mechanical rewrites this tool cannot express, such as renaming a symbol across many files.
        - One change a call: call edit again for the next change, and nothing is written when the old text does not match.
        - Avoid sed, cat, and similar shell commands for reading or changing files unless it is necessary; inspect files with the read tool and change them with this tool.
        - Read the target lines first and copy old_string exactly: same indentation, quotes, and line breaks.
        - Make old_string unique by including a neighbouring line or two; set replace_all only when every occurrence must change.
        - When an edit fails, read the file again and retry with corrected old_string rather than switching to a shell command.
    """
    located = Located.of(file_path)
    updated, replacements = apply_edit(read_text(located.require_file()), old_string, new_string, replace_all)
    write_text(located.path, updated)
    return f"Replaced {replacements} occurrence{'s' if replacements != 1 else ''} in {located.shown}"


__all__ = ["edit", "glob", "grep", "read", "read_file", "write_file"]
