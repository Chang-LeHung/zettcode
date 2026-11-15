<p align="center">
  <img src="clients/vscode/media/logo.svg" width="120" alt="ZettCode mascot riding a sword past the moon" />
</p>
<h1 align="center">ZettCode</h1>
<p align="center"><strong>A terminal coding agent that can write its own tools and work with other agents.</strong></p>
<p align="center">
  <strong>English</strong> · <a href="README.zh-CN.md">简体中文</a><br />
  <a href="https://chang-lehung.github.io/zettcode/guide/getting-started">Get started</a> ·
  <a href="https://chang-lehung.github.io/zettcode/guide/capabilities">What it can do</a> ·
  <a href="https://chang-lehung.github.io/zettcode/">Documentation</a> ·
  <a href="https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode">VS Code extension</a>
</p>

<p align="center">
  <img src="docs/public/terminal.svg" width="1000" alt="ZettCode showing a task, thinking, file reads, a code edit, passing tests, and a Markdown answer" />
</p>
<p align="center"><sub>Illustrative conversation, rendered with ZettCode’s actual terminal widgets.</sub></p>

ZettCode works in your terminal on one directory. It shows every reasoning step and tool call as a readable row,
asks before it runs a shell command, and lets you resume any conversation. A session can also write a small tool for
the task, hand a review to a second agent, run in the background, and message other sessions — including Codex and
Claude Code — from your terminal or a web page.

## What it does

| | In one line | Try |
| --- | --- | --- |
| **JIT harness** | The model writes a Python tool, loads it and calls it in the same turn. | `/harness gen` |
| **Code review** | A second agent reads your uncommitted changes while you keep the conversation. | `/code-review` |
| **Background agents** | A session with nobody at the keyboard; it keeps running after you close the terminal. | `zettcode daemon spawn` |
| **Messages and groups** | Sessions on one machine message each other; `@name` points the model at one, a group reaches all. | `@name` in the prompt |
| **Web gateway** | A page for daemons, sessions and groups, with a graph and replay. Also on a phone. | `zettcode gateway start` |
| **Codex and Claude Code** | Both run as members you can message and put in groups. | New → External agent |

Each one has a page in the [user guide](https://chang-lehung.github.io/zettcode/guide/capabilities).

## Get running

You need **Python 3.10+**, a terminal (Windows Terminal on Windows), and an **OpenAI-compatible API** or Anthropic's
**Messages API**.

```bash
uv tool install "zettcode[all]"
# or: pip install "zettcode[all]"
```

Keep the quotes: `fish` and `zsh` read an unquoted `[all]` as a pattern. Plain `zettcode` is the terminal, gateway,
server and SDK; `[all]` adds `/monitor`, `/recap`, the vendor models, and Codex and Claude Code.

Connect a model. Run `zettcode` and use `/config`:

```text
/config add --model deepseek-v4-pro --token sk-... --url https://api.deepseek.com --context 1m --name "DeepSeek Pro"
```

Or write the same entry in `~/.zettcode/config.toml`:

```toml
[[models]]
model = "deepseek-v4-pro"
display_model = "DeepSeek Pro"
token = "sk-..."                       # or set OPENAI_API_KEY and leave this out
base_url = "https://api.deepseek.com"
context_window = 1000000
```

Start a task in the directory you want to work on:

```bash
cd ~/projects/api
zettcode
```

Type what you want and press **Enter**. `y` approves a shell command once, `p` remembers it, `a` stops asking,
`Esc` refuses, and **Ctrl-D** on an empty prompt exits.

## Work with other agents

```bash
zettcode daemon spawn --name builder --title "tool builder" --permission safe
zettcode gateway start
```

The first starts a background session; `@tool-builder` in your prompt sends work to it. The second opens a page where
you can watch sessions, make groups, and message Codex or Claude Code when `zettcode[code-agents]` is installed.

<p align="center">
  <img src="docs/public/demo/group.gif" width="800" alt="Creating a group, mentioning the builder agent, and reading its reply" />
</p>

## Documentation and development

The [user guide](https://chang-lehung.github.io/zettcode/guide/overview) covers every command, setting and feature,
in English and [简体中文](https://chang-lehung.github.io/zettcode/zh/guide/overview). The
[**SDK**](https://chang-lehung.github.io/zettcode/sdk/) drives the agent from Python, and the
[**server**](https://chang-lehung.github.io/zettcode/server/) exposes it over HTTP.

```bash
uv sync                       # install the workspace
make check                    # Ruff, mypy and the suites this change needs
make check-all                # every suite
make docs                     # preview the guide
uv run zettcode --workspace . # run from the checkout
```

The agent runtime is [`zett-agent`](https://github.com/Chang-LeHung/zett-agent). This repository is a uv workspace of
one distribution per subsystem under `packages/`, sharing the `zettcode` namespace; `clients/typescript/` and
`clients/vscode/` are the editor clients. Contributor notes and invariants live in [`AGENTS.md`](AGENTS.md) and
[`docs/internal/`](docs/internal/), apart from the user guide.

## License

MIT. See [`LICENSE`](LICENSE).
