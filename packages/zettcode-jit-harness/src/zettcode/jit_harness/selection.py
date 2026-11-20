"""The harness a session works in, when it is not its own: one borrowed from another session, or the shared default.

The page lists harness folders; choosing one points this session at that folder instead of its own. ``/harness use``
sets a *default* the same way for every session that has not borrowed one: a library harness (see
:mod:`zettcode.engine.harness_library`). The mapping is kept here rather than in the frame, so the harness extension,
the command and the page read the same value: :meth:`HarnessChoices.effective` is the one answer to "which folder
does this session use", before it falls back to its own.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

#: Service name under which the plugin provides the choices.
HARNESS_CHOICES = "harness-choices"

#: What a listener is told when the default changed: every session is affected, not one. Not a possible session id
#: (those are generated, never ``*``), so it cannot be taken for one.
ALL_SESSIONS = "*"


@dataclass(frozen=True, slots=True)
class HarnessChoice:
    """One harness a session works in: the row label it came from and its directory."""

    label: str
    directory: Path


class HarnessChoices:
    """Map a session to the harness it works in, and tell the extension when it changes."""

    def __init__(self, store: Path | None = None) -> None:
        """Keep borrows in memory, and also under ``store`` (one small file a session) when it is given.

        A borrow written there is read back the first time the session is asked about, so a conversation that is
        resumed — in this window or a later one — goes on working in the harness it borrowed. A borrow whose folder
        is gone is ignored.
        """
        self._store = store
        self._store_error: str | None = None
        self._recalled: set[str] = set()
        self._choices: dict[str, HarnessChoice] = {}
        self._default: HarnessChoice | None = None
        self._listeners: list[Callable[[str], None]] = []

    @property
    def default(self) -> HarnessChoice | None:
        """Return the harness every session works in unless it borrowed another, or ``None`` for each its own."""
        return self._default

    def target(self, session_id: str) -> HarnessChoice | None:
        """Return the harness this session borrowed, or ``None`` when it has not borrowed one."""
        return self._borrowed(session_id)

    def effective(self, session_id: str) -> HarnessChoice | None:
        """Return the harness this session works in — borrowed, else the default — or ``None`` for its own."""
        return self._borrowed(session_id) or self._default

    def _file(self, session_id: str) -> Path | None:
        """Return where this session's borrow is kept: one file named like its harness folder, so none leaves the store."""
        if self._store is None or session_id == ALL_SESSIONS or not session_id:
            return None
        from zett_agent.jit_harness.repo import session_directory_name

        return self._store / f"{session_directory_name(session_id)}.json"

    def _inside(self, directory: Path) -> bool:
        """Whether a folder is one a borrow may name: absolute, and strictly under the harness directory.

        Compared after resolving, so neither a ``..`` nor a link planted under the directory leads out of it, and the
        directory itself (every workspace at once) is not a session's folder.
        """
        if self._store is None or not directory.is_absolute():
            return False
        root = self._store.parent
        try:
            resolved = directory.resolve()
            return resolved != root.resolve() and resolved.is_relative_to(root.resolve())
        except (OSError, RuntimeError, ValueError):
            return False

    def _verdict(self, choice: HarnessChoice | None) -> str:
        """Judge a stored borrow: ``ok``, ``bad`` (delete the record) or ``unknown`` (leave it, borrow nothing now).

        Only a folder that is really absent, or is not a folder, makes a record dead. A stat that fails for another
        reason — a permission, an I/O error — says nothing about whether the borrow is fine once that passes.
        """
        if choice is None or not self._inside(choice.directory):
            return "bad"
        try:
            return "ok" if stat.S_ISDIR(os.stat(choice.directory).st_mode) else "bad"
        except (FileNotFoundError, NotADirectoryError):
            return "bad"
        except OSError:
            return "unknown"

    def _borrowed(self, session_id: str) -> HarnessChoice | None:
        """Return this session's borrow, reading the stored one the first time it is asked about.

        What becomes of the record is :meth:`_verdict`'s: ``ok`` borrows, ``bad`` (unreadable, outside the harness
        directory, or its folder absent) deletes it so it cannot come back to life, and anything else leaves it for a
        run that can tell. The record lives under the harness directory, as
        every folder a borrow may name does, so a tree that is not mounted has no record to judge.
        """
        if session_id not in self._recalled:
            self._recalled.add(session_id)
            path = self._file(session_id)
            if path is not None and session_id not in self._choices and path.is_file():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    choice: HarnessChoice | None = HarnessChoice(str(data["label"]), Path(str(data["directory"])))
                except (OSError, ValueError, KeyError, TypeError):
                    choice = None
                verdict = self._verdict(choice)
                if verdict == "ok" and choice is not None:
                    self._choices[session_id] = choice
                elif verdict == "bad":
                    self._remember(session_id, None)
        return self._choices.get(session_id)

    @property
    def store_error(self) -> str | None:
        """Why the last borrow could not be written down, or ``None``: it then will not survive a resume."""
        return self._store_error

    def _remember(self, session_id: str, choice: HarnessChoice | None) -> None:
        """Write or remove the stored borrow; a store that cannot be written costs only the resume, never the switch."""
        from zettcode.config_edit import write_text_atomically

        path = self._file(session_id)
        if path is None:
            return
        self._store_error = None
        try:
            if choice is None:
                path.unlink(missing_ok=True)
            elif not self._inside(choice.directory):
                # Read back by the same rule at the next start, which would delete the record: say so now, and leave
                # no record of an earlier borrow that would contradict it.
                path.unlink(missing_ok=True)
                self._store_error = "that folder is not one a session can borrow"
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                write_text_atomically(path, json.dumps({"label": choice.label, "directory": str(choice.directory)}))
        except OSError as exc:
            self._store_error = str(exc)

    def directory(self, session_id: str) -> Path | None:
        """Return the directory this session works in, or ``None`` to use the session's own."""
        choice = self.effective(session_id)
        return None if choice is None else choice.directory

    def select(self, session_id: str, label: str, directory: Path) -> bool:
        """Borrow the harness named by ``label`` for ``session_id``; return whether that changed anything.

        Choosing what the session already works in — the folder it borrowed, or the default it has no borrow over —
        changes nothing.
        """
        current = self.effective(session_id)
        if current is not None and current.directory == directory:
            borrowed = self._borrowed(session_id)
            if borrowed is None:
                return False
            if borrowed.label != label:
                # Only the name shown for the folder differs: keep the new one, but nothing the model sees moved.
                self._choices[session_id] = HarnessChoice(label, directory)
                self._remember(session_id, self._choices[session_id])
            return False
        self._choices[session_id] = HarnessChoice(label, directory)
        self._remember(session_id, self._choices[session_id])
        self._changed(session_id)
        return True

    def clear(self, session_id: str) -> bool:
        """Drop this session's borrow; return whether it had one. It then works in the default, or its own."""
        self._borrowed(session_id)
        if self._choices.pop(session_id, None) is None:
            return False
        self._remember(session_id, None)
        self._changed(session_id)
        return True

    def use(self, label: str, directory: Path) -> bool:
        """Make a harness the default for every session; return whether that changed anything."""
        chosen = HarnessChoice(label, directory)
        if self._default == chosen:
            return False
        self._default = chosen
        self._changed(ALL_SESSIONS)
        return True

    def unuse(self) -> bool:
        """Go back to each session's own harness; return whether there was a default."""
        if self._default is None:
            return False
        self._default = None
        self._changed(ALL_SESSIONS)
        return True

    def add_listener(self, listener: Callable[[str], None]) -> None:
        """Call ``listener`` after a choice changes (with :data:`ALL_SESSIONS` for the default); the harness uses it."""
        self._listeners.append(listener)

    def _changed(self, session_id: str) -> None:
        for listener in tuple(self._listeners):
            listener(session_id)
