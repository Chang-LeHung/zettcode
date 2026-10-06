# Skills and MCP

Two ways to teach ZettCode something it does not ship with: **skills** you
write yourself, and **MCP servers** that already exist. Both are off until there
is something to load, so neither adds a word to a request that does not use
them.

## Skills

A skill is one directory holding a `SKILL.md` with a name and a description in
its front matter:

```
~/.zettcode/skills/
└── code-review/
    └── SKILL.md
```

```md
---
name: code-review
description: Review a diff with the team checklist
---

Read the diff twice. Check error handling first, then naming, then tests.
Report findings as a list, most serious first.
```

The catalog — names and descriptions, nothing more — is what reaches the model.
The body arrives only when the model decides it needs it, which is what keeps a
large skill collection from filling the context window.

Discover them in two ways:

| Where | Who it is for |
| --- | --- |
| `~/.zettcode/skills/` | You, in every project. |
| `[skills] roots` | A project or a team: `roots = [".zettcode/skills"]` resolves against the workspace. |

Earlier roots win a name clash, and the configured ones are searched before your
own. `[skills] enabled = false` turns discovery off.

### Using one

Type `@` in a draft to reference a skill directly:

> Review @code-review the change I just made

The menu lists what was found. The message that gets stored is the one you
typed, so reopening the session later shows `@code-review` rather than a page of
instructions; the model is told to load the skill when it needs it.

## MCP servers

An MCP server publishes tools. ZettCode reads them from
`~/.zettcode/mcp.json` — or wherever `[mcp] config` points — and registers each
one as `<server>__<tool>`, so their tools sit beside the built-in ones.

```json
{
  "servers": {
    "docs": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:9000/mcp"
    },
    "browser": {
      "command": "npx",
      "args": ["-y", "some-mcp-server"],
      "env": { "API_KEY": "..." }
    }
  }
}
```

`mcpServers` is accepted as a spelling of `servers`, and a server may be a
streamable HTTP `url` (with optional `headers`) or a stdio `command` (with
optional `args`, `env`, and `cwd`).

With no file there is nothing to load, so an unconfigured run carries no MCP
instructions at all — rather than a system message saying there is nothing.
`[mcp] enabled = false` turns the extension off, and a server that fails to
start is reported by name, so a dead endpoint does not look like a hung request.

::: tip A chatty server cannot break the screen
A stdio server writes its banner to stderr. While ZettCode owns the terminal
that output goes to `~/.zettcode/log/tui.log`, because painting it would corrupt
the frame. If a server seems to do nothing, that file is the first place to
look.
:::
