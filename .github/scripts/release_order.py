"""Print the distributions the program is made of, in the order a release has to publish them.

The order is not a list anyone keeps: it is read from the `pyproject.toml` of every distribution under `packages/` that
is not a plugin (a plugin says `[tool.zettcode] plugin = true` and is released on its own line), from the
`zettcode-*` dependencies each one declares. A topological sort with alphabetical tie-breaks gives the same output on
every run, so `make build`, `release.yml` and the test that holds the rule all agree.

Printing to stdout is the interface: `release.yml` loops over the output and `make order` writes it to
`packages/order.txt` for a reader (that file is generated and not in git). A dependency on a name nobody ships, or a
cycle, is an error rather than a short list.
"""

from __future__ import annotations

import pathlib
import re
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # the release workflow runs 3.12; this keeps the script runnable on the oldest version the project claims
    import tomli as tomllib

ROOT = pathlib.Path(__file__).resolve().parents[2]


class Cycle(Exception):
    """A dependency the order cannot satisfy."""


def _described(directory: pathlib.Path) -> tuple[str, set[str], bool]:
    """Return a distribution's name, the distributions of ours it needs, and whether it is a plugin."""
    settings = tomllib.loads((directory / "pyproject.toml").read_text(encoding="utf-8"))
    project = settings["project"]
    # `zettcode-engine[tiktoken]>=0.3,<0.4; python_version < "3.11"` — the name is everything before the first
    # character a requirement can use for something else.
    needed = {
        match.group(0)
        for line in project["dependencies"]
        if line.startswith("zettcode")
        for match in [re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)]
        if match
    }
    plugin = bool(settings.get("tool", {}).get("zettcode", {}).get("plugin"))
    return project["name"], needed, plugin


def ordered() -> list[str]:
    """Return the program's distributions, dependencies first.

    Raises:
        Cycle: When a dependency names a distribution this repository does not ship, or the graph has a loop.
    """
    found: dict[str, set[str]] = {}
    plugins: set[str] = set()
    for project in sorted((ROOT / "packages").glob("*/pyproject.toml")):
        name, needed, plugin = _described(project.parent)
        if plugin:
            plugins.add(name)
        else:
            found[name] = needed

    # An edge to a name that is not one of these would silently disappear from the graph: the readiness check only
    # compares against what is left, so a typo — or a program distribution that started needing a plugin, which is
    # published on another line — would be dropped instead of ordered.
    unknown = {need for needed in found.values() for need in needed} - set(found) - plugins
    if unknown:
        raise Cycle(f"these dependencies name nothing the program is made of: {sorted(unknown)}")

    remaining = dict(found)
    order: list[str] = []
    while remaining:
        ready = sorted(name for name, needed in remaining.items() if not needed & remaining.keys())
        if not ready:
            raise Cycle(f"these distributions need each other, or something nobody ships: {sorted(remaining)}")
        # One at a time, smallest first: a batch would let a name that became ready mid-batch jump ahead of one that
        # was already waiting, and the output would depend on the batch size rather than the graph.
        order.append(ready[0])
        del remaining[ready[0]]
    return order


def main() -> int:
    try:
        for name in ordered():
            print(name)
    except Cycle as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
