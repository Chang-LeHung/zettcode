"""The harness library: harnesses kept by name, for every session of every workspace.

A session's own harness is a folder the model writes into (see :mod:`zettcode.engine.harness_paths`). The library is
the other kind: ``<harness_dir>/library/<name>/<repository>/``, a folder of the same shape that nobody's session owns,
so it can be installed from GitHub, listed, updated, copied (``fork``) and chosen (``[harness] use``) without the
framework knowing the difference. The page that lists harnesses finds it as one more workspace called ``library``.

A library entry holds the repository's files without ``.git`` and one ``SOURCE.json`` beside them, which records where
it came from and the digest of the files as they were installed — what tells ``update`` that the model or the reader
has changed them since.

Nothing here imports a repository, and nothing here talks to a person: the functions raise :class:`LibraryError` with a
sentence to show, and the command that asks for a confirmation is the caller's.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ZettCodeConfig

#: The folder under ``harness_dir`` the library lives in. A workspace folder always ends in ``-<8 hex>``, so no
#: workspace can be called this.
LIBRARY_DIRECTORY = "library"
#: The file beside an entry's repositories that says where it came from.
SOURCE_FILE = "SOURCE.json"
#: Seconds one ``git`` call may take before it is given up on.
GIT_TIMEOUT = 120
#: Variables that point git at a repository other than the one in the working directory.
_GIT_REPOSITORY_VARIABLES = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
        # Configuration injected through the environment: the reader's own files (``~/.gitconfig``, credential
        # helpers) are what a private repository needs and stay; a variable somebody exported is not theirs to trust.
        "GIT_CONFIG",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_GLOBAL",
        "GIT_CONFIG_SYSTEM",
    }
)
#: Variables of the form ``GIT_CONFIG_KEY_<n>`` and ``GIT_CONFIG_VALUE_<n>``, dropped with the ones above.
_GIT_CONFIG_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
#: What a download must not run: its hooks, a file-system monitor, and the smudge filters (git-lfs, say) that a
#: ``.gitattributes`` of the repository's own could name — an LFS pointer would otherwise fetch from the host in the
#: repository's ``.lfsconfig``, which the reader never chose. The files stay what they are: a pointer is a text file.
_GIT_SAFE_OPTIONS = (
    "-c",
    "core.hooksPath=" + os.devnull,
    "-c",
    "core.fsmonitor=",
    "-c",
    "filter.lfs.smudge=",
    "-c",
    "filter.lfs.process=",
    "-c",
    "filter.lfs.required=false",
)
_OWNER = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
_SOURCE = re.compile(rf"^(?P<owner>{_OWNER})/(?P<repo>{_OWNER}?)(?:\.git)?(?:[@#](?P<ref>[^\s]+))?$")
_ENTRY_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class LibraryError(Exception):
    """A request the library refuses; the message is a sentence for the reader."""


class GitMissingError(LibraryError):
    """``git`` is not on this machine."""


@dataclass(frozen=True, slots=True)
class Source:
    """Where a harness comes from: a GitHub repository and, optionally, a branch, a tag or a commit."""

    url: str
    ref: str = ""

    def shown(self) -> str:
        """Return the source as the reader typed it."""
        short = self.url.removeprefix("https://github.com/").removesuffix(".git")
        return f"{short}@{self.ref}" if self.ref else short


@dataclass(frozen=True, slots=True)
class Candidate:
    """A repository that meets the harness format, read before any of its code runs."""

    name: str
    version: str
    description: str
    tools: tuple[str, ...]
    banned: tuple[str, ...]
    files: tuple[str, ...]
    size: int
    digest: str


@dataclass(frozen=True, slots=True)
class Prepared:
    """A downloaded repository, checked and waiting for the reader's answer."""

    source: Source
    commit: str
    directory: Path
    candidate: Candidate


@dataclass(frozen=True, slots=True)
class Entry:
    """One library harness: its folder, the repositories in it and what ``SOURCE.json`` says."""

    name: str
    path: Path
    repositories: tuple[str, ...]
    source: dict[str, object]

    @property
    def origin(self) -> str:
        """Return where it came from, in a phrase a table can hold."""
        url = self.source.get("url")
        if isinstance(url, str) and url:
            ref = self.source.get("ref")
            return Source(url, ref if isinstance(ref, str) else "").shown()
        forked = self.source.get("forked_from")
        if isinstance(forked, str) and forked:
            return f"fork of {forked}"
        return "local"

    @property
    def commit(self) -> str:
        """Return the commit it was installed at, or an empty string for a harness that has none."""
        value = self.source.get("commit")
        return value if isinstance(value, str) else ""


def library_root(config: ZettCodeConfig) -> Path:
    """Return the folder the library's entries are in."""
    return config.harness_dir / LIBRARY_DIRECTORY


def valid_name(name: str) -> str:
    """Return ``name`` when it can be an entry's folder, else raise."""
    if _ENTRY_NAME.fullmatch(name) is None:
        raise LibraryError(
            f"`{name}` is not a harness name: use letters, digits, `_` and `-`, starting with a letter or digit "
            "(at most 64 characters)."
        )
    return name


def parse_source(text: str) -> Source:
    """Read ``owner/repo``, ``owner/repo@ref`` or a ``https://github.com/...`` address into a :class:`Source`."""
    value = text.strip()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
            break
    value = value.rstrip("/")
    found = _SOURCE.fullmatch(value)
    if found is None:
        raise LibraryError(
            f"`{text}` is not a GitHub repository: write owner/repo, owner/repo@branch-tag-or-commit, "
            "or a https://github.com/owner/repo address."
        )
    ref = found.group("ref") or ""
    if ref.startswith("-"):
        raise LibraryError(f"`{ref}` cannot be a branch, a tag or a commit: it starts with `-`.")
    return Source(f"https://github.com/{found.group('owner')}/{found.group('repo')}.git", ref)


def _git(arguments: list[str], cwd: Path) -> str:
    """Run one ``git`` command and return its output; a failure is a :class:`LibraryError` with git's own words."""
    if shutil.which("git") is None:
        raise GitMissingError(
            "git is not installed: install git first (https://git-scm.com/downloads), then run this again."
        )
    # Never ask for a password on a terminal that is not there: a private repository needs credentials git already has.
    # The repository variables a git hook leaves behind would point these commands at the reader's own repository, so
    # they are dropped; and no hook the reader's git configuration supplies runs in a download.
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _GIT_REPOSITORY_VARIABLES and not key.startswith(_GIT_CONFIG_PREFIXES)
    }
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", *_GIT_SAFE_OPTIONS, *arguments],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise LibraryError(f"git {arguments[0]} took longer than {GIT_TIMEOUT} seconds and was stopped.") from error
    except OSError as error:
        raise LibraryError(f"git could not be run: {error}") from error
    if result.returncode != 0:
        said = (result.stderr or result.stdout).strip().splitlines()
        raise LibraryError(f"git {arguments[0]} failed: {said[-1] if said else f'exit {result.returncode}'}")
    return result.stdout.strip()


def _tree_files(directory: Path) -> list[Path]:
    """Return every entry below ``directory`` that belongs to the harness: not ``.git``, not caches.

    A symbolic link is an entry of its own, not followed: it is kept as the link it is.
    """
    found: list[Path] = []
    for current, directories, files in os.walk(directory):
        directories[:] = sorted(item for item in directories if item not in {".git", "__pycache__"})
        found.extend(Path(current) / name for name in directories if (Path(current) / name).is_symlink())
        found.extend(Path(current) / name for name in sorted(files) if not name.endswith((".pyc", ".pyo")))
    return found


def tree_fingerprints(directory: Path) -> dict[str, str]:
    """Return a fingerprint for every entry of a repository, by relative path: a link's target, or a file's digest.

    A link is never read through (it may point at anything on this machine), so comparing two trees with this reads
    only the files that are really inside them.
    """
    found: dict[str, str] = {}
    for path in _tree_files(directory):
        shown = path.relative_to(directory).as_posix()
        if path.is_symlink():
            found[shown] = "link:" + os.readlink(path)
        else:
            found[shown] = "file:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return found


def tree_digest(directory: Path) -> str:
    """Return a digest of every file of a repository: names and content (a link's target), not modification times."""
    digest = hashlib.sha256()
    for path in _tree_files(directory):
        digest.update(path.relative_to(directory).as_posix().encode() + b"\0")
        digest.update((os.readlink(path).encode() if path.is_symlink() else path.read_bytes()) + b"\0")
    return digest.hexdigest()


def inspect(directory: Path) -> Candidate:
    """Check that ``directory`` is a harness repository and describe it; nothing in it is imported.

    The rules are the framework's own (``zett_agent.jit_harness``): ``__init__.py`` and ``MANIFEST`` at its root, a
    manifest that names the directory and the tools, a ban list that does not contradict it. The reader asked for this
    repository, so nothing else is limited here: they see its files before it is kept.
    """
    from zett_agent.jit_harness.manifest import inspect_repository

    if not directory.is_dir():
        raise LibraryError(f"{directory} is not a folder.")
    if not (directory / "__init__.py").is_file():
        raise LibraryError("This is not a harness repository: it has no __init__.py at its root.")
    policy = inspect_repository(directory)
    if policy.manifest is None or not policy.ok:
        problems = "; ".join(policy.problems) or "no MANIFEST"
        raise LibraryError(f"This is not a harness repository: {problems}.")
    files = _tree_files(directory)
    size = sum(path.lstat().st_size for path in files)
    manifest = policy.manifest
    return Candidate(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        tools=tuple(manifest.tools),
        banned=tuple(policy.banned),
        files=tuple(path.relative_to(directory).as_posix() for path in files),
        size=size,
        digest=tree_digest(directory),
    )


def prepare(source: Source, workdir: Path) -> Prepared:
    """Download ``source`` into ``workdir`` and check it; return what the reader has to see before anything is kept.

    The branch, tag or commit is fetched at depth one, so a long history is never downloaded. ``workdir`` is the
    caller's temporary folder: nothing is written anywhere else.
    """
    clone = workdir / "clone"
    clone.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], clone)
    _git(["fetch", "-q", "--depth", "1", "--", source.url, source.ref or "HEAD"], clone)
    _git(["checkout", "-q", "FETCH_HEAD"], clone)
    commit = _git(["rev-parse", "HEAD"], clone)
    # The framework wants a MANIFEST's name to be the folder it sits in, and a download's folder is called what the
    # reader chose to call the clone: stage the files under the name the manifest gives, then check them there.
    staged = workdir / _declared_name(clone)
    _copy_tree(clone, staged)
    return Prepared(source, commit, staged, inspect(staged))


def _declared_name(directory: Path) -> str:
    """Return the ``name`` a repository's MANIFEST declares, so it can be staged in a folder of that name."""
    from zettcode._compat import tomllib

    try:
        data = tomllib.loads((directory / "MANIFEST").read_text(encoding="utf-8"))
    except OSError as error:
        raise LibraryError("This is not a harness repository: it has no MANIFEST at its root.") from error
    except ValueError as error:
        raise LibraryError(f"This is not a harness repository: its MANIFEST is not TOML ({error}).") from error
    name = data.get("name")
    if not isinstance(name, str) or _ENTRY_NAME.fullmatch(name) is None:
        raise LibraryError("This is not a harness repository: its MANIFEST has no usable `name`.")
    return name


def _copy_tree(source: Path, target: Path) -> None:
    """Copy a repository's files, without ``.git`` and caches, into ``target``."""
    target.mkdir(parents=True)
    for path in _tree_files(source):
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            os.symlink(os.readlink(path), destination)
        else:
            shutil.copy2(path, destination)


def _write_source(path: Path, record: dict[str, object]) -> None:
    """Write ``SOURCE.json`` beside an entry's repositories, whole or not at all.

    A crash half-way through a plain write leaves an empty file, which reads as an entry with no upstream: the file
    is replaced atomically instead.
    """
    from zettcode.config_edit import write_text_atomically

    write_text_atomically(path / SOURCE_FILE, json.dumps(record, indent=2, sort_keys=True) + "\n")


def _now() -> str:
    """Return the time as an ISO string in UTC, to the second."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_source(path: Path) -> dict[str, object]:
    """Read ``SOURCE.json``; a missing or damaged one is an entry with no known origin, not an error."""
    try:
        data = json.loads((path / SOURCE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _repositories(path: Path) -> tuple[str, ...]:
    """Return the repositories in an entry: folders holding an ``__init__.py``."""
    try:
        return tuple(
            sorted(
                item.name
                for item in path.iterdir()
                if item.is_dir() and (item / "__init__.py").is_file() and not item.name.startswith(".")
            )
        )
    except OSError:
        return ()


def entries(config: ZettCodeConfig) -> list[Entry]:
    """Return every library harness, by name."""
    root = library_root(config)
    if not root.is_dir():
        return []
    found = [
        Entry(item.name, item, _repositories(item), _read_source(item))
        for item in sorted(root.iterdir(), key=lambda path: path.name)
        if item.is_dir() and not item.name.startswith(".")
    ]
    return found


def get(config: ZettCodeConfig, name: str) -> Entry:
    """Return the library harness called ``name``, or say which ones there are."""
    for entry in entries(config):
        if entry.name == name:
            return entry
    known = ", ".join(entry.name for entry in entries(config)) or "none installed"
    raise LibraryError(f"There is no harness called `{name}` in the library ({known}).")


def install(config: ZettCodeConfig, prepared: Prepared, *, name: str | None = None) -> Entry:
    """Keep a prepared repository in the library under ``name`` (its own name by default), pinned to its commit."""
    chosen = valid_name(name or prepared.candidate.name)
    target = library_root(config) / chosen
    library_root(config).mkdir(parents=True, exist_ok=True)
    try:
        # Exclusive: of two writers of one name, the second finds the folder made and stops, instead of mixing its
        # files into the first's entry or deleting it when it fails.
        target.mkdir()
    except FileExistsError:
        raise LibraryError(
            f"`{chosen}` is already in the library: `update` it, `remove` it first, or pass --as."
        ) from None
    try:
        _copy_tree(prepared.directory, target / prepared.candidate.name)
        _write_source(
            target,
            {
                "url": prepared.source.url,
                "ref": prepared.source.ref,
                "commit": prepared.commit,
                "digest": prepared.candidate.digest,
                "repository": prepared.candidate.name,
                "added": _now(),
            },
        )
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return get(config, chosen)


def recorded_repository(entry: Entry) -> str | None:
    """Return the repository folder name ``SOURCE.json`` records, or ``None`` when it is not a safe folder name.

    The file is plain text anyone can edit; a value that is not a folder name is no record, never a path to follow.
    """
    value = entry.source.get("repository")
    return value if isinstance(value, str) and _ENTRY_NAME.fullmatch(value) is not None else None


def _record_damaged(entry: Entry) -> bool:
    """Return whether an entry that has an upstream has lost what says what was installed.

    A fork has no upstream and no digest, and that is what it is. An entry with a URL and no usable digest or
    repository name was installed and then damaged (a hand edit, a half-written file): nothing can say whether it was
    changed, so an update must not assume it was not.
    """
    has_upstream = isinstance(entry.source.get("url"), str) and bool(entry.source.get("url"))
    return has_upstream and (not isinstance(entry.source.get("digest"), str) or recorded_repository(entry) is None)


def sweep_leftovers(config: ZettCodeConfig) -> int:
    """Remove the staging folders an update that was killed left behind, and return how many.

    A staging folder is only a leftover when nothing in it is the sole copy of anything: one holding a ``previous``
    tree is kept as long as some entry has lost its repository (``update_refusal`` names it for recovery), and removed
    once every entry has its repository again. A folder an update is using right now is never touched: it is taken
    only while that entry's lock is free.
    """
    root = library_root(config)
    if not root.is_dir():
        return 0
    from zettcode.filelock import SingletonLock

    losing = any(update_state(entry) == "missing" for entry in entries(config))
    removed = 0
    for folder in sorted(root.glob(".update-*")):
        if not folder.is_dir() or (losing and (folder / "previous").exists()):
            continue
        guards = [SingletonLock(lock) for lock in sorted(root.glob(".*.lock"))]
        held = [guard for guard in guards if guard.acquire()]
        try:
            # An update creates its lock before its staging folder, so a lock that appeared after the list above was
            # made belongs to an update that may be using this folder right now: look again once all are held.
            unchanged = len(sorted(root.glob(".*.lock"))) == len(guards)
            if len(held) == len(guards) and unchanged:
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
        finally:
            for guard in held:
                guard.release()
    return removed


def update_state(entry: Entry) -> str:
    """Return what an update would find: ``"ok"``, ``"changed"``, ``"missing"`` or ``"damaged"``.

    ``"damaged"`` is an entry with an upstream whose record no longer says what was installed; ``"missing"`` one whose
    repository is gone (a kill in the middle of an update, or somebody deleted it); ``"changed"`` one whose files
    differ from what was installed. A fork or a hand-made folder has no record to compare with and is ``"ok"``.
    """
    if _record_damaged(entry):
        return "damaged"
    repository = recorded_repository(entry)
    if repository is not None and not (entry.path / repository).is_dir():
        return "missing"
    return "changed" if modified(entry) else "ok"


def update_refusal(config: ZettCodeConfig, entry: Entry, *, force: bool) -> str | None:
    """Return why an update must not go ahead, or ``None``; the terminal command and ``update`` ask the same thing."""
    if force:
        return None
    state = update_state(entry)
    if state == "ok":
        return None
    if state == "missing":
        leftovers = sorted(library_root(config).glob(".update-*/previous"))
        where = (
            f" The old tree of an update that was cut short may be in {leftovers[0].parent}: move `previous` back "
            f"to `{entry.name}/{recorded_repository(entry)}` to recover it."
            if leftovers
            else ""
        )
        return (
            f"`{entry.name}` has lost its repository `{recorded_repository(entry)}`.{where} "
            f"`update --force` installs the new one in its place."
        )
    why = "its SOURCE.json no longer says what was installed" if state == "damaged" else "it has been changed"
    return (
        f"`{entry.name}` cannot be updated safely: {why}, and an update would overwrite what is there. "
        f"`fork {entry.name} <new>` keeps it, `update --force` replaces it (and a repository of the same name that "
        f"the entry did not install is never replaced, with or without --force)."
    )


def modified(entry: Entry) -> bool | None:
    """Return whether the repository the entry was installed from differs from what was installed.

    ``None`` when the entry records no digest (a fork, or a folder somebody made by hand), so there is nothing to
    compare with. A repository that is gone, or that cannot be read, counts as changed.
    """
    digest = entry.source.get("digest")
    repository = recorded_repository(entry)
    if not isinstance(digest, str) or repository is None:
        return None
    folder = entry.path / repository
    if not folder.is_dir():
        return True
    try:
        return tree_digest(folder) != digest
    except OSError:
        return True


def refetch(entry: Entry, workdir: Path) -> Prepared:
    """Download the entry's source again, at the branch or tag it was installed from, for ``update`` to compare."""
    url = entry.source.get("url")
    if not isinstance(url, str) or not url:
        raise LibraryError(f"`{entry.name}` has no upstream to update from: it is a {entry.origin}.")
    ref = entry.source.get("ref")
    return prepare(Source(url, ref if isinstance(ref, str) else ""), workdir)


def update(config: ZettCodeConfig, entry: Entry, prepared: Prepared, *, force: bool = False) -> Entry:
    """Replace the entry's repository with a newer download of the same source.

    A repository the model or the reader has changed since it was installed is refused unless ``force`` says to
    overwrite it: the way to keep those changes is ``fork``. Other repositories in the entry are left alone.

    Nothing is deleted before the new one is in place: the new tree is built in a staging folder beside the entry (not
    inside it, where a leftover would look like a repository), the old one is moved aside, the new one moved in and
    ``SOURCE.json`` rewritten, and any failure puts the old one back. A lock on the entry keeps two updates of it from
    taking each other's staging folders.
    """
    from zettcode.filelock import SingletonLock

    root = library_root(config)
    sweep_leftovers(config)
    lock = SingletonLock(root / f".{entry.name}.lock")
    if not lock.acquire():
        raise LibraryError(f"`{entry.name}` is being updated by another process; try again in a moment.")
    staging: Path | None = None
    try:
        entry = get(config, entry.name)
        refusal = update_refusal(config, entry, force=force)
        if refusal is not None:
            raise LibraryError(refusal)
        previous = recorded_repository(entry)
        name = prepared.candidate.name
        current = entry.path / name
        if (current.exists() or current.is_symlink()) and name != previous:
            # A repository of the same name that this entry did not install is somebody's work (the model writes
            # into a shared harness): moving it aside to be deleted with the staging folder would lose it, with
            # `--force` as much as without it.
            raise LibraryError(
                f"`{entry.name}` already holds a repository called `{name}` that it did not install from this "
                f"source; the update was not made. `remove` or `fork` the entry first."
            )
        staging = Path(tempfile.mkdtemp(prefix=".update-", dir=root))
        staged = staging / name
        aside = staging / "previous"
        _copy_tree(prepared.directory, staged)
        moved_aside = current.exists() or current.is_symlink()
        if moved_aside:
            os.replace(current, aside)
        try:
            os.replace(staged, current)
            record = dict(entry.source)
            record.update(
                commit=prepared.commit,
                digest=prepared.candidate.digest,
                repository=name,
                updated=_now(),
            )
            _write_source(entry.path, record)
        except BaseException:
            shutil.rmtree(current, ignore_errors=True)
            if moved_aside:
                os.replace(aside, current)
            raise
        if previous is not None and previous != name:
            shutil.rmtree(entry.path / previous, ignore_errors=True)
        return get(config, entry.name)
    finally:
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        lock.release()


def _used(config: ZettCodeConfig, name: str) -> bool:
    """Return whether ``name`` is the harness every session is set to work in."""
    return config.harness_use == name


def remove(config: ZettCodeConfig, name: str) -> Entry:
    """Delete a library harness; refused while it is the one every session works in, or while it is being updated."""
    from zettcode.filelock import SingletonLock

    entry = get(config, name)
    if _used(config, name):
        raise LibraryError(
            f"`{name}` is the harness every session works in: run `/harness use --none` in ZettCode first."
        )
    lock = SingletonLock(library_root(config) / f".{entry.name}.lock")
    if not lock.acquire():
        raise LibraryError(f"`{name}` is being updated by another process; try again in a moment.")
    try:
        shutil.rmtree(entry.path)
    finally:
        lock.release()
    return entry


def fork(config: ZettCodeConfig, name: str, new: str) -> Entry:
    """Copy a library harness under a new name, with no upstream, so changing the copy leaves the original alone."""
    entry = get(config, name)
    return keep(config, entry.path, new, origin=name)


def keep(config: ZettCodeConfig, folder: Path, new: str, *, origin: str) -> Entry:
    """Keep a harness folder — what a session's model wrote, or one it borrowed — as a library harness named ``new``.

    Every repository in it must be one a session could load (a manifest that names it and its tools), so the library
    never holds something the page lists and nothing can use; the reason is the refusal. A symbolic link is copied as
    the link it is, never as the file it points at.
    """
    from zett_agent.jit_harness.manifest import inspect_repository

    found = _repositories(folder)
    if not found:
        raise LibraryError(f"There is no harness repository to keep in {folder}.")
    for repository in found:
        policy = inspect_repository(folder / repository)
        if not policy.ok:
            raise LibraryError(f"`{repository}` cannot be loaded, so it was not kept: {'; '.join(policy.problems)}.")
    target = library_root(config) / valid_name(new)
    library_root(config).mkdir(parents=True, exist_ok=True)
    try:
        target.mkdir()
    except FileExistsError:
        raise LibraryError(f"`{new}` is already in the library.") from None
    try:
        shutil.copytree(
            folder,
            target,
            symlinks=True,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", SOURCE_FILE),
        )
        _write_source(target, {"forked_from": origin, "added": _now()})
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise
    return get(config, new)


def used_entry(config: ZettCodeConfig) -> Entry | None:
    """Return the library harness ``[harness] use`` names, or ``None`` when none is named or it is not there."""
    if not config.harness_use or _ENTRY_NAME.fullmatch(config.harness_use) is None:
        return None
    folder = library_root(config) / config.harness_use
    if not folder.is_dir():
        return None
    return Entry(folder.name, folder, _repositories(folder), _read_source(folder))


def write_use(name: str) -> Path:
    """Write ``[harness] use`` to the configuration file and return that file: the library harness every session
    works in (empty: none).

    It is the file ``$ZETTCODE_CONFIG`` or ``~/.zettcode/config.toml`` names, the one a start reads by default; a
    process that was handed another file with ``--config`` still reads that one. An empty name is how "every session its
    own harness" is spelled: the key stays, with ``""``, rather than being removed.
    """
    from zettcode.config_edit import set_string, write_text_atomically
    from zettcode.paths import config_path

    path = config_path()
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomically(path, set_string(text, "harness", "use", name, where=path, command="/harness use"))
    return path
