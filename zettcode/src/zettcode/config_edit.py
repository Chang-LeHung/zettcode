"""Edit the ``[[models]]`` entries of the config file without disturbing the rest of it.

The file is the reader's: it has comments they wrote, tables this code has never heard of, and a
layout they chose. Rewriting it from parsed data would throw all of that away, so the edits here are
made on the *text* — one ``[[models]]`` block is added, replaced or removed — and everything outside
that block is left byte for byte as it was.

Because text editing is only safe when the text is what it looks like, every edit is checked before
it is written: the result must parse, must hold exactly the models the edit meant it to, and every
table other than ``models`` must be equal to what it was. A file that spells its models some other
way (an inline array, say) is refused rather than guessed at, and a refused or failed edit writes
nothing.
"""

from __future__ import annotations

import contextlib
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._compat import tomllib
from .config import MODEL_KEYS, ModelConfig, _read_models

#: A line that opens a table or an array of tables; the first thing on it, so a ``[`` inside a value
#: or a comment is not one.
_HEADER = re.compile(r"^\s*\[")
#: The line that opens one model.
_MODEL_HEADER = re.compile(r"^\s*\[\[\s*models\s*\]\]\s*(#.*)?$")

#: The order keys are written in, so a new entry reads the way the documentation shows one.
_KEY_ORDER = (
    "display_model",
    "model",
    "base_url",
    "token",
    "chat",
    "anthropic",
    "responses_api",
    "multimodal",
    "temperature",
    "context_window",
    "compact_percent",
    "reasoning_efforts",
)


class ConfigEditError(ValueError):
    """The file could not be edited safely; its message says why and nothing was written."""


def toml_string(value: str) -> str:
    """Return ``value`` as a TOML basic string, escaping what a basic string cannot hold."""
    out = ['"']
    for character in value:
        code = ord(character)
        if character == '"':
            out.append('\\"')
        elif character == "\\":
            out.append("\\\\")
        elif character == "\n":
            out.append("\\n")
        elif character == "\t":
            out.append("\\t")
        elif code < 0x20 or code == 0x7F:
            out.append(f"\\u{code:04x}")
        else:
            out.append(character)
    out.append('"')
    return "".join(out)


def _value(value: object) -> str:
    """Render one setting's value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)) and all(isinstance(item, str) for item in value):
        return "[" + ", ".join(toml_string(item) for item in value) + "]"
    raise ConfigEditError(f"cannot write a value of type {type(value).__name__}")


def render_entry(entry: Mapping[str, object]) -> str:
    """Return one ``[[models]]`` block for ``entry``, keys in the documented order.

    Args:
        entry: The keys of one model as they are written in the file.
    """
    unknown = sorted(set(entry) - MODEL_KEYS)
    if unknown:
        raise ConfigEditError(f"unknown model keys: {', '.join(unknown)}")
    lines = ["[[models]]"]
    for key in _KEY_ORDER:
        if key in entry:
            lines.append(f"{key} = {_value(entry[key])}")
    return "\n".join(lines) + "\n"


def entry_from_model(model: ModelConfig, *, token: str | None = None) -> dict[str, object]:
    """Return the file keys for ``model``, leaving out whatever is the default.

    Args:
        model: A validated model.
        token: What to write for the token; ``None`` writes the one the model holds.
    """
    from .config import DEFAULT_COMPACT_PERCENT, DEFAULT_CONTEXT_WINDOW

    written = model.token if token is None else token
    entry: dict[str, object] = {"model": model.model}
    if written:
        entry["token"] = written
    if model.display_model:
        entry["display_model"] = model.display_model
    if model.base_url:
        entry["base_url"] = model.base_url
    if model.anthropic:
        entry["anthropic"] = True
    if model.responses_api:
        entry["responses_api"] = True
    if model.chat:
        entry["chat"] = True
    if model.multimodal:
        entry["multimodal"] = True
    if model.temperature is not None:
        entry["temperature"] = model.temperature
    if model.context_window != DEFAULT_CONTEXT_WINDOW:
        entry["context_window"] = model.context_window
    if model.compact_percent != DEFAULT_COMPACT_PERCENT:
        entry["compact_percent"] = model.compact_percent
    if model.reasoning_efforts:
        entry["reasoning_efforts"] = [level.value for level in model.reasoning_efforts]
    return entry


def _blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` line range of every ``[[models]]`` block, in order.

    A block runs to the next table header, less the blank and comment lines at its end: those are
    the introduction to whatever follows, and belong to it.
    """
    blocks: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        if not _MODEL_HEADER.match(line):
            continue
        end = len(lines)
        for later in range(index + 1, len(lines)):
            if _HEADER.match(lines[later]):
                end = later
                break
        while end > index + 1 and (not lines[end - 1].strip() or lines[end - 1].lstrip().startswith("#")):
            end -= 1
        blocks.append((index, end))
    return blocks


def _parse(text: str, where: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigEditError(f"{where} is not valid TOML: {error}") from error


def _guarded(text: str, where: Path) -> tuple[list[str], list[tuple[int, int]], dict[str, Any]]:
    """Return the file's lines, its model blocks and its data, or refuse a layout this cannot edit."""
    data = _parse(text, where)
    models = data.get("models")
    if not isinstance(models, list) or not all(isinstance(entry, dict) for entry in models):
        raise ConfigEditError(f"{where} has no [[models]] entries to edit")
    lines = text.split("\n")
    blocks = _blocks(lines)
    if len(blocks) != len(models):
        raise ConfigEditError(
            f"{where} writes its models in a way /config cannot edit safely "
            f"({len(models)} models, {len(blocks)} [[models]] blocks); edit the file by hand"
        )
    return lines, blocks, data


def _checked(new_text: str, before: dict[str, Any], expected: list[dict[str, Any]], where: Path) -> None:
    """Refuse a result that does not hold what the edit meant it to, before anything is written."""
    after = _parse(new_text, where)
    if after.get("models") != expected:
        raise ConfigEditError("the edit did not produce the models it meant to; nothing was written")
    others_before = {key: value for key, value in before.items() if key != "models"}
    others_after = {key: value for key, value in after.items() if key != "models"}
    if others_before != others_after:
        raise ConfigEditError("the edit would have changed something other than the models; nothing was written")
    models = after.get("models")
    try:
        _read_models(models, where)
    except ValueError as error:
        raise ConfigEditError(str(error)) from error


def add_model(text: str, entry: Mapping[str, object], *, where: Path) -> str:
    """Return ``text`` with one more model after the last, which is where a reader looks for it.

    Args:
        text: The config file as it is.
        entry: The new model's keys.
        where: The file's path, for messages.
    """
    lines, blocks, data = _guarded(text, where)
    block = render_entry(entry).rstrip("\n").split("\n")
    at = blocks[-1][1] if blocks else len(lines)
    if blocks:
        insert = ["", *block]
        new = [*lines[:at], *insert, *lines[at:]]
    else:  # pragma: no cover - _guarded refuses a file with no models
        new = [*lines, *block]
    result = "\n".join(new)
    _checked(result, data, [*data["models"], dict(_parse(render_entry(entry), where)["models"][0])], where)
    return result


def replace_model(text: str, index: int, entry: Mapping[str, object], *, where: Path) -> str:
    """Return ``text`` with model number ``index`` (from zero) rewritten as ``entry``.

    Comments inside that one block are not kept; those above it and everywhere else are.
    """
    lines, blocks, data = _guarded(text, where)
    if not 0 <= index < len(blocks):
        raise ConfigEditError(f"there is no model number {index + 1}")
    start, end = blocks[index]
    new = [*lines[:start], *render_entry(entry).rstrip("\n").split("\n"), *lines[end:]]
    expected = list(data["models"])
    expected[index] = dict(_parse(render_entry(entry), where)["models"][0])
    result = "\n".join(new)
    _checked(result, data, expected, where)
    return result


def remove_model(text: str, index: int, *, where: Path) -> str:
    """Return ``text`` without model number ``index`` (from zero). The last one cannot be removed."""
    lines, blocks, data = _guarded(text, where)
    if not 0 <= index < len(blocks):
        raise ConfigEditError(f"there is no model number {index + 1}")
    if len(blocks) == 1:
        raise ConfigEditError("that is the only model; add another before removing it")
    start, end = blocks[index]
    # The blank line that set the block apart goes with it, so removing leaves no gap behind.
    if start > 0 and not lines[start - 1].strip():
        start -= 1
    new = [*lines[:start], *lines[end:]]
    expected = list(data["models"])
    del expected[index]
    result = "\n".join(new)
    _checked(result, data, expected, where)
    return result


def _set_key(text: str, table: str, key: str, literal: str, value: object, *, where: Path, command: str) -> str:
    """Return ``text`` with ``[table] key`` set to ``value``, touching nothing else.

    The key's line is replaced where the file already has one, added under an existing header, or the
    table is appended at the end. The result is checked before it is returned: it must parse and differ
    from the original in nothing but this key. A file that spells the table some other way (an inline
    table, say) is refused rather than guessed at.

    Args:
        table: The table's name (``"ui"``).
        key: The key in it (``"theme"``).
        literal: ``value`` as TOML spells it (``'"nord"'``, ``"true"``).
        value: What the key must read back as.
        where: The file, for messages.
        command: What the reader ran, for the message when the file cannot be edited safely.
    """
    header_pattern = re.compile(rf"^\s*\[\s*{re.escape(table)}\s*\]\s*(#.*)?$")
    key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    before = _parse(text, where)
    lines = text.split("\n")
    line = f"{key} = {literal}"
    header = next((index for index, item in enumerate(lines) if header_pattern.match(item)), None)
    if header is None:
        if table in before:
            raise ConfigEditError(
                f"{where} writes [{table}] in a way {command} cannot edit safely; edit the file by hand"
            )
        while lines and not lines[-1].strip():
            lines.pop()
        new = [*lines, "", f"[{table}]", line, ""]
    else:
        end = next((i for i in range(header + 1, len(lines)) if _HEADER.match(lines[i])), len(lines))
        existing = next((i for i in range(header + 1, end) if key_pattern.match(lines[i])), None)
        if existing is not None:
            new = [*lines[:existing], line, *lines[existing + 1 :]]
        else:
            new = [*lines[: header + 1], line, *lines[header + 1 :]]
    result = "\n".join(new)
    after = _parse(result, where)
    table_before = {name: item for name, item in before.get(table, {}).items() if name != key}
    table_after = {name: item for name, item in after.get(table, {}).items() if name != key}
    others_before = {name: item for name, item in before.items() if name != table}
    others_after = {name: item for name, item in after.items() if name != table}
    if after.get(table, {}).get(key) != value or table_before != table_after or others_before != others_after:
        raise ConfigEditError(f"the edit would have changed something other than {table}.{key}; nothing was written")
    return result


def set_theme(text: str, name: str, *, where: Path) -> str:
    """Return ``text`` with ``[ui] theme`` set to ``name``, touching nothing else.

    Like the model edits it is checked before it is returned: the result must parse and differ from the
    original in nothing but ``ui.theme``.
    """
    return _set_key(text, "ui", "theme", toml_string(name), name, where=where, command="/theme")


def set_pet(text: str, name: str, *, where: Path) -> str:
    """Return ``text`` with ``[ui] pet`` set to ``name``, touching nothing else."""
    return _set_key(text, "ui", "pet", toml_string(name), name, where=where, command="/pet")


def set_pet_position(text: str, across: float, down: float, *, where: Path) -> str:
    """Return ``text`` with ``[ui] pet_position`` set to where the pet was left, touching nothing else.

    The shares are rounded to three places: a pet moves a cell at a time, and a number such as
    ``0.8571428571428571`` in a file the reader reads and edits is noise.
    """
    shares = [round(min(1.0, max(0.0, across)), 3), round(min(1.0, max(0.0, down)), 3)]
    literal = "[" + ", ".join(repr(share) for share in shares) + "]"
    return _set_key(text, "ui", "pet_position", literal, shares, where=where, command="the pet")


def set_self_compaction(text: str, enabled: bool, *, where: Path) -> str:
    """Return ``text`` with ``[compaction] self`` set to ``enabled``, touching nothing else."""
    return _set_key(
        text, "compaction", "self", "true" if enabled else "false", enabled, where=where, command="/self-compact"
    )


def set_statusline(text: str, shown: Mapping[str, bool], *, where: Path) -> str:
    """Return ``text`` with each named part of ``[statusline]`` set to shown or hidden, touching nothing else.

    A part is a key of the table (``ctx = false`` hides it, ``ctx = true`` shows it again). Each key is
    written and checked on its own, as the other single-key edits are, so a file that cannot take one is
    refused whole rather than half-written.
    """
    for name, visible in shown.items():
        text = _set_key(
            text, "statusline", name, "true" if visible else "false", visible, where=where, command="/statusline"
        )
    return text


def file_entries(text: str, *, where: Path) -> list[dict[str, Any]]:
    """Return the models as the file writes them (a token left to the environment stays absent)."""
    return list(_guarded(text, where)[2]["models"])


def write_text_atomically(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` so a crash leaves the old file or the new one, never half.

    The new file takes the old one's permissions: the file holds tokens, and a reader who made it
    private has not asked for that to change by adding a model.
    """
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    handle, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as file:
            file.write(text)
        with contextlib.suppress(OSError):  # not every file system keeps modes
            os.chmod(name, mode)
        os.replace(name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(name)
        raise
