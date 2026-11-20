"""``zettcode harness``: keep harnesses by name, install one from GitHub, update, copy and choose one.

The just-in-time harness is the Python tools the model writes for a task. This command is the shell side of keeping
them: a *library* of named harnesses, shared by every session of every workspace (see
:mod:`zettcode.engine.harness_library`).

* ``add`` downloads a GitHub repository that meets the harness format, shows what it is — manifest, tools, files —
  and keeps it only once the reader says yes, pinned to the commit it was downloaded at.
* ``update`` fetches the source again, shows what changed and replaces the repository on a yes; it refuses to
  overwrite changes made since the install, which ``fork`` keeps.
* ``fork`` copies a harness under a new name, with no upstream, to change on its own.
* ``remove`` deletes one; ``list`` and ``show`` read.

What works on a session — choosing the harness every session works in (``/harness use``), keeping what a session's
model wrote (``/harness save``) — is the in-process ``/harness`` command's, not this one's.

It decides nothing about loading: the code of a harness is imported only when a session loads it, in the sandbox the
permission level gives the harness, never by this command.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - annotations only
    from zettcode.config import ZettCodeConfig
    from zettcode.engine.harness_library import Entry, Prepared

EXIT_OK = 0
EXIT_FAILED = 1
#: What a shell reports for a process that was stopped by Ctrl-C.
EXIT_INTERRUPTED = 130

#: Files listed before the rest are counted: a harness is small, and a long list is not a better answer.
MAX_LISTED_FILES = 40

CAUTION = (
    "Its code runs on this machine when a session loads it, in the sandbox the permission level gives the harness "
    "(no sandbox at `/permission full`). Read it first if you do not know where it comes from."
)


def build_parser() -> argparse.ArgumentParser:
    """Return the parser for ``zettcode harness`` and its actions."""
    parser = argparse.ArgumentParser(
        prog="zettcode harness",
        description=(
            "Keep harnesses by name: install one from GitHub, update it, copy it, remove it. A harness is a repository "
            "of Python tools with a MANIFEST. Choosing the one every session works in is `/harness use`, inside ZettCode."
        ),
    )
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    listing = commands.add_parser("list", help="list the harnesses in the library")
    listing.add_argument("--json", action="store_true", help="print JSON instead of a table")

    show = commands.add_parser("show", help="show one harness: manifest, tools, files and where it came from")
    show.add_argument("name")

    add = commands.add_parser(
        "add",
        help="install a harness from GitHub: add owner/repo[@branch|tag|commit]",
        description=(
            "Download a GitHub repository with git, check that it meets the harness format (an __init__.py and a "
            "MANIFEST at its root), show what it is, and keep it in the library after you say yes."
        ),
    )
    add.add_argument("source", help="owner/repo, owner/repo@ref, or a https://github.com/owner/repo address")
    add.add_argument(
        "--as", dest="name", default=None, help="keep it under this name (the repository's own by default)"
    )
    add.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    updating = commands.add_parser("update", help="fetch a harness's source again and replace it after you confirm")
    updating.add_argument("name")
    updating.add_argument("--force", action="store_true", help="overwrite changes made since it was installed")
    updating.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")

    fork = commands.add_parser("fork", help="copy a harness under a new name, to change your own copy")
    fork.add_argument("name")
    fork.add_argument("new")

    remove = commands.add_parser("remove", help="delete a harness from the library")
    remove.add_argument("name")
    remove.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    return parser


def harness_program(argv: Sequence[str] | None = None) -> int:
    """Entry point of ``zettcode harness``; 0 done, 1 failed, 2 for bad arguments."""
    from zettcode.engine.harness_library import LibraryError

    args = build_parser().parse_args(argv)
    try:
        config = _config()
        if args.command == "list":
            return _list(config, as_json=args.json)
        if args.command == "show":
            return _show(config, args.name)
        if args.command == "add":
            return _add(config, args.source, args.name, yes=args.yes)
        if args.command == "update":
            return _update(config, args.name, force=args.force, yes=args.yes)
        if args.command == "fork":
            return _done(config, "forked", _fork(config, args.name, args.new))
        return _remove(config, args.name, yes=args.yes)
    except KeyboardInterrupt:
        print("zettcode harness: interrupted; nothing further was changed", file=sys.stderr)
        return EXIT_INTERRUPTED
    except LibraryError as error:
        print(f"zettcode harness: {error}", file=sys.stderr)
        return EXIT_FAILED
    except (OSError, ValueError) as error:
        print(f"zettcode harness: {error}", file=sys.stderr)
        return EXIT_FAILED


def _config() -> ZettCodeConfig:
    """Read the settings without requiring a model: the command may run on a machine that is not set up yet."""
    from zettcode.config import load_config

    return load_config(Path.cwd(), require_models=False)


def _confirm(question: str, *, yes: bool) -> bool:
    """Ask a yes/no question; with ``-y`` it is yes, and with no terminal to ask on it is a failure, said aloud.

    A reader who answered no has done what they meant (the caller returns 0); a script with nothing to ask on has not,
    so it stops with the reason rather than reporting a decision nobody made.
    """
    from zettcode.engine.harness_library import LibraryError

    if yes:
        return True
    if not sys.stdin.isatty():
        raise LibraryError("nothing to ask on; pass -y to confirm without a terminal")
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def _table(rows: Sequence[tuple[str, ...]]) -> str:
    """Return rows as left-aligned columns, two spaces apart."""
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip() for row in rows
    )


def _manifest_line(entry: Entry) -> tuple[str, str, str]:
    """Return ``(version, tools, description)`` of an entry's first repository, read from its files."""
    from zett_agent.jit_harness.manifest import read_manifest

    for repository in entry.repositories:
        try:
            manifest = read_manifest(entry.path / repository)
        except ValueError:
            continue
        return manifest.version, ", ".join(manifest.tools) or "-", manifest.description
    return "-", "-", "-"


def _state(config: ZettCodeConfig, entry: Entry) -> str:
    """Return the words after an entry's name in the list: whether it is in use, and whether it was changed."""
    from zettcode.engine.harness_library import update_state

    parts = []
    if config.harness_use == entry.name:
        parts.append("in use")
    state = update_state(entry)
    if state != "ok":
        parts.append({"damaged": "record damaged", "missing": "repository missing"}.get(state, state))
    return ", ".join(parts)


def _list(config: ZettCodeConfig, *, as_json: bool) -> int:
    """Print the library, as a table or as JSON."""
    from zettcode.engine.harness_library import entries

    found = entries(config)
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": entry.name,
                        "repositories": list(entry.repositories),
                        "origin": entry.origin,
                        "commit": entry.commit,
                        "in_use": config.harness_use == entry.name,
                        "modified": _modified(entry),
                        "state": _update_state(entry),
                    }
                    for entry in found
                ],
                indent=2,
            )
        )
        return EXIT_OK
    dangling = bool(config.harness_use) and config.harness_use not in {entry.name for entry in found}
    note = f"\n[harness] use = {config.harness_use!r} names a harness that is not in the library." if dangling else ""
    if not found:
        print("The library is empty. `zettcode harness add owner/repo` installs one from GitHub." + note)
        return EXIT_OK
    rows = [("NAME", "VERSION", "TOOLS", "SOURCE", "COMMIT", "STATE")]
    for entry in found:
        version, tools, _ = _manifest_line(entry)
        rows.append((entry.name, version, tools, entry.origin, entry.commit[:10] or "-", _state(config, entry)))
    print(_table(rows))
    if note:
        print(note)
    return EXIT_OK


def _update_state(entry: Entry) -> str:
    """Return ``ok``, ``changed``, ``missing`` or ``damaged``: what an update would find."""
    from zettcode.engine.harness_library import update_state

    return update_state(entry)


def _modified(entry: Entry) -> bool | None:
    """Return whether the entry changed since it was installed (``None``: nothing to compare)."""
    from zettcode.engine.harness_library import modified

    return modified(entry)


def _show(config: ZettCodeConfig, name: str) -> int:
    """Print one entry: where it is, where it came from, and what is in it."""
    from zett_agent.jit_harness.manifest import read_manifest

    from zettcode.engine.harness_library import get

    entry = get(config, name)
    print(f"{entry.name}  ({entry.path})")
    print(f"  source: {entry.origin}" + (f" at {entry.commit}" if entry.commit else ""))
    state = _state(config, entry)
    if state:
        print(f"  state:  {state}")
    for repository in entry.repositories:
        print(f"\n  repository {repository}")
        try:
            manifest = read_manifest(entry.path / repository)
        except ValueError as error:
            print(f"    (not readable: {error})")
            continue
        print(f"    version:     {manifest.version}")
        print(f"    description: {manifest.description}")
        print(f"    tools:       {', '.join(manifest.tools) or '-'}")
    return EXIT_OK


def _summary(prepared: Prepared, name: str) -> str:
    """Return what the reader sees before a download is kept."""
    candidate = prepared.candidate
    lines = [
        f"{candidate.name} {candidate.version}  (will be kept as `{name}`)",
        f"  {candidate.description}",
        f"  source:  {prepared.source.shown()} at {prepared.commit}",
        f"  tools:   {', '.join(candidate.tools) or '-'}",
    ]
    if candidate.banned:
        lines.append(f"  banned:  {', '.join(candidate.banned)}")
    lines.append(f"  files:   {len(candidate.files)} ({candidate.size:,} bytes)")
    lines.extend(f"    {path}" for path in candidate.files[:MAX_LISTED_FILES])
    if len(candidate.files) > MAX_LISTED_FILES:
        lines.append(f"    ... and {len(candidate.files) - MAX_LISTED_FILES} more")
    return "\n".join(lines)


def _add(config: ZettCodeConfig, text: str, name: str | None, *, yes: bool) -> int:
    """Download, show, ask, keep."""
    from zettcode.engine.harness_library import install, library_root, parse_source, prepare, valid_name

    source = parse_source(text)
    if name is not None:
        valid_name(name)
        if (library_root(config) / name).exists():
            print(
                f"zettcode harness: `{name}` is already in the library: `update` it, or pass another --as",
                file=sys.stderr,
            )
            return EXIT_FAILED
    print(f"Downloading {source.shown()} ...")
    with tempfile.TemporaryDirectory(prefix="zettcode-harness-") as work:
        prepared = prepare(source, Path(work))
        chosen = name or prepared.candidate.name
        if (library_root(config) / chosen).exists():
            print(f"zettcode harness: `{chosen}` is already in the library: `update` it, or pass --as", file=sys.stderr)
            return EXIT_FAILED
        print(_summary(prepared, chosen))
        print(f"\n{CAUTION}")
        if not _confirm(f"Keep it as `{chosen}`?", yes=yes):
            print("Nothing was kept.")
            return EXIT_OK
        entry = install(config, prepared, name=name)
    return _done(config, "installed", entry)


def _changes(old: Path, prepared: Prepared) -> list[str]:
    """Return what an update would change: the version, the tools, and which files come, go or differ."""
    from zett_agent.jit_harness.manifest import read_manifest

    lines: list[str] = []
    try:
        before = read_manifest(old)
    except (ValueError, OSError):
        before = None
    after = prepared.candidate
    if before is not None:
        if before.version != after.version:
            lines.append(f"version: {before.version} -> {after.version}")
        gone = sorted(set(before.tools) - set(after.tools))
        new = sorted(set(after.tools) - set(before.tools))
        if gone:
            lines.append(f"tools removed: {', '.join(gone)}")
        if new:
            lines.append(f"tools added: {', '.join(new)}")
    from zettcode.engine.harness_library import tree_fingerprints

    before_files = tree_fingerprints(old) if old.is_dir() else {}
    after_files = tree_fingerprints(prepared.directory)
    added = sorted(set(after_files) - set(before_files))
    removed = sorted(set(before_files) - set(after_files))
    changed = sorted(path for path in set(after_files) & set(before_files) if after_files[path] != before_files[path])
    for label, paths in (("files added", added), ("files removed", removed), ("files changed", changed)):
        if paths:
            lines.append(
                f"{label}: {', '.join(paths[:MAX_LISTED_FILES])}" + (" ..." if len(paths) > MAX_LISTED_FILES else "")
            )
    return lines or ["the files are the same, only the commit differs"]


def _update(config: ZettCodeConfig, name: str, *, force: bool, yes: bool) -> int:
    """Fetch the source again, show what would change, and replace the repository after a yes."""
    from zettcode.engine.harness_library import get, recorded_repository, refetch, update, update_refusal

    entry = get(config, name)
    refusal = update_refusal(config, entry, force=force)
    if refusal is not None:
        print(f"zettcode harness: {refusal}", file=sys.stderr)
        return EXIT_FAILED
    with tempfile.TemporaryDirectory(prefix="zettcode-harness-") as work:
        prepared = refetch(entry, Path(work))
        if prepared.commit == entry.commit:
            print(f"`{name}` is already at {entry.commit[:10]}.")
            return EXIT_OK
        previous = recorded_repository(entry)
        folder = entry.path / previous if previous is not None else entry.path / "(no recorded repository)"
        print(f"{name}: {entry.commit[:10]} -> {prepared.commit[:10]}")
        for line in _changes(folder, prepared):
            print(f"  {line}")
        print(f"\n{CAUTION}")
        if not _confirm(f"Update `{name}`?", yes=yes):
            print("Nothing was changed.")
            return EXIT_OK
        updated = update(config, entry, prepared, force=force)
    return _done(config, "updated", updated)


def _fork(config: ZettCodeConfig, name: str, new: str) -> Entry:
    """Copy a harness under a new name."""
    from zettcode.engine.harness_library import fork

    return fork(config, name, new)


def _done(config: ZettCodeConfig, verb: str, entry: Entry) -> int:
    """Say what was done, and how to have the sessions use it."""
    print(f"{verb} `{entry.name}`" + (f" ({', '.join(entry.repositories)})" if entry.repositories else ""))
    if config.harness_use != entry.name:
        print(f"In ZettCode, `/harness use {entry.name}` makes every session work in it.")
    return EXIT_OK


def _remove(config: ZettCodeConfig, name: str, *, yes: bool) -> int:
    """Delete one entry after a yes."""
    from zettcode.engine.harness_library import get, remove

    entry = get(config, name)
    if not _confirm(f"Delete `{name}` and everything in {entry.path}?", yes=yes):
        print("Nothing was deleted.")
        return EXIT_OK
    remove(config, name)
    print(f"removed `{name}`")
    return EXIT_OK
