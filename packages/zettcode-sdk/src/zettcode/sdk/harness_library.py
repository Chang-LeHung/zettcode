"""The user-level library of named harnesses, for a program that is not the terminal.

``zettcode harness`` and ``/harness`` keep harnesses by name under ``<harness_dir>/library`` (see
:mod:`zettcode.engine.harness_library`). This is the same library as a group of methods on the client, so an editor can
draw it: list what is there, show one, install from GitHub, update, fork and remove.

Installing and updating are two calls, because a download must be seen before it is kept: ``preview_add`` /
``preview_update`` download and inspect (nothing is imported, nothing is kept) and return a
:class:`~zettcode.sdk.types.HarnessPreview`; ``add`` / ``update`` take its ``commit`` and ``digest`` back, download that
commit again and keep it only when it is what was shown. ``/harness use`` and ``/harness save`` act on the running
conversation and stay commands (``client.plugins.plain_commands``).

A preview is a network call that can take minutes (up to the time git is allowed). Downloads, updates, forks and
removals through one library run one at a time, and a second one while another runs is refused with a ``ValueError``
rather than left waiting. The limit is per library object: ``client.harnesses`` is one per client, and a server keeps
one of its own for all its conversations. Every method raises ``ValueError`` with the library's own words (git
missing, a name taken, an update refused).

The library needs no model and no agent: it takes the configuration (a function, so a changed one is seen) and,
optionally, the file that configuration was loaded from, and a check that its owner is open.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from .types import HarnessEntry, HarnessPreview, HarnessRepository

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ZettCodeConfig
    from zettcode.engine.harness_library import Entry, Prepared, Source

_T = TypeVar("_T")


def _entry(
    config: ZettCodeConfig, entry: Entry, *, detail: bool = True, use: str | None = None, settings: Path | None = None
) -> HarnessEntry:
    from zettcode.engine.harness_library import describe

    info = describe(config, entry, detail=detail, use=use, settings_file=settings)
    return HarnessEntry(
        info.name,
        info.origin,
        info.commit,
        info.state,
        info.in_use,
        tuple(
            HarnessRepository(
                item.name, item.version, item.description, item.tools, item.files, item.error, item.file_count
            )
            for item in info.repositories
        ),
    )


class HarnessLibrary:
    """The harnesses the user keeps by name, shared by every session of every workspace."""

    def __init__(
        self,
        config: Callable[[], ZettCodeConfig],
        *,
        settings_file: Callable[[], Path | None] | None = None,
        check_open: Callable[[], None] | None = None,
    ) -> None:
        """Keep the library of ``config()``.

        Args:
            config: The configuration to read the library's place from.
            settings_file: The file that configuration was loaded from, when the process was given one of its own
                (``--config``); ``[harness] use`` is read from it. ``None`` means the default file.
            check_open: Raises when the owner of this library has been closed.
        """
        self._config = config
        self._settings_file = settings_file
        self._check_open = check_open
        self._turn = asyncio.Semaphore(1)

    def _settings(self) -> Path | None:
        return None if self._settings_file is None else self._settings_file()

    async def _run(self, work: Callable[[], _T], *, alone: bool = False) -> _T:
        """Run blocking library work (files, git) off the event loop, as ``ValueError`` when the library refuses.

        ``alone`` refuses the call while another such call runs: downloads are minutes long, and the threads they use
        are the ones the rest of the process shares.
        """
        from zettcode.engine.harness_library import LibraryError

        if self._check_open is not None:
            self._check_open()
        try:
            if not alone:
                return await asyncio.to_thread(work)
            if self._turn.locked():
                raise ValueError("Another harness download or change is already running; try again when it is done.")
            async with self._turn:
                return await asyncio.to_thread(work)
        except LibraryError as error:
            raise ValueError(str(error)) from error

    async def entries(self) -> list[HarnessEntry]:
        """Return every harness in the library, by name, cheaply.

        A repository carries ``file_count`` and not its ``files``, and ``state`` is ``""``: reading it takes every byte
        of the harness. ``entry(name)`` has both.
        """
        from zettcode.engine.harness_library import current_use, entries

        def work() -> list[HarnessEntry]:
            config, settings = self._config(), self._settings()
            use = current_use(config, settings)
            return [_entry(config, item, detail=False, use=use) for item in entries(config)]

        return await self._run(work)

    async def entry(self, name: str) -> HarnessEntry:
        """Return one harness with its manifests, files and ``state``.

        Raises:
            ValueError: When the library has no harness of that name.
        """
        from zettcode.engine.harness_library import get

        def work() -> HarnessEntry:
            config = self._config()
            return _entry(config, get(config, name), settings=self._settings())

        return await self._run(work)

    async def preview_add(self, source: str, *, name: str | None = None) -> HarnessPreview:
        """Download ``source`` (``owner/repo``, ``owner/repo@ref`` or a GitHub URL), inspect it, and keep nothing.

        Raises:
            ValueError: When git is missing, the source is not a harness, ``name`` is taken, or another download runs.
        """
        from zettcode.engine.harness_library import CAUTION, library_root, parse_source, prepare, valid_name

        def work() -> HarnessPreview:
            config = self._config()
            parsed = parse_source(source)
            if name is not None:
                valid_name(name)
            with tempfile.TemporaryDirectory(prefix="zettcode-harness-") as scratch:
                prepared = prepare(parsed, Path(scratch))
                chosen = name or prepared.candidate.name
                valid_name(chosen)
                if (library_root(config) / chosen).exists():
                    raise ValueError(f"`{chosen}` is already in the library: update it, or choose another name.")
                found = prepared.candidate
                return HarnessPreview(
                    "add",
                    chosen,
                    parsed.shown(),
                    prepared.commit,
                    found.digest,
                    found.version,
                    found.description,
                    found.tools,
                    found.banned,
                    found.files,
                    found.size,
                    (),
                    False,
                    CAUTION,
                    dict(found.links),
                )

        return await self._run(work, alone=True)

    async def add(self, source: str, *, commit: str, digest: str, name: str | None = None) -> HarnessEntry:
        """Keep what ``preview_add`` showed, pinned to its commit.

        Raises:
            ValueError: When ``commit`` or ``digest`` is not what a preview reports, when the download at ``commit`` is
                not what was shown, when the name is taken, or when another download runs.
        """
        from zettcode.engine.harness_library import Source, install, parse_source, prepare, valid_commit, valid_digest

        def work() -> HarnessEntry:
            config = self._config()
            valid_commit(commit)
            valid_digest(digest)
            parsed = parse_source(source)
            with tempfile.TemporaryDirectory(prefix="zettcode-harness-") as scratch:
                prepared = prepare(Source(parsed.url, commit), Path(scratch))
                if prepared.commit != commit or prepared.candidate.digest != digest:
                    raise ValueError("What was downloaded is not what was shown. Preview it again.")
                # What is recorded is what the reader asked for (a branch), not the commit that pinned this fetch.
                kept = install(config, _with_source(prepared, parsed), name=name)
            return _entry(config, kept, settings=self._settings())

        return await self._run(work, alone=True)

    async def preview_update(self, name: str, *, force: bool = False) -> HarnessPreview:
        """Download the source of a harness again and say what an update would change; keep nothing.

        Raises:
            ValueError: When the harness has no upstream, or an update is refused (it was changed since it was
                installed, its repository is missing, or its record is damaged) and ``force`` does not say otherwise.
        """
        from zettcode.engine.harness_library import (
            CAUTION,
            changes,
            get,
            recorded_repository,
            refetch,
            update_refusal,
        )

        def work() -> HarnessPreview:
            config = self._config()
            entry = get(config, name)
            refusal = update_refusal(config, entry, force=force)
            if refusal is not None:
                raise ValueError(refusal)
            with tempfile.TemporaryDirectory(prefix="zettcode-harness-") as scratch:
                prepared = refetch(entry, Path(scratch))
                previous = recorded_repository(entry)
                diff = changes(entry.path / previous, prepared) if previous is not None else []
                found = prepared.candidate
                return HarnessPreview(
                    "update",
                    name,
                    prepared.source.shown(),
                    prepared.commit,
                    found.digest,
                    found.version,
                    found.description,
                    found.tools,
                    found.banned,
                    found.files,
                    found.size,
                    tuple(diff),
                    prepared.commit == entry.commit,
                    CAUTION,
                    dict(found.links),
                )

        return await self._run(work, alone=True)

    async def update(
        self,
        name: str,
        *,
        commit: str,
        digest: str,
        force: bool = False,
        guard: Callable[[], None] | None = None,
    ) -> HarnessEntry:
        """Replace a harness with what ``preview_update`` showed.

        ``guard`` is called from the worker after the download and the staging copy, right before the old files are
        moved aside: a caller that must not change the files under a running conversation raises there, and nothing is
        changed.

        Raises:
            ValueError: When ``commit`` or ``digest`` is not what a preview reports, when the download at ``commit`` is
                not what was shown, when the update is refused, or when another download runs.
        """
        from zettcode.engine.harness_library import get, refetch, update, update_refusal, valid_commit, valid_digest

        def work() -> HarnessEntry:
            config = self._config()
            valid_commit(commit)
            valid_digest(digest)
            entry = get(config, name)
            refusal = update_refusal(config, entry, force=force)
            if refusal is not None:
                raise ValueError(refusal)
            with tempfile.TemporaryDirectory(prefix="zettcode-harness-") as scratch:
                prepared = refetch(entry, Path(scratch), commit=commit)
                if prepared.commit != commit or prepared.candidate.digest != digest:
                    raise ValueError("What was downloaded is not what was shown. Preview it again.")
                updated = update(config, entry, prepared, force=force, guard=guard)
            return _entry(config, updated, settings=self._settings())

        return await self._run(work, alone=True)

    async def fork(self, name: str, new: str) -> HarnessEntry:
        """Copy a harness under a new name, with no upstream, so the copy can change without touching it."""
        from zettcode.engine.harness_library import fork

        def work() -> HarnessEntry:
            config = self._config()
            return _entry(config, fork(config, name, new), settings=self._settings())

        return await self._run(work, alone=True)

    async def remove(self, name: str, *, guard: Callable[[], None] | None = None) -> None:
        """Delete a harness from the library; refused while it is the one `[harness] use` names or an update runs.

        ``guard`` is called from the worker right before the files are removed (see :meth:`update`).
        """
        from zettcode.engine.harness_library import remove

        def work() -> None:
            config = self._config()
            if guard is not None:
                guard()
            remove(config, name, settings_file=self._settings())

        await self._run(work, alone=True)


def _with_source(prepared: Prepared, source: Source) -> Prepared:
    """Return ``prepared`` recording ``source`` (the reader's words) instead of the commit that pinned the fetch."""
    from dataclasses import replace

    return replace(prepared, source=source)
