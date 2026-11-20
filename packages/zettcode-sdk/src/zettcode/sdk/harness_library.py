"""The user-level library of named harnesses, for a program that is not the terminal.

``zettcode harness`` and ``/harness`` keep harnesses by name under ``<harness_dir>/library`` (see
:mod:`zettcode.engine.harness_library`). This is the same library as a group of methods on the client, so an editor can
draw it: list what is there, show one, install from GitHub, update, fork and remove.

Installing and updating are two calls, because a download must be seen before it is kept: ``preview_add`` /
``preview_update`` download and inspect (nothing is imported, nothing is kept) and return a
:class:`~zettcode.sdk.types.HarnessPreview`; ``add`` / ``update`` take its ``commit`` and ``digest`` back, download that
commit again and keep it only when it is what was shown. ``/harness use`` and ``/harness save`` act on the running
conversation and stay commands (``client.plugins.plain_commands``).

Every method raises ``ValueError`` with the library's own words (git missing, a name taken, an update refused).
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

from .types import HarnessEntry, HarnessPreview, HarnessRepository

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.engine.harness_library import Entry, Prepared, Source

    from .client import Client

_T = TypeVar("_T")


def _entry(config: object, entry: Entry) -> HarnessEntry:
    from zettcode.engine.harness_library import describe

    info = describe(config, entry)  # type: ignore[arg-type]
    return HarnessEntry(
        info.name,
        info.origin,
        info.commit,
        info.state,
        info.in_use,
        tuple(
            HarnessRepository(item.name, item.version, item.description, item.tools, item.files, item.error)
            for item in info.repositories
        ),
    )


class HarnessLibrary:
    """The harnesses the user keeps by name, shared by every session of every workspace."""

    def __init__(self, client: Client) -> None:
        self._client = client

    async def _run(self, work: Callable[[], _T]) -> _T:
        """Run blocking library work (files, git) off the event loop, as ``ValueError`` when the library refuses."""
        from zettcode.engine.harness_library import LibraryError

        self._client._check_open()
        try:
            return await asyncio.to_thread(work)
        except LibraryError as error:
            raise ValueError(str(error)) from error

    async def entries(self) -> list[HarnessEntry]:
        """Return every harness in the library, by name."""
        from zettcode.engine.harness_library import entries

        config = self._client.config
        return await self._run(lambda: [_entry(config, item) for item in entries(config)])

    async def entry(self, name: str) -> HarnessEntry:
        """Return one harness with its manifests and files.

        Raises:
            ValueError: When the library has no harness of that name.
        """
        from zettcode.engine.harness_library import get

        config = self._client.config
        return await self._run(lambda: _entry(config, get(config, name)))

    async def preview_add(self, source: str, *, name: str | None = None) -> HarnessPreview:
        """Download ``source`` (``owner/repo``, ``owner/repo@ref`` or a GitHub URL), inspect it, and keep nothing.

        Raises:
            ValueError: When git is missing, the source is not a harness, or ``name`` is taken.
        """
        from zettcode.engine.harness_library import CAUTION, library_root, parse_source, prepare, valid_name

        config = self._client.config

        def work() -> HarnessPreview:
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
                )

        return await self._run(work)

    async def add(self, source: str, *, commit: str, digest: str, name: str | None = None) -> HarnessEntry:
        """Keep what ``preview_add`` showed, pinned to its commit.

        Raises:
            ValueError: When the download at ``commit`` is not what was shown, or the name is taken.
        """
        from zettcode.engine.harness_library import Source, install, parse_source, prepare

        config = self._client.config

        def work() -> HarnessEntry:
            parsed = parse_source(source)
            with tempfile.TemporaryDirectory(prefix="zettcode-harness-") as scratch:
                prepared = prepare(Source(parsed.url, commit), Path(scratch))
                if prepared.commit != commit or prepared.candidate.digest != digest:
                    raise ValueError("What was downloaded is not what was shown. Preview it again.")
                # What is recorded is what the reader asked for (a branch), not the commit that pinned this fetch.
                kept = install(config, _with_source(prepared, parsed), name=name)
            return _entry(config, kept)

        return await self._run(work)

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

        config = self._client.config

        def work() -> HarnessPreview:
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
                )

        return await self._run(work)

    async def update(self, name: str, *, commit: str, digest: str, force: bool = False) -> HarnessEntry:
        """Replace a harness with what ``preview_update`` showed.

        Raises:
            ValueError: When the download at ``commit`` is not what was shown, or the update is refused.
        """
        from zettcode.engine.harness_library import get, refetch, update, update_refusal

        config = self._client.config

        def work() -> HarnessEntry:
            entry = get(config, name)
            refusal = update_refusal(config, entry, force=force)
            if refusal is not None:
                raise ValueError(refusal)
            with tempfile.TemporaryDirectory(prefix="zettcode-harness-") as scratch:
                prepared = refetch(entry, Path(scratch), commit=commit)
                if prepared.commit != commit or prepared.candidate.digest != digest:
                    raise ValueError("What was downloaded is not what was shown. Preview it again.")
                updated = update(config, entry, prepared, force=force)
            return _entry(config, updated)

        return await self._run(work)

    async def fork(self, name: str, new: str) -> HarnessEntry:
        """Copy a harness under a new name, with no upstream, so the copy can change without touching it."""
        from zettcode.engine.harness_library import fork

        config = self._client.config
        return await self._run(lambda: _entry(config, fork(config, name, new)))

    async def remove(self, name: str) -> None:
        """Delete a harness from the library; refused while it is the one `[harness] use` names or an update runs."""
        from zettcode.engine.harness_library import remove

        config = self._client.config
        await self._run(lambda: remove(config, name))


def _with_source(prepared: Prepared, source: Source) -> Prepared:
    """Return ``prepared`` recording ``source`` (the reader's words) instead of the commit that pinned the fetch."""
    from dataclasses import replace

    return replace(prepared, source=source)
