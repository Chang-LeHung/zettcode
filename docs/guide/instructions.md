# Project instructions

`AGENTS.md` tells the agent how a project works: which commands to run, which conventions matter, what not to
touch. ZettCode reads the files that apply to the workspace and gives them to the model. You do not paste them.

## Where it looks

Discovery starts at the workspace and walks up to the filesystem root, so a repository root and a nested package
both contribute. Files are read outermost first, innermost last:

```
~/AGENTS.md
~/projects/AGENTS.md
~/projects/api/AGENTS.md
~/projects/api/service/AGENTS.md    read last, and wins an argument
```

Every request re-reads them, so an edit applies to the next turn — no restart. Only the workspace's own file and
its ancestors count: starting in `~/projects/api` does not load the `AGENTS.md` files below it. Choose the
workspace that matches the part you are working on.

## What to write

Write it the way you would brief a new teammate:

```md
## Tooling
- Python 3.12+ and `uv`; Ruff with `line-length = 120`.
- Run `make check` before handing work over.

## Scope
- `src/app/` holds the service; `tools/` holds one-off scripts.
- Keep the public API in `src/app/api.py` stable.
```

Commands beat prose: "run `make check`" is actionable, "write good code" is not. Name the files and directories that
are off limits. Save it as `<project>/AGENTS.md` and start in that directory:

```bash
zettcode -w /path/to/project
```

The file is guidance, not proof: check that the command ran and read the diff. It is also sent to your model
endpoint, so keep secrets out of it.

## What it is not

Project instructions are content, not authority. They cannot grant permissions or override ZettCode's own
instructions, so a cloned repository cannot quietly widen what the agent may do.

A file over 32,000 characters is cut with a marker rather than dropped. One that cannot be read is skipped in
silence.

## Turning it off

```toml
[agents_md]
enabled = false
```

`agents_md.enabled` is in the [optional settings](/guide/config#optional-settings-reference), beside the other
switches.

## Next steps

- [Workspace memory](/guide/memory): what the agent keeps between sessions.
- [Configuration](/guide/config): every switch in `config.toml`.
