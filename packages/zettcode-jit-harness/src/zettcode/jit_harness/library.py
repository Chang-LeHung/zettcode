"""``/harness use``, ``save`` and ``fork``: the words that work on the library from inside a session, with no widgets.

The terminal's command and the plain one every front end can run both import these, so what a reader is told is one
text. Each returns the Markdown to answer with; a refusal is an answer too, never a traceback.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from zettcode.engine.harness_library import (
    LibraryError,
    get,
    keep,
    library_root,
    valid_name,
    write_use,
)
from zettcode.engine.harness_library import fork as fork_entry
from zettcode.engine.harness_paths import existing_session_path

from .brief import CACHE_MISS, NOT_MOUNTED

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ZettCodeConfig

    from .selection import HarnessChoices


def _cost(harness_on: bool) -> str:
    """Return what a change of folder costs the next request."""
    return CACHE_MISS if harness_on else NOT_MOUNTED


def use(config: ZettCodeConfig, choices: HarnessChoices | None, rest: str, *, harness_on: bool) -> str:
    """Make a library harness the one every session works in, or (``--none``) hand each session back its own.

    The choice is written to ``[harness] use`` so the next start keeps it, and takes effect for the sessions of this
    window at once. With no name it says what the choice is.
    """
    word = rest.strip()
    if choices is None:
        return "Choosing a harness is unavailable in this window."
    if not word:
        default = choices.default
        if default is None:
            return "Every session works in its own harness. `/harness use <name>` shares a library harness instead."
        return f"Every session works in the library harness `{default.label.removeprefix('library/')}`."
    try:
        # The file first: a write that fails leaves every session where it was and says so, instead of changing them
        # now and losing the choice at the next start. Writing is idempotent, so "already" is still a retry of it.
        if word == "--none":
            written = write_use("")
            had_default = choices.unuse()
            return (
                f"Every session works in its own harness again. {_cost(harness_on and had_default)}\n\n"
                f"Written to `{written}`; other windows and the editor change at their next start "
                "(unless a server was started with `--config` naming another file)."
            )
        name = valid_name(word)
        entry = get(config, name)
        written = write_use(entry.name)
        changed = choices.use(f"library/{entry.name}", entry.path)
    except (LibraryError, OSError, ValueError) as error:
        return f"Nothing was changed: {error}"
    empty = "" if entry.repositories else " It has no repository yet, so there is nothing in it to load."
    head = (
        f"Every session in this window works in the library harness `{entry.name}`. What the model writes goes into "
        f"it, for every workspace. {_cost(harness_on)}"
        if changed
        else f"Every session in this window already works in `{entry.name}`."
    )
    return (
        f"{head}{empty}\n\nWritten to `{written}`; other windows and the editor change at their next start "
        "(unless a server was started with `--config` naming another file)."
    )


def save(config: ZettCodeConfig, choices: HarnessChoices | None, session_id: str, rest: str) -> str:
    """Keep the harness this session works in — its own, or one it borrowed — in the library under a name."""
    name = rest.strip()
    if not name:
        return "Name it: `/harness save <name>` keeps this session's harness in the library under that name."
    effective = choices.effective(session_id) if choices is not None else None
    if effective is not None and Path(effective.directory).parent == library_root(config):
        return (
            f"This session already works in the library harness `{effective.directory.name}`: "
            f"`/harness fork {effective.directory.name} {name}` makes a copy of it to change on its own."
        )
    folder = effective.directory if effective is not None else existing_session_path(config, session_id)
    # What the library records is whose code this is: a borrowed folder was written by another session, not this one.
    origin = f"session {session_id}" if effective is None else effective.label
    try:
        entry = keep(config, folder, name, origin=origin)
    except (LibraryError, OSError) as error:
        return f"Nothing was kept: {error}"
    return f"Kept as the library harness `{entry.name}` ({', '.join(entry.repositories)}). `/harness use {entry.name}` shares it."


def fork(config: ZettCodeConfig, rest: str) -> str:
    """Copy a library harness under a new name, with no upstream, so the copy can change without touching it."""
    words = rest.split()
    if len(words) != 2:
        return "Say which and what to call the copy: `/harness fork <name> <new name>`."
    try:
        copy = fork_entry(config, words[0], words[1])
    except (LibraryError, OSError) as error:
        return f"Nothing was copied: {error}"
    return f"Copied `{words[0]}` as `{copy.name}`. `/harness use {copy.name}` works in the copy."
