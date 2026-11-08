"""The agent's workspace memory and its guide to background daemons.

The personal memory is ``~/memory/personal``; the project memory is one folder per Git root under
``~/.zettcode/memory``, shared by its worktrees. Each holds a ``MEMORY.md`` index and the topic files the model
writes. :class:`~zettcode.memory.extension.MemoryExtension` puts both indexes and the maintenance rules in every
request's system messages; :class:`~zettcode.memory.extension.DaemonGuideExtension` tells the model how to start and
reach a background agent when it has a shell and the messaging tool. The plugin `memory` registers the first and
`daemon-guide` the second, both published through :mod:`zettcode.memory.plugin` under the ``zettcode.plugin`` group.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
