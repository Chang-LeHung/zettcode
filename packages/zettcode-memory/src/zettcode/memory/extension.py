"""The two memories the model starts a request with, and the guide to background agents.

Personal memory belongs to the reader and lives at ``~/memory/personal``; project memory belongs to the repository
(every worktree shares it) and lives under ``~/.zettcode/memory``. Each has a ``MEMORY.md`` index, which is the only
part included in a request; topic files are read on demand with the ordinary file tools.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from zett_agent.agent import AgentRunContext
from zett_agent.extensions.base import AgentExtension
from zett_agent.messages import SystemMessage

from zettcode.engine.harness_paths import workspace_directory_name

#: The global personal memory, shared by every workspace.
PERSONAL_MEMORY_ROOT = Path.home() / "memory" / "personal"

#: Where project memories live, one folder per repository.
PROJECT_MEMORY_ROOT = Path.home() / ".zettcode" / "memory"

#: The index inside a memory folder. Only this file goes into the request.
MEMORY_INDEX = "MEMORY.md"

#: How much of one index the request carries. Lines catch the ordinary case; bytes catch a few enormous lines.
MAX_ENTRYPOINT_LINES = 200
MAX_ENTRYPOINT_BYTES = 25_000

#: The most a pointer line in the index takes. The index is a table of contents, never the memory itself.
MAX_INDEX_LINE_CHARS = 150


def canonical_git_root(workspace: Path) -> Path:
    """Return the repository a workspace belongs to, following a worktree's ``.git`` file to its common directory."""
    start = workspace.resolve()
    for candidate in (start, *start.parents):
        marker = candidate / ".git"
        if marker.is_dir():
            return candidate
        if not marker.is_file():
            continue
        try:
            text = marker.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return candidate
        if not text.startswith("gitdir:"):
            return candidate
        git_dir = Path(text.removeprefix("gitdir:").strip()).expanduser()
        if not git_dir.is_absolute():
            git_dir = (candidate / git_dir).resolve()
        try:
            common = (git_dir / "commondir").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return candidate
        return (git_dir / common).resolve().parent
    return start


def project_memory_directory(root: Path, workspace: Path) -> Path:
    """Return the folder for one repository's memory, shared by its worktrees."""
    return root / workspace_directory_name(canonical_git_root(workspace))


def _index_text(directory: Path) -> tuple[str, str | None, str | None]:
    """Return ``(index text, which file, warning)`` from a memory folder, or empty when it has no index."""
    path = directory / MEMORY_INDEX
    if not path.is_file():
        return "", None, None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "", MEMORY_INDEX, "the index cannot be read"
    if not text:
        return "", MEMORY_INDEX, None
    return _bounded(text, MEMORY_INDEX)


def _bounded(text: str, name: str) -> tuple[str, str, str | None]:
    """Cut an index at the line and byte limits, saying which limit made the cut."""
    warnings: list[str] = []
    lines = text.splitlines()
    if len(lines) > MAX_ENTRYPOINT_LINES:
        lines = lines[:MAX_ENTRYPOINT_LINES]
        warnings.append(f"{MAX_ENTRYPOINT_LINES} lines")
    text = "\n".join(lines)
    if len(text.encode("utf-8")) > MAX_ENTRYPOINT_BYTES:
        cut = text.encode("utf-8")[:MAX_ENTRYPOINT_BYTES].decode("utf-8", "ignore")
        text = cut.rsplit("\n", 1)[0] if "\n" in cut else cut
        warnings.append(f"{MAX_ENTRYPOINT_BYTES} bytes")
    if not warnings:
        return text, name, None
    return text, name, "the index was cut at " + " and ".join(warnings)


_INTRO = """# Memory

Two memories, both outside the project and both loaded only through their `MEMORY.md` index:

- Personal: `{personal}` — the reader across workspaces: role, technical background, collaboration preferences,
  current focus and learning.
- Project: `{project}` — this repository, shared by its worktrees: context code and git do not carry, decisions,
  external references.

Read a topic file with your normal file tools when its index line is relevant; there is no memory tool.
"""

_RULES = """## Keeping memory

A topic file starts with frontmatter, then the note:

```markdown
---
name: Tests use a real database
description: retrieval key, not a human summary
type: user | feedback | project | reference
---
The note. **Why:** … **How to apply:** …
```

- `user`: the reader's role, background, preferences, current focus and learning.
- `feedback`: corrections *and* confirmations; only recording corrections makes you cautious and drifts from what
  the reader already approved.
- `project`: context code and git cannot show.
- `reference`: where an external thing lives.

Write the topic file, then add one index line: `- [Title](file.md) — when to read it`, at most {line_chars}
characters. Never put the note in the index. Indexes are loaded up to {lines} lines and {bytes} bytes; rewrite rather
than let them grow. Write absolute dates (`Thursday` becomes `2026-03-05`). Correct or delete a wrong memory, merge
duplicates and prune stale entries; do not leave old and new versions behind.

Do not store code patterns, paths inside this project, project structure, git history, debugging recipes, `AGENTS.md`
content, current task state or logs — even if asked. Keep the surprising, non-obvious part instead.

Before relying on a memory, check that the path, function or flag still exists. If the reader says to ignore memory,
treat both indexes as empty: do not apply, quote, compare or mention them.
"""

_MISSING = """No `{index}` yet. Create it when there is a first memory worth keeping, with a short `# Memory index`
line and one pointer per topic file.
"""


def _python_command() -> str:
    """Return the running interpreter, quoted for this platform's shell."""
    executable = sys.executable or "python"
    if os.name == "nt":
        return f'"{executable}"' if " " in executable else executable
    return shlex.quote(executable)


_DAEMON_GUIDE = """# Background agents (daemons)

Start one with the interpreter running this session:

    {python} -m zettcode daemon spawn --name <label> --title <title> --permission safe

It prints a session id. `{python} -m zettcode daemon list` lists daemons; `log <id>` shows one; `stop <id>` stops it
and keeps the record; `kill <id>` stops it and removes the record. Talk to it only with
`send_message(to="<session-id>", ...)`; answers arrive later. A daemon has nobody to ask: `spawn` defaults to
`--permission full`, so pass `safe` for a sandbox. Use it for work that should outlive this turn; keep work this turn
needs here. Tell the reader what you started.
"""


class MemoryExtension(AgentExtension):
    """Put both memory indexes and the rules for keeping them in the model's system messages.

    Args:
        project_root: The root of project memories; ``~/.zettcode/memory`` by default.
        personal_root: The global personal memory folder; ``~/memory/personal`` by default.
        workspace: The directory the project memory belongs to; the process working directory by default.
    """

    #: After project instructions and before the daemon guide.
    priority = 11

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        personal_root: Path | None = None,
        workspace: Path | None = None,
    ) -> None:
        """Keep the roots and the workspace; the folders are derived when a request needs them."""
        self.project_root = PROJECT_MEMORY_ROOT if project_root is None else Path(project_root).expanduser()
        self.personal_root = PERSONAL_MEMORY_ROOT if personal_root is None else Path(personal_root).expanduser()
        self.workspace = None if workspace is None else Path(workspace)

    def personal_directory(self) -> Path:
        """Return the global personal memory folder."""
        return self.personal_root

    def project_directory(self) -> Path:
        """Return this repository's memory folder, shared with its worktrees."""
        workspace = Path.cwd() if self.workspace is None else self.workspace
        return project_memory_directory(self.project_root, workspace)

    def instructions(self) -> str:
        """Return the two indexes and the rules, as one system message body."""
        personal, project = self.personal_directory(), self.project_directory()
        parts = [
            _INTRO.format(personal=personal, project=project),
            _RULES.format(line_chars=MAX_INDEX_LINE_CHARS, lines=MAX_ENTRYPOINT_LINES, bytes=MAX_ENTRYPOINT_BYTES),
        ]
        for title, directory in (("Personal", personal), ("Project", project)):
            text, name, warning = _index_text(directory)
            if not text:
                if warning:
                    parts.append(
                        f"## {title} index ({name})\n\n> {warning}. It is there but could not be read; "
                        f"rewrite `{MEMORY_INDEX}` when there is something to keep."
                    )
                else:
                    parts.append(f"## {title} index\n\n" + _MISSING.format(index=MEMORY_INDEX))
                continue
            heading = f"## {title} index ({name})"
            if warning:
                heading += f"\n\n> {warning}; rewrite the index"
            parts.append(f"{heading}\n\n{text}")
        return "\n\n".join(parts) + "\n"

    async def on_state(self, context: AgentRunContext) -> None:
        """Place the memory after the instructions already in the request."""
        content = self.instructions()
        if not content:
            return
        instructions = [message for message in context.state.messages if isinstance(message, SystemMessage)]
        context.add_message(SystemMessage(content=content), index=len(instructions))


class DaemonGuideExtension(AgentExtension):
    """Tell the model it may start a background agent, and how to reach the one it started.

    It is offered only when the request has both a shell and ``send_message``: without the shell it cannot start a
    daemon, and without the messaging tool it could not talk to one.
    """

    #: After the memory, so the two system messages have a stable order.
    priority = 12

    async def on_state(self, context: AgentRunContext) -> None:
        """Place the guide after the instructions already in the request."""
        if "bash" not in context.tools or "send_message" not in context.tools:
            return
        instructions = [message for message in context.state.messages if isinstance(message, SystemMessage)]
        context.add_message(
            SystemMessage(content=_DAEMON_GUIDE.format(python=_python_command())), index=len(instructions)
        )


__all__ = [
    "DaemonGuideExtension",
    "MAX_ENTRYPOINT_BYTES",
    "MAX_ENTRYPOINT_LINES",
    "MEMORY_INDEX",
    "MemoryExtension",
    "canonical_git_root",
    "project_memory_directory",
]
