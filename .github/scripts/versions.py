"""One version for everything this repository publishes, and the checks and the write that keep it so.

The program and the parts it is built from already share one number: every ``pyproject.toml`` of those distributions has
``dynamic = ["version"]`` and ``[tool.hatch.version] path`` pointing at ``packages/zettcode-engine/src/zettcode/version.py``,
so a release is one edit and one tag. The plugins were the exception — a plugin is released on its own line, so it keeps
its own ``__version__`` — and with four of them the tree held four numbers that had to be read together to know what a
checkout was. They are now the same number as the program: a plugin is built from the same source at the same commit, and
a reader who sees ``zettcode-monitor 0.4.5`` and ``zettcode 0.4.5`` can tell they belong together.

This module is the one place that knows what "the same version" means, and the two things that need it call it:

* ``--check`` (the test ``test_versions.py`` and a step of ``release.yml``) reports every disagreement: a plugin's
  ``__version__`` that is not the program's, and a requirement on one of our own distributions whose floor is not this
  version or whose ceiling is not the next minor line. It writes nothing.
* ``--set X.Y.Z`` writes the version into every place it lives — the engine's ``version.py``, each plugin's
  ``__init__.py``, and every ``zettcode-*>=X.Y.Z,<MAJ.MIN`` requirement in the ``pyproject.toml`` of every distribution
  under ``packages/`` — so the bump a release starts with is one command rather than a search. It refuses a
  requirement written with a specifier it does not own (``==``, ``~=``, a bare ``>``) before it writes anything, and
  checks the whole tree again afterwards, so a rewrite it could not find fails instead of leaving half a tree behind.

Why the requirement floor moves with the version: the distributions are published together under one tag, so
``zettcode 0.5.0`` means ``zettcode-engine 0.5.0`` was published with it; a floor of ``0.4`` would let a resolver pair a
new program with an old part that has never been tested against it. The ceiling is the next minor line, which is where
incompatible changes are allowed to land.

A plugin keeps a literal ``__version__`` rather than reading the engine's file: a wheel built from its sdist on a
machine without this repository must be buildable, and ``[tool.hatch.version] path = "../zettcode-engine/…"`` is a path
that only exists inside the checkout. The literal is what ``--set`` rewrites, and what ``--check`` compares.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # the release workflow runs 3.12; this keeps the script runnable on the oldest version the project claims
    import tomli as tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: The one file the program's version is written in, relative to the repository root.
VERSION_FILE = pathlib.Path("packages/zettcode-engine/src/zettcode/version.py")

#: What a requirement on one of our own distributions looks like: the name, then the range this module owns.
_REQUIREMENT = re.compile(r"^(?P<name>zettcode[A-Za-z0-9._-]*)(?P<extras>\[[^\]]*\])?\s*(?P<rest>.*)$")

#: The part of that range this module writes and checks.
_RANGE = re.compile(r">=(?P<floor>[0-9]+(?:\.[0-9]+)*)\s*,\s*<(?P<ceiling>[0-9]+(?:\.[0-9]+)*)")


class VersionError(Exception):
    """The tree cannot be read as one versioned program, or asked to become one."""


def version_of(module: pathlib.Path) -> str:
    """Return the ``__version__`` a module assigns at the top level, read without importing it."""
    for node in ast.parse(module.read_text(encoding="utf-8")).body:
        value: ast.expr | None = None
        targets: tuple[ast.expr, ...]
        if isinstance(node, ast.Assign):
            targets, value = tuple(node.targets), node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = (node.target,), node.value
        else:
            continue
        if not any(getattr(target, "id", "") == "__version__" for target in targets):
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    raise VersionError(f'{module}: no __version__ = "…" at the top level')


def major_minor(version: str) -> str:
    """Return ``"MAJOR.MINOR"`` for a version, which is the ceiling line that follows it."""
    parts = version.split(".")
    while len(parts) < 2:
        parts.append("0")
    return f"{int(parts[0])}.{int(parts[1]) + 1}"


def _plugin_modules(root: pathlib.Path) -> list[pathlib.Path]:
    """Return the module each plugin writes its own version in, from the `path` its pyproject names."""
    found: list[pathlib.Path] = []
    for project in sorted((root / "packages").glob("*/pyproject.toml")):
        settings = tomllib.loads(project.read_text(encoding="utf-8"))
        if not settings.get("tool", {}).get("zettcode", {}).get("plugin"):
            continue
        path = settings.get("tool", {}).get("hatch", {}).get("version", {}).get("path")
        if not isinstance(path, str):
            raise VersionError(f"{project}: a plugin needs [tool.hatch.version] path")
        found.append(project.parent / path)
    return found


def _name_of(requirement: str) -> str:
    """Return the distribution a requirement names, without extras, range or marker."""
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement.strip())
    return match.group(0) if match else ""


def _requirements(root: pathlib.Path) -> list[tuple[pathlib.Path, str, int]]:
    """Return every requirement on one of our distributions, as the file, the text and its first line number.

    Both the program's dependencies and its extras are read: a plugin is named in an extra, and that is where two of
    the three ranges a reader feels live. A requirement written twice in one file — the `all` extra of the program
    names the same three plugins an extra each names — is one entry: every occurrence is rewritten together.
    """
    found: list[tuple[pathlib.Path, str, int]] = []
    for project in sorted((root / "packages").glob("*/pyproject.toml")):
        settings = tomllib.loads(project.read_text(encoding="utf-8"))
        table = settings.get("project", {})
        wanted: list[str] = list(table.get("dependencies", []))
        for items in table.get("optional-dependencies", {}).values():
            wanted.extend(items)
        lines = project.read_text(encoding="utf-8").splitlines()
        seen: set[str] = set()
        for requirement in wanted:
            if requirement in seen or not _name_of(requirement).startswith("zettcode"):
                continue
            seen.add(requirement)
            # -1 when the text does not hold the requirement as one string: a TOML string joined across lines reads
            # as one requirement and is written as two, and a rewrite that searched for it would find nothing.
            found.append((project, requirement, next((n for n, line in enumerate(lines) if requirement in line), -1)))
    return found


#: Characters that mean a requirement already carries a specifier this module does not own: ``==``, ``~=``, ``>``,
#: ``!=``, or a bare ``<``. Appending our range to one of those writes a requirement nothing can parse.
_FOREIGN = re.compile(r"[=!~<>]")


def _foreign_specifier(requirement: str) -> str:
    """Return the specifier a requirement carries that is not ours, or an empty string.

    The rule owns ``>=x,<y`` and nothing else. A requirement pinned with ``==``, or written ``~=0.4``, is a decision
    somebody made by hand, and rewriting it by appending our range to it would produce a line pip cannot read — so it
    is refused, naming the line, rather than half-rewritten.
    """
    body = requirement.partition(";")[0]
    match = _RANGE.search(body)
    if match is not None:
        return "" if not _FOREIGN.search(body[: match.start()] + body[match.end() :]) else body
    found = _FOREIGN.search(body)
    return body if found is not None else ""


def _unwritable(root: pathlib.Path, version: str) -> list[str]:
    """Return the requirements ``--set`` must refuse rather than rewrite, as sentences naming the file.

    Two shapes: one that carries a specifier this module does not own, and one the file does not hold as a single
    string — a TOML multi-line string, whose value and whose text are different things. Either would be written wrong
    or skipped in silence, so the write refuses before it starts.
    """
    refused: list[str] = []
    for project, requirement, number in _requirements(root):
        where = f"{project.relative_to(root)}:{number + 1}" if number >= 0 else str(project.relative_to(root))
        if _foreign_specifier(requirement):
            refused.append(
                f'{where}: "{requirement}" carries a specifier this cannot rewrite; write it as '
                f"{_with_range(_name_of(requirement), version)}"
            )
        elif number < 0:
            refused.append(f'{where}: "{requirement}" is not written as one string this can find; write it on one line')
    return refused


def _with_range(requirement: str, version: str) -> str:
    """Return the same requirement with our range on it, leaving a marker after ``;`` as it was."""
    body, separator, marker = requirement.partition(";")
    match = _RANGE.search(body)
    if match is not None:
        body = body[: match.start()] + f">={version},<{major_minor(version)}" + body[match.end() :]
    else:
        body = body.rstrip() + f">={version},<{major_minor(version)}"
    return body + separator + marker


def _problems(root: pathlib.Path) -> list[str]:
    """Return every way the tree disagrees with "one version", as sentences a reader can act on."""
    version = version_of(root / VERSION_FILE)
    wanted_ceiling = major_minor(version)
    problems: list[str] = []
    for module in _plugin_modules(root):
        found = version_of(module)
        if found != version:
            problems.append(f"{module.relative_to(root)}: __version__ is {found}, the program is {version}")
    problems.extend(_unwritable(root, version))
    for project, requirement, number in _requirements(root):
        if number < 0:  # already reported as unwritable
            continue
        match = _RANGE.search(requirement)
        where = f"{project.relative_to(root)}:{number + 1}"
        if _foreign_specifier(requirement):
            continue
        if match is None:
            problems.append(
                f'{where}: "{requirement}" names one of ours with no range; it should be {_with_range(requirement, version)}'
            )
        elif match.group("floor") != version or match.group("ceiling") != wanted_ceiling:
            problems.append(f'{where}: "{requirement}" should be {_with_range(requirement, version)}')
    return problems


def _rewrite_module(module: pathlib.Path, version: str) -> bool:
    """Set the ``__version__`` a module assigns, and say whether the file changed."""
    text = module.read_text(encoding="utf-8")
    replaced, count = re.subn(
        r'^__version__ = "[^"]*"', f'__version__ = "{version}"', text, count=1, flags=re.MULTILINE
    )
    if count != 1:
        raise VersionError(f'{module}: expected one top-level __version__ = "…" line')
    if replaced == text:
        return False
    module.write_text(replaced, encoding="utf-8")
    return True


def _rewrite_requirements(root: pathlib.Path, version: str) -> list[pathlib.Path]:
    """Point every requirement on one of our distributions at ``version``, and return the files it changed.

    Every occurrence of a requirement is replaced, not only the first: the program names the same plugin once in its
    own extra and once in the ``all`` extra, and a range that disagrees with itself is worse than either.
    """
    changed: list[pathlib.Path] = []
    for project, requirement, _number in _requirements(root):
        wanted = _with_range(requirement, version)
        if wanted == requirement:
            continue
        text = project.read_text(encoding="utf-8")
        if requirement not in text:
            continue
        project.write_text(text.replace(requirement, wanted), encoding="utf-8")
        changed.append(project)
    return sorted(set(changed))


def set_version(root: pathlib.Path, version: str) -> list[str]:
    """Write ``version`` everywhere it lives, and return one line per file that changed.

    What a release leans on: a requirement this module cannot rewrite safely — one with a specifier it does not own
    (``==``, ``~=``, a bare ``>``), or one the file does not hold as a single string, which is what a TOML string
    joined across lines reads as — is refused *before* anything is written, naming the file and line, because
    appending our range to ``==0.4.0`` writes a line pip cannot read and searching for text that is not there writes
    nothing at all.

    The check that follows the writes is a backstop for this script rather than for a reader: every shape a
    ``pyproject.toml`` can be written in has already been refused, so what is left is a bug in the replacement itself
    — a requirement the rewrite walked past. It fails loudly with "the write went through", because that is true: the
    files are not rolled back, and a release discovering it at PyPI is worse than one discovering it here.

    Raises:
        VersionError: The version is not ``MAJOR.MINOR.PATCH``, a requirement cannot be rewritten safely, or the tree
            still disagrees after the write.
    """
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise VersionError(f"{version!r} is not MAJOR.MINOR.PATCH")
    refused = _unwritable(root, version)
    if refused:
        raise VersionError("these requirements cannot be rewritten, so nothing was written:\n" + "\n".join(refused))
    changed: list[str] = []
    target = root / VERSION_FILE
    before = version_of(target)
    if _rewrite_module(target, version):
        changed.append(f"{target.relative_to(root)}: {before} -> {version}")
    for module in _plugin_modules(root):
        was = version_of(module)
        if _rewrite_module(module, version):
            changed.append(f"{module.relative_to(root)}: {was} -> {version}")
    changed.extend(
        f"{path.relative_to(root)}: requirements -> >= {version},< {major_minor(version)}"
        for path in _rewrite_requirements(root, version)
    )
    left = _problems(root)
    if left:
        raise VersionError(f"the write went through, but these places are still not on {version}:\n" + "\n".join(left))
    return changed


def main(argv: list[str] | None = None) -> int:
    """Check the tree, or move it to one version; return the exit status."""
    parser = argparse.ArgumentParser(
        prog="versions.py",
        description="One version for the program and every distribution beside it, including the plugins.",
    )
    choosing = parser.add_mutually_exclusive_group(required=True)
    choosing.add_argument("--check", action="store_true", help="report every disagreement and exit non-zero if any")
    choosing.add_argument("--set", metavar="VERSION", help="write MAJOR.MINOR.PATCH into every place the version lives")
    arguments = parser.parse_args(argv)
    try:
        if arguments.check:
            problems = _problems(ROOT)
            if problems:
                print("\n".join(problems))
                print(
                    f"\n{len(problems)} place(s) are not at the program's version. Run `make version VERSION=<x.y.z>`."
                )
                return 1
            print(f"every distribution is {version_of(ROOT / VERSION_FILE)}")
            return 0
        changed = set_version(ROOT, arguments.set)
    except VersionError as error:
        print(f"versions.py: {error}", file=sys.stderr)
        return 2
    print("\n".join(changed) or "nothing changed")
    print("\nNow regenerate the lock: `uv lock`.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
