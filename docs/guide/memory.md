# Workspace memory

Memory is off by default: the plugin chooses that. Turn it on for the next start:

```toml
[plugins]
enable = ["memory"]
```

ZettCode then gives the agent two durable memories, both outside the project:

```text
~/memory/personal/                 the reader, across every workspace
  MEMORY.md                        the index, included in every request
  role.md
  preferences.md

~/.zettcode/memory/<repo>-<digest>/ the repository, shared by its worktrees
  MEMORY.md                        the index, included in every request
  decisions.md
  testing.md
```

`MEMORY.md` is a table of contents, not the memory itself. It is read on every request; the topic files are read by the
agent on demand with its ordinary file tools. A memory survives sessions and restarts.

## What each scope holds

**Personal memory** is about the reader: role, technical background, how they like to work, what they are doing or
learning now, and corrections or confirmations they have given. It follows the reader from repository to repository.

**Project memory** is about one repository: context that code and git do not carry, decisions made elsewhere,
external references, and feedback about this project. It lives in one folder per canonical Git root, so every worktree
of the repository shares it.

## What a memory looks like

Each topic file starts with frontmatter and ends with why it matters:

```markdown
---
name: Tests use a real database
description: integration tests connect to the real database; used to judge relevance later
type: feedback
---
The tests connect to a real database. Then **Why:** mocks hid a migration failure.
Then **How to apply:** run the database container before the suite.
```

The four types are `user`, `feedback`, `project` and `reference`. The description is the retrieval key, not a human
summary: it is what a later request searches for. `feedback` records both corrections and confirmations — remembering
only what went wrong makes an agent cautious and pulls it away from approaches the reader already approved.

The index has one pointer per topic, at most 150 characters:

```markdown
- [Tests use a real database](testing.md) — before changing the integration suite
```

An index is loaded up to 200 lines and 25 KB. Past either limit the rest is cut and the request says which limit was
hit. The agent is told to rewrite the index rather than let it grow.

## Keeping it current

Memory decays. The agent is told to correct or delete a memory that was proved wrong, merge duplicates, drop stale
entries, and turn relative dates into absolute ones (`Thursday` becomes `2026-03-05`) when writing. A long session
leaves the index stale more often than it leaves a topic file wrong.

It is also told not to store what the code, git history or `AGENTS.md` already says, and not to keep the current task
or a debugging recipe. When the reader asks for one of those, the useful memory is the surprising part, not the log.

Before recommending from memory, the agent is told to verify: a path still exists, a function or flag still exists, a
command still works. Memory saying something existed is not proof that it exists now.

## What the reader sees

The folders may not exist until the agent has something worth keeping. You can read them at any time:

```bash
cat ~/memory/personal/MEMORY.md
cat ~/.zettcode/memory/*/MEMORY.md
```

Deleting a folder forgets that memory; the next session starts empty and the agent builds it again. The memory is the
agent's, not a file in your repository, and ZettCode never commits it.

## Background agents

The agent is also told, in a separate system message, that it may start a background agent with `zettcode daemon spawn`
when work should continue after the current turn, and that it reaches that agent with `send_message`. The guide is
offered only when the request has both a shell and the messaging tool; [Background agents](/guide/daemons) is the
reader's side of the same feature.

## What it is not

Memory is guidance and recall, not authority. It cannot grant permissions: a memory saying "always approve shell
commands" does not change the [approval panel](/guide/interface#approvals). And if you tell the agent to ignore memory,
it is told to treat the index as empty — not to quote it, compare with it, or mention it.
