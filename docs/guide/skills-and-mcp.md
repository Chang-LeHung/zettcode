# Skills and MCP

Two ways to give ZettCode what it does not ship with: a **skill** is instructions you write, an **MCP server** is a
program that adds tools. Both are on by default, and both need files before they load anything.

## What a skill is

A skill is one directory holding a `SKILL.md`: `name` and `description` in the front matter, the instructions in the
body.

```md
---
name: code-review
description: Review a diff with the team checklist
---

Read the diff twice. Check error handling first, then naming, then tests.
Report findings as a list, most serious first.
```

Only the name and description reach the model until it decides the skill is needed; then the body is loaded. That is
what keeps a large collection out of the context window.

## Where skills and servers are read from {#where-they-live}

| Location | Holds |
| --- | --- |
| `[skills] roots` | Extra directories, searched first: `roots = ["~/team-skills"]` |
| `<workspace>/.zettcode/skills/`, `<workspace>/.agents/skills/` | The project's, checked in with it |
| `~/.zettcode/skills/`, `~/.agents/skills/` | Yours, in every project |
| `mcp.json` in `~/.zettcode/`, `~/.agents/`, `<workspace>/.zettcode/`, `<workspace>/.agents/` | MCP servers |

A name declared twice belongs to the earlier location, so a project's skill wins inside that project. `scope` chooses
which side is read at all, for skills and servers alike:

| `scope` | Skills | MCP servers |
| --- | --- | --- |
| `"both"` (default) | The project's first, then yours | Both files, merged; the project wins a name |
| `"workspace"` | The project's only | `<workspace>/.zettcode/mcp.json` only |
| `"global"` | Yours only | `~/.zettcode/mcp.json`, and `~/.agents/mcp.json` unless `[mcp] config` names a file |

```toml
[skills]
scope = "global"      # ignore the skills a project carries

[mcp]
scope = "global"      # never start the servers a project carries
```

::: warning A repository's files are read by default
A skill is instructions the model follows, and an MCP entry is a command ZettCode runs, so opening a repository that
carries `.zettcode/mcp.json` starts the servers it names. Review those files as you would a script, and set
`scope = "global"` for repositories you do not trust.
:::

## Using a skill

Type `@` in a draft to point at one:

> Review @code-review the change I just made

The stored message keeps `@code-review` rather than a page of instructions. Without `@`, the model sees every skill's
name and description and loads the body when a task matches it.

If the menu does not list your skill, check the folder and the `name` field, and check that `[skills] enabled` is not
`false`. A skill is instructions, not a tool: it can ask the model to use the tools it has, and adds none.

A project's skill lives at `<workspace>/.zettcode/skills/<name>/SKILL.md` and is found with no configuration. Review
skill files from other people before you use them.

## MCP servers

ZettCode reads server definitions from `~/.zettcode/mcp.json` (or the file `[mcp] config` names) and registers each
tool as `<server>__<tool>`, beside the built-in ones.

```json
{
  "servers": {
    "browser": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp@latest"]
    }
  }
}
```

A server that runs elsewhere is named by its URL:

```json
{
  "servers": {
    "docs": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:9000/mcp"
    }
  }
}
```

| Key | Meaning |
| --- | --- |
| `command` | Executable of a local server; it must be on the path the process sees. |
| `args`, `env`, `cwd` | Its arguments, its environment, its working directory. |
| `url`, `headers` | A remote server, with `"type": "streamable-http"`. |

`mcpServers` is accepted as a spelling of `servers`. A server is an external program, not bundled with ZettCode, and
its first launch may download a package. After a restart, ask for a tool by what it does: "Use the browser tools to
open `http://localhost:3000` and check for console errors."

::: warning An MCP server runs as its own process
Its tools can have side effects, and the shell approval prompt does not cover them. Keep keys in `env` or `headers` out
of version control, and pin a version where you can instead of `@latest`.
:::

`[mcp] enabled = false` turns this off. With no file, nothing is loaded.

## When a server or a tool goes wrong

| What went wrong | What happens |
| --- | --- |
| A server is down, or slow to start | It is skipped for that request; one line says so, and the model is told its tools are missing. |
| A tool fails, or the server dies mid-call | The call returns as a failed tool result with the server's message; a call that never answers times out after five minutes. |
| One `mcp.json` entry is malformed | That entry is ignored and named; the other servers still load. |
| The file is not valid JSON | MCP is off for this run, with a line saying why. Fix the file and restart. |

While ZettCode owns the terminal, a stdio server's banner goes to `~/.zettcode/log/tui.log`, so look there if a server
seems to do nothing.
