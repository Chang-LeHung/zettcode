# ZettCode

**English** · [简体中文](README.zh-CN.md)

A focused coding agent for your terminal. Point it at a workspace, describe the
change you want, and watch the work happen — files read, commands approved,
edits made, tests run — as a conversation you can scroll, select, and copy.

The terminal interface is this repository; the model loop is
[`zett-agent`](https://github.com/Chang-LeHung/zett-agent), published separately.

## Install

ZettCode needs Python 3.10 or newer. It is published on PyPI as `zettcode`:

```bash
uv tool install zettcode
# or
pip install zettcode
```

## Configure

Everything except the workspace lives in `~/.zettcode/config.toml`. At least one
model, and the first one is active at startup:

```toml
[[models]]
model = "gpt-4o"
token = "sk-..."                       # or set OPENAI_API_KEY
base_url = "http://localhost:8787/v1"  # any OpenAI-compatible endpoint
context_window = 200000                # tokens this model can carry
multimodal = true                      # accepts images as well as text
```

Project `AGENTS.md` files, [skills](https://chang-lehung.github.io/zettcode/guide/skills-and-mcp),
MCP servers, plugins, the palette, and the rest are all in the same file. The
full key list is in the [configuration reference](https://chang-lehung.github.io/zettcode/guide/config).

## Run

```bash
cd ~/projects/api
zettcode                                    # workspace defaults to the cwd
zettcode -w /path/to/project                # work somewhere else
zettcode --resume <session-id>              # reopen a stored session
zettcode --dry-run                          # time the startup and exit
```

Type a task and press **Enter**. `/` opens the command menu, `@` references a
skill, `Ctrl-C` stops a request, `Ctrl-D` on an empty composer exits — and
leaving prints the command that brings the session back.

## What it does

- **Streams a conversation, not a payload.** Reasoning, answers, and tool calls
  arrive as rows in order; tool output reads like a log — `Read src/app.py`,
  `Ran pytest -q` — never raw JSON.
- **Asks before it acts.** Every shell command is confirmed first, with
  `a` to allow the rest of the run and `p` to remember one command.
- **Keeps the context honest.** The status line shows tokens, cache hit rate,
  and how full the window is; `/context` breaks the request down, and compaction
  summarizes before the window overflows.
- **Remembers the project.** `AGENTS.md` files from the workspace upward become
  project instructions; skills and MCP servers extend what the model can do.
- **Respects the terminal.** Mouse selection and scrolling, panels for choices,
  image paste, `Ctrl-L`, and a palette that follows your terminal's background —
  or your own `theme.toml`.

## Documentation

The user guide is published at
**<https://chang-lehung.github.io/zettcode/>** (English, with
[中文](https://chang-lehung.github.io/zettcode/zh/) alongside it):

| | |
| --- | --- |
| [Getting started](https://chang-lehung.github.io/zettcode/guide/getting-started) | Install, first task, first approvals. |
| [The interface](https://chang-lehung.github.io/zettcode/guide/interface) | What each row of the screen tells you. |
| [Keys and mouse](https://chang-lehung.github.io/zettcode/guide/keys) | The full reference. |
| [Commands](https://chang-lehung.github.io/zettcode/guide/commands) | Every `/command` and `@resource`. |
| [Sessions](https://chang-lehung.github.io/zettcode/guide/sessions) | Resume, title, export. |
| [Configuration](https://chang-lehung.github.io/zettcode/guide/config) | One file, every key. |
| [Models and context](https://chang-lehung.github.io/zettcode/guide/models) | Effort, compaction, cache, images. |
| [Project instructions](https://chang-lehung.github.io/zettcode/guide/instructions) | Writing a good `AGENTS.md`. |
| [Skills and MCP](https://chang-lehung.github.io/zettcode/guide/skills-and-mcp) | Teaching it your own tools. |
| [Plugins](https://chang-lehung.github.io/zettcode/guide/plugins) | Adding commands and rows in Python. |
| [Problems and questions](https://chang-lehung.github.io/zettcode/guide/faq) | When something does not work. |

## Development

```bash
uv sync                       # install the environment
make check                    # ruff, mypy, and pytest
make hooks                    # run mypy before every commit
make demo                     # browse the widgets interactively
uv run zettcode -w .          # run the checkout against a workspace
```

Notes for working inside the repository — layering, the invariant list, the
platform seam — are in [`AGENTS.md`](AGENTS.md) and
[`docs/internal/`](docs/internal/). The docs site itself lives in
`docs/` and builds with `npm ci --prefix docs && npm run docs:build --prefix docs`.

## License

MIT — see [`LICENSE`](LICENSE).
