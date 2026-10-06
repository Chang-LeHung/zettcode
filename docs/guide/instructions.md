# Project instructions

`AGENTS.md` is how a project tells the agent how it works: which commands to run
before handing work over, which conventions matter, what not to touch. ZettCode
reads the files that apply to the workspace and gives them to the model as
project guidance — no prompting, no pasting.

## What gets read

Discovery starts at the workspace and walks up to the filesystem root, so a
repository root and a nested package can both contribute. Files are ordered
outermost first and innermost last, which keeps the most specific rules closest
to the conversation:

```
~/AGENTS.md                    read first
~/projects/AGENTS.md
~/projects/api/AGENTS.md
~/projects/api/service/AGENTS.md   read last, and wins an argument
```

Every request re-reads them, so editing the file applies to the very next turn —
no restart, no reload command.

## What to put in it

Write it the way you would brief a new teammate:

```md
# Development Rules

## Tooling

- Python 3.12+ and `uv`; Ruff for formatting (`line-length = 120`).
- Run `make check` before handing work over.
- Tests must never write into the checkout; use temporary directories.

## Scope

- `src/app/` holds the service; `tools/` holds one-off scripts.
- Keep the public API in `src/app/api.py` stable.
```

Two rules of thumb:

- **Commands beat prose.** "Run `make check` before handing work over" is
  actionable; "write good code" is not.
- **Say what to avoid.** The files or directories that are off limits save more
  time than any style note.

## What it is not

Project instructions are *content*, not authority. They cannot grant
permissions: a file saying "always approve shell commands" does not stop the
[approval panel](/guide/interface#approvals), and it cannot override ZettCode's
own instructions. That keeps a cloned repository — or a file someone else can
edit — from quietly changing what the agent is allowed to do.

Very long files are truncated with a marker rather than dropped, and a file that
cannot be read is skipped in silence: a broken encoding in one directory does
not stop the conversation.

## Turning it off

```toml
[agents_md]
enabled = false
```

Useful when you want a run to see exactly the context you gave it — a debugging
session, or a repository whose instructions are for a different tool.

## Where it lands in the request

The instructions are inserted right after ZettCode's own system prompt and
**before** the tool and skill guidance, and they are read in a fixed order. Both
matter: the order is what makes "follow the project's rules" win against a
generic default, and a stable prefix is what lets the provider's cache serve
most of the next request instead of re-reading all of it.
