# Getting started

ZettCode is a coding agent that runs in your terminal. It works on the files of one directory, shows every tool call
it makes, and asks before it runs a shell command.

## What you need

- Python 3.10+ on macOS, Linux, or Windows (use Windows Terminal).
- An OpenAI-compatible endpoint, or Anthropic's Messages API, and a token for it.

## Install

::: code-group

```bash [uv]
uv tool install "zettcode[all]"
```

```bash [pip]
pip install "zettcode[all]"
```

:::

Keep the quotes: `fish` and `zsh` read an unquoted `[all]` as a pattern. Plain `zettcode` is the terminal, gateway,
server and SDK. `[all]` adds the four plugins: `/monitor`, `/recap`, the vendor models, and Codex and Claude Code as
agents.

## Connect a model

Run `zettcode`, then add a model from inside the window:

```text
/config add --model deepseek-v4-pro --token sk-... --url https://api.deepseek.com --context 1m --name "DeepSeek Pro"
```

This writes one `[[models]]` entry to `~/.zettcode/config.toml` and makes it the active model. Use your provider's
model id and API root; the token is a secret.

Prefer a file? The same entry in `~/.zettcode/config.toml`:

```toml
[[models]]
model = "deepseek-v4-pro"
display_model = "DeepSeek Pro"
token = "sk-..."
base_url = "https://api.deepseek.com"
context_window = 1000000
```

The [configuration reference](/guide/config#models) covers every key, multiple models, and environment variables.

## Start a task

Open ZettCode in the directory you want to work on:

```bash
cd ~/projects/api
zettcode
```

Type what you want and press **Enter**:

> add a limit/offset window to GET /users, and cover it with a test

Be specific about scope and how to verify the result. For a first look at an unfamiliar repository, ask first:

> Explain this project's entry point and how to run its tests. Do not edit files.

When the model wants to run a command, a panel asks before it does. `y` runs it once, `p` remembers that command,
`s` stops asking for read-only commands, `a` stops asking, `Esc` refuses. The agent can edit files without asking, so
review the diff before you keep the work.

Press **Ctrl-D** on an empty prompt to exit. The shell prints the command that reopens the session.

## Next steps

- [What it can do](/guide/capabilities): the JIT harness, `/code-review`, background agents, groups and the gateway.
- [The interface](/guide/interface): what every row on the screen means.
- [Commands](/guide/commands): every slash command, and the `zettcode` command line.
