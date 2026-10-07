# Skills and MCP

Two ways to teach ZettCode something it does not ship with: **skills** you
write yourself, and **MCP servers** that already exist. Skills supply reusable
instructions; MCP servers supply additional tools. Both are enabled by default,
but need local files or server definitions before they have anything to load.

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

### Example: install a personal review skill

1. Create `~/.zettcode/skills/code-review/`.
2. Save the `SKILL.md` example above into that directory. Keep the `---` front
   matter and both the `name` and `description` fields.
3. Restart ZettCode, type `@code`, and select `code-review` from the menu.
4. Send `Use @code-review to review the current diff. Do not edit files.`

The name is what you reference, not an absolute path. If nothing appears, check
the directory/file spelling and whether `[skills] enabled = false` is set.
Adding a skill is not the same as installing a tool: its instructions can ask
the model to use available tools, but do not create new ones.

For a skill checked into a project, place it at
`<workspace>/.zettcode/skills/code-review/SKILL.md`, then add this to
`config.toml`:

```toml
[skills]
roots = [".zettcode/skills"]
```

This is opt-in: project-local skill folders are not searched unless configured.
Review skill files from other people before using them, just as you would
review instructions given to a teammate.

## MCP servers

An MCP server publishes tools. ZettCode reads them from
`~/.zettcode/mcp.json` — or wherever `[mcp] config` points — and registers each
one as `<server>__<tool>`, so their tools sit beside the built-in ones.

### Example: a local browser server

For Chrome DevTools, install Node.js with `npx` available and Google Chrome,
then save this **JSON** in `~/.zettcode/mcp.json`:

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

Restart ZettCode and ask, for example:

> Use the browser tools to open `http://localhost:3000` and check for console errors.

Your application must already be serving that URL. The server is an external
program, not bundled with ZettCode; its first launch may download a package.
See its [setup instructions](https://github.com/ChromeDevTools/chrome-devtools-mcp)
for supported Node.js versions and browser options. In a controlled environment,
pin a reviewed package version rather than using `@latest`.

### Example: a remote HTTP server

If a service already exposes an MCP endpoint, use its actual URL instead:

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

The URL above is an example: you must start a server there or replace it.
To use both servers, put `browser` and `docs` in the same `servers` object;
do not concatenate two JSON documents. JSON requires double quotes and does
not allow comments or trailing commas.

`mcpServers` is accepted as a spelling of `servers`, and a server may be a
streamable HTTP `url` (with optional `headers`) or a stdio `command` (with
optional `args`, `env`, and `cwd`).

| Server key | Meaning | Example |
| --- | --- | --- |
| `command` | Executable for a local stdio server; it must be available to the process. | `"npx"` |
| `args` | Separate command arguments, as an array. | `["-y", "chrome-devtools-mcp@latest"]` |
| `env` | Environment values supplied to that server. | `{ "API_KEY": "your-server-key" }` |
| `cwd` | Working directory for a local server. | `"/absolute/path/to/project"` |
| `url` | Remote MCP endpoint, not a normal web page. | `"http://127.0.0.1:9000/mcp"` |
| `headers` | HTTP headers for a remote server, when required. | `{ "Authorization": "Bearer your-server-key" }` |

Use `command` for stdio or `"type": "streamable-http"` with `url` for HTTP;
they are different transports.

::: warning External tools need trust
An MCP server runs with the permissions of its process and may expose tools
with side effects. ZettCode's shell approval prompt is not a sandbox for all
MCP tools. Review the server and its capabilities before enabling it, and keep
keys in `env` or `headers` out of version control.
:::

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
