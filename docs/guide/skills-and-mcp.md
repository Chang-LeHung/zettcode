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
| `<workspace>/.zettcode/skills/` | One project, checked in with it. Read by default; `[skills] scope` can turn that off. |
| `[skills] roots` | A team directory, or any other: `roots = ["~/team-skills"]`. A relative entry resolves against the workspace. |

Configured roots are searched first, then the scope's directories, and the earlier one wins a name clash.
`[skills] enabled = false` turns discovery off.

### Where they live: your files, the project's, or both {#where-they-live}

`[skills] scope` (and `[mcp] scope`, below) chooses whose files are read:

| `scope` | Skills read from | MCP servers read from |
| --- | --- | --- |
| `"both"` (default) | The project's first, then yours | Both, merged; the project's entry wins a server name |
| `"workspace"` | `<workspace>/.zettcode/skills` | `<workspace>/.zettcode/mcp.json` |
| `"global"` | `~/.zettcode/skills` | `~/.zettcode/mcp.json` (or `[mcp] config`) |

Both are used together unless you say otherwise, so a project can carry its own skills and servers without any
configuration. To choose one side:

```toml
[skills]
scope = "global"      # ignore the skills a project carries

[mcp]
scope = "global"      # never start the servers a project carries
```

With `both`, a project can ship its own `review` skill that wins over yours inside that project and nowhere
else. The workspace is the one you launched with, so `zettcode -w ~/projects/api` reads
`~/projects/api/.zettcode/…`.

::: warning A repository's files are read by default
A skill is instructions the model follows, and an MCP entry is a command ZettCode runs, so with the default
opening a repository that carries `.zettcode/mcp.json` starts the servers it names. Review those files as you
would a script you were about to run, and set `scope = "global"` for the ones you do not trust.
:::

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
`<workspace>/.zettcode/skills/code-review/SKILL.md`. It is found with no configuration, and wins over a skill
of the same name in your own directory while you are in that project. Review skill files from other people
before using them, just as you would review instructions given to a teammate.

## MCP servers

An MCP server publishes tools. ZettCode reads them from
`~/.zettcode/mcp.json` — or wherever `[mcp] config` points — and from `<workspace>/.zettcode/mcp.json` too
([which files are read](#where-they-live)). It registers each
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
`[mcp] enabled = false` turns the extension off.

### Starting a server

A server that has to be started is a process, and starting one can take a while (`npx` may download a
package first). While it does, the conversation says so, so a request that sits on "Processing" has
a reason you can read:

```text
Starting MCP server 'docs' (process)…
MCP server 'docs' is ready: 3 tools, 2.1s
```

A remote server says `(connection)`. These lines appear **once per session, at its first turn** — they
explain why that turn was slow, and nothing later needs explaining: ZettCode looks at the servers again every
few minutes without saying so. Starting a new session or resuming one is entering one, so its first turn
says it again. A server whose tool list ZettCode already has starts nothing and says nothing, and one that
is down is reported as down rather than ready — and that is said whenever it happens, not only at the first
turn. The lines name the server and its kind and never repeat its command, which may carry a key. A
subagent says nothing about servers: you did not ask it anything.

### When a server or a tool goes wrong

One broken MCP piece never stops the task. What happens depends on which piece:

| What went wrong | What happens |
| --- | --- |
| A server is down, will not start, or does not answer in time | It is skipped for that request and the others work as usual. You get one line in the conversation — `MCP server 'docs' is not available (ConnectionError); its tools are skipped until it works` — and the model is told too, so it does not call tools that are not there. The line is said once, not at the top of every turn; if the server comes back and fails again, you hear about it again. |
| A tool reports an error, or the server dies in the middle of a call | The call comes back to the model as an ordinary failed tool result, with the server's own message, and the model carries on. A call that never answers times out after five minutes. |
| One entry in `mcp.json` is malformed (a missing field, an unknown `type`) | That entry is ignored and named — `MCP server 'typo' in mcp.json is ignored: …` — and every other server still loads. |
| `mcp.json` is not valid JSON at all, or names no servers | MCP is off for this run, with a line saying why. Fix the file and restart ZettCode; a file that was valid when it started is re-read when it changes, but one that never loaded has nothing to reload. |

Earlier versions stopped the whole request with `MCP unavailable (…)` when any one server
could not be reached, and listed every configured server in the message, working ones included.

::: tip A chatty server cannot break the screen
A stdio server writes its banner to stderr. While ZettCode owns the terminal
that output goes to `~/.zettcode/log/tui.log`, because painting it would corrupt
the frame. If a server seems to do nothing, that file is the first place to
look.
:::
