# Workspace memory

Memory is off by default; the `memory` plugin chooses that. Turn it on for the next start:

```toml
[plugins]
enable = ["memory"]
```

ZettCode then keeps two durable memories, both outside the project:

| Scope | Folder | What it holds |
| --- | --- | --- |
| Personal | `~/memory/personal/` | You: role, background, how you like to work, corrections you gave. Every workspace shares it. |
| Project | `~/.zettcode/memory/<repo>-<digest>/` | One repository: decisions made elsewhere, context code and git do not carry, feedback about this project. Its worktrees share it. |

Each folder holds a `MEMORY.md` index and the topic files it points at. The index is read on every request; a topic
file is read by the agent with its ordinary file tools when the index says it matters. One index line is one
pointer, at most 150 characters. An index is loaded up to 200 lines or 25,000 bytes, and past either limit the
request says which limit it hit. A memory survives sessions and restarts.

## When it is written

The agent writes a topic file when it learns something durable: a correction or a confirmation, a decision taken
elsewhere, a reference it will need again. It is told to correct or delete what proved wrong, merge duplicates,
drop stale entries, and write dates in full (`2026-03-05`, not `Thursday`). A long session leaves the index stale
more often than it leaves a topic file wrong.

It is told not to store what the code, git or `AGENTS.md` already says, nor the current task or a debugging recipe.

## Inspecting and clearing

The folders may not exist until there is something worth keeping. Read them at any time:

```bash
cat ~/memory/personal/MEMORY.md
cat ~/.zettcode/memory/*/MEMORY.md
```

Delete a folder to forget that memory: the next session starts empty and the agent builds it again. If you tell
the agent to ignore memory, it treats the index as empty.

## Privacy

Memory belongs to the agent, not to your repository: nothing is written inside the project and ZettCode never
commits it. Both indexes are sent to your model endpoint on every request, so keep secrets out of them.

## Next steps

- [Project instructions](/guide/instructions): what `AGENTS.md` does, and how it differs from memory.
- [Plugins](/guide/plugins): switching a plugin on, and what a plugin may register.
- [Configuration](/guide/config#optional-settings-reference): the `[plugins]` table and the rest.
