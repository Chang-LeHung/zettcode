<p align="center">
  <img src="docs/public/logo.svg" width="88" height="88" alt="ZettCode pixel robot with a warm heart" />
</p>
<h1 align="center">ZettCode</h1>
<p align="center"><strong>Your terminal. Your coding partner.</strong></p>
<p align="center">A focused coding agent that reads your project, shows its work, and keeps you in control.</p>
<p align="center">
  <strong>English</strong> · <a href="README.zh-CN.md">简体中文</a><br />
  <a href="https://chang-lehung.github.io/zettcode/guide/getting-started">Get started</a> ·
  <a href="https://chang-lehung.github.io/zettcode/">Documentation</a> ·
  <a href="https://chang-lehung.github.io/zettcode/guide/commands">Commands</a>
</p>

<p align="center">
  <img src="docs/public/terminal.svg" width="1000" alt="ZettCode showing a task, thinking, file reads, a code edit, passing tests, and a Markdown answer" />
</p>
<p align="center"><sub>Illustrative conversation, rendered with ZettCode’s actual terminal widgets.</sub></p>

## Get running

You need **Python 3.10+**, a UTF-8 terminal, and an **OpenAI-compatible API**.
Works on macOS, Linux, and Windows (use Windows Terminal).

### 1. Install

```bash
uv tool install zettcode
# or: pip install zettcode
```

### 2. Connect a model

Create `~/.zettcode/config.toml` (and its parent directory) with one model:

```toml
[[models]]
model = "deepseek-v4-pro"             # the model id sent to DeepSeek
display_model = "DeepSeek Pro"        # the name shown in ZettCode
token = "sk-..."                      # replace with your DeepSeek API key
base_url = "https://api.deepseek.com"  # DeepSeek's OpenAI-compatible API root
context_window = 1000000               # verify against the endpoint's current limits
multimodal = false                    # this model accepts text, not images
```

Get a key from the [DeepSeek platform](https://platform.deepseek.com/), not from
the chat website. Alternatively, omit `token` and set `OPENAI_API_KEY` to that
key. Add more `[[models]]` entries to switch with `/model`; the first is selected
at startup. See the
[configuration reference](https://chang-lehung.github.io/zettcode/guide/config)
for complete examples, defaults, and troubleshooting.

### 3. Start a task

```bash
cd /path/to/project
zettcode
# or: zettcode --workspace /path/to/project
```

Describe a change and press **Enter**. Type `/` for commands, `@` to reference a
skill, and **Ctrl-C** to stop a request. **Ctrl-D** with an empty composer exits
and prints the command to resume your session.

## Built for the way you work

| | |
| --- | --- |
| **See every step** | Reasoning, answers, and tool calls stream as readable rows — not raw JSON. |
| **Keep the decision** | Review shell commands before they run. When the agent needs your input, choose an option or type an answer. |
| **Keep moving** | Send a steering message during a reply. Use `/btw` for a side question that stays out of later context. |
| **Come back later** | `/resume` restores a conversation; `/export` saves a readable HTML record. |
| **Understand the context** | Monitor token usage and caching, inspect `/context`, and compact when needed. |
| **Bring your tools** | Use project `AGENTS.md` instructions, skills, MCP servers, and Python plugins. |

The palette follows your terminal’s background, or your own `theme.toml`.
Select and copy text, scroll through answers, and paste images when your model
supports them.

## Find your next step

The **[user guide](https://chang-lehung.github.io/zettcode/guide/overview)** is
available in English and [简体中文](https://chang-lehung.github.io/zettcode/zh/guide/overview).

| First time | Everyday use | Configuration & extensions |
| --- | --- | --- |
| [Getting started](https://chang-lehung.github.io/zettcode/guide/getting-started) | [Keys & mouse](https://chang-lehung.github.io/zettcode/guide/keys) | [Configuration](https://chang-lehung.github.io/zettcode/guide/config) |
| [The interface](https://chang-lehung.github.io/zettcode/guide/interface) | [Commands](https://chang-lehung.github.io/zettcode/guide/commands) | [Models & context](https://chang-lehung.github.io/zettcode/guide/models) |
| [Problems & questions](https://chang-lehung.github.io/zettcode/guide/faq) | [Sessions](https://chang-lehung.github.io/zettcode/guide/sessions) | [Project instructions](https://chang-lehung.github.io/zettcode/guide/instructions) |
| | | [Skills & MCP](https://chang-lehung.github.io/zettcode/guide/skills-and-mcp) · [Plugins](https://chang-lehung.github.io/zettcode/guide/plugins) |

## Development

```bash
uv sync                         # install dependencies
make check                      # Ruff, mypy, and tests
make hooks                      # enforce mypy before commits
make demo                       # browse terminal widgets
make docs                       # preview the user guide locally
uv run zettcode --workspace .    # run from the checkout
```

ZettCode provides the terminal application; the agent runtime is
[`zett-agent`](https://github.com/Chang-LeHung/zett-agent). Contributor notes and
invariants live in [`AGENTS.md`](AGENTS.md) and
[`docs/internal/`](docs/internal/), separately from the user guide. See
[`docs/internal/site-design.md`](docs/internal/site-design.md) for preview and
asset-generation instructions.

## License

MIT. See [`LICENSE`](LICENSE).
