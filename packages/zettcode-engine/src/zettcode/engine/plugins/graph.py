"""Put plugins in dependency order, and say which of them cannot be loaded at all.

A plugin names the plugins it needs in :attr:`~zettcode.engine.plugins.plugin.Plugin.deps`. :func:`order` turns those
names into a topological order — a plugin is always activated after every plugin it needs — and into the reasons a
plugin has to be left out: a plugin it needs is absent, or the needs go round in a circle. The order is stable: among
the plugins that are ready, the one that was offered first goes first, so a graph with no edges keeps exactly the
order it was given in, and the built-in plugins stay ahead of the installed ones unless one of them needs a later one.

The module knows names and edges only, not plugins, so it is one pure function that a test can feed strings.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Node:
    """One plugin as the graph sees it: the name it is known by and the names it needs."""

    name: str
    deps: tuple[str, ...] = ()


def order(nodes: list[Node]) -> tuple[list[int], dict[int, str]]:
    """Return the activation order of ``nodes`` and the reason each node that cannot be activated has.

    Args:
        nodes: The candidates, in the order they were offered.

    Returns:
        The indices of the nodes that can be activated, dependencies first, and ``{index: why}`` for the ones that
        cannot. A node that needs a failed node fails too, so the reasons name the first thing missing and the chain
        it took down is in the later reasons. A name offered twice belongs to its first node; the second is ordered
        like any other and left for the loader to refuse as a duplicate.
    """
    owner: dict[str, int] = {}
    for index, node in enumerate(nodes):
        owner.setdefault(node.name, index)

    failed: dict[int, str] = {}
    changed = True
    while changed:
        changed = False
        for index, node in enumerate(nodes):
            if index in failed:
                continue
            for dep in node.deps:
                if dep == node.name:
                    failed[index] = f"plugin {node.name!r} lists itself in deps"
                elif dep not in owner:
                    failed[index] = f"needs plugin {dep!r}, which is not installed or is turned off"
                elif owner[dep] in failed:
                    failed[index] = f"needs plugin {dep!r}, which cannot be loaded"
                else:
                    continue
                changed = True
                break

    alive = [index for index in range(len(nodes)) if index not in failed]
    waiting = {index: {owner[dep] for dep in nodes[index].deps if owner[dep] != index} for index in alive}
    ordered: list[int] = []
    done: set[int] = set()
    remaining = list(alive)
    while remaining:
        ready = next((index for index in remaining if waiting[index] <= done), None)
        if ready is None:
            break
        ordered.append(ready)
        done.add(ready)
        remaining.remove(ready)

    for index in remaining:
        cycle = _cycle(index, nodes, owner, set(remaining))
        failed[index] = (
            f"dependency cycle: {' -> '.join(cycle)}" if cycle else "needs a plugin that is part of a dependency cycle"
        )
    return ordered, failed


def _cycle(start: int, nodes: list[Node], owner: dict[str, int], within: set[int]) -> list[str]:
    """Return the names on a path from ``start`` back to itself inside ``within``, or ``[]`` when it is on none."""
    stack: list[tuple[int, list[int]]] = [(start, [start])]
    seen: set[int] = set()
    while stack:
        index, path = stack.pop()
        for dep in nodes[index].deps:
            target = owner.get(dep)
            if target is None or target not in within:
                continue
            if target == start:
                return [nodes[step].name for step in (*path, start)]
            if target not in seen:
                seen.add(target)
                stack.append((target, [*path, target]))
    return []
