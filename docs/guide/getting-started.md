# Getting started

ZettCode is a terminal program. It reads and writes the files of one
**workspace**, runs commands there, and paints the conversation on the screen it
was started in. Messages and tool results needed for a request are sent to your
configured model endpoint. Shell commands ask for approval; file-editing tools
can change the workspace as part of a task, so use version control and review
the diff before accepting the work.

## What you need

- Python 3.10 or newer, on macOS, Linux, or Windows.
- A terminal that speaks UTF-8 and at least 256 colours. On Windows use Windows
  Terminal; the classic console host is not enough.
- An OpenAI-compatible endpoint — a hosted API or a local server — or
  Anthropic's Messages API, and a token for it.

## Install

::: code-group

```bash [uv]
uv tool install zettcode
```

```bash [pip]
pip install zettcode
```

:::

Either way you get a `zettcode` command. `zettcode --help` lists everything the
command line takes, which is deliberately short:

| Flag | What it does |
| --- | --- |
| `-v`, `-V`, `--version` | Print the version — ZettCode, the zett-agent it runs on, and Python — and exit. Quote it when you report a problem. |
| `-w`, `--workspace DIR` | The directory to work in. Defaults to the current directory. |
| `-r`, `--resume SESSION` | Open a stored session instead of starting a new one. |
| `--full`, `--auto`, `--yolo` | Run shell commands with full access and without asking, for this run. The same as `/permission full`. (`--auto` is the old name.) |
| `--dry-run` | Run the startup, paint one frame, and exit. Useful for profiling. |

Four subcommands do their work by name: `zettcode resume SESSION` is `zettcode --resume SESSION`
(`-w DIR` may go before or after it, as in `zettcode resume 01a10b75 -w ~/projects/api`), `zettcode update`
(or `zettcode upgrade`, the same thing) installs the newest release and exits (see the
[FAQ](/guide/faq#new-versions)), and `zettcode doctor` asks every model in your config file one short
question and prints which of them answer and how fast, or why not (a revoked token, a wrong base URL, a model
the endpoint does not serve), exiting 1 if one does not. `zettcode prompt` runs the agent once
without opening the terminal, below.

### One question, from a script

`zettcode prompt` sends one prompt, prints the answer, and exits. Without `-m` and `-s` it uses the first model in the
config file and a new session:

```bash
zettcode prompt "explain what this repository does"
git diff | zettcode prompt "review this change"          # no prompt on the line: it is read from standard input
zettcode prompt -m "Claude Sonnet" -s 01a10b75 "and the tests?"
zettcode prompt --continue -s 01a10b75             # pick up a request that was cut short
```

| Option | What it does |
| --- | --- |
| `PROMPT` | What to ask. Leave it out, or give `-`, to read it from standard input. |
| `-m`, `--model NAME` | The model, by the name `/model` lists. |
| `-s`, `--session ID` | Continue a stored session. |
| `-c`, `--continue` | No prompt: pick up the request that was cut short, as [`/continue`](/guide/commands#continue) does. Needs `-s`. |
| `-e`, `--effort LEVEL` | The reasoning level. |
| `-w`, `--workspace DIR` | The directory to work in. |

Standard output holds the answer and nothing else. The tools used and, last, `session: <id>` go to standard error.
The exit status is `0` for an answer, `1` when the run failed or stopped early, `2` for arguments that cannot be used,
and `3` when `--continue` finds nothing to pick up.

Nobody can be asked here, so the shell permission is always `auto`: the model's commands run without asking. Use it
only in a workspace you would trust with a shell.

Working from a checkout instead:

```bash
uv sync
uv run zettcode -w /path/to/project
```

## Name a model

Everything except the workspace lives in `~/.zettcode/config.toml`. The only
required section is a list of models — one table each, and the first one is
active at startup. Create the directory before opening the file:

::: code-group

```bash [macOS / Linux]
mkdir -p ~/.zettcode
```

```powershell [Windows]
New-Item -ItemType Directory -Force "$HOME/.zettcode"
```

:::

This example connects to **DeepSeek**, which exposes an OpenAI-compatible API.
Create an API key on the [DeepSeek platform](https://platform.deepseek.com/),
then save the following in `~/.zettcode/config.toml`. Replace `sk-...` with your
key; it is a placeholder, not a working credential.

```toml
# ~/.zettcode/config.toml
[[models]]
model = "deepseek-v4-pro"             # the id sent to DeepSeek
display_model = "DeepSeek Pro"        # optional; what the header shows
token = "sk-..."                      # your DeepSeek API key
base_url = "https://api.deepseek.com"  # API root, not the chat website
responses_api = false                 # use Chat Completions
context_window = 1000000               # tokens; check the endpoint's current limits
compact_percent = 80                  # summarize before the context fills up
multimodal = false                    # DeepSeek Pro does not accept images
```

Three details matter here:

- `model` is the API's model id; `display_model` is only a label in the UI.
- `base_url` is the API root. Do not use `https://chat.deepseek.com` or append
  `/chat/completions` to it.
- `multimodal = false` keeps image input disabled for this text-only model. If
  you want to paste screenshots, configure a model that accepts images.

DeepSeek's model names and capabilities change over time. This example follows
its [current model reference](https://api-docs.deepseek.com/quick_start/pricing);
if you use a gateway, use the ids and limits advertised by that gateway.

Prefer not to keep a key in a file? Omit the `token` line and set
`OPENAI_API_KEY` instead, even when the key belongs to DeepSeek. See
[the environment-variable example](/guide/config#keeping-the-key-out-of-the-file).
The [configuration reference](/guide/config) covers multiple models and all
optional sections. Startup errors name a missing setting or invalid key; TOML
syntax errors include the parser's location information.

Haven't written any of this yet? Start anyway: the window opens, the header reads
`no model`, and `/config` asks for the provider, the model id and the token and
writes the entry into the same file — creating it if this machine has none. A
request before then is refused with the same instruction, and the words you
typed stay in the box, ready to send once the model is in.

## Send the first task

Start it in the directory you want to work on:

```bash
cd ~/projects/api
zettcode
```

The window opens immediately — settings and the session are ready before the
provider SDK is — and the status line reads `ready`. Type a task and press
**Enter**:

> add a limit/offset window to GET /users, and cover it with a test

For a safer first look at an unfamiliar repository, start with a read-only
request:

> Explain this project's entry point and how to run its tests. Do not edit files.

Then give it a bounded change:

> Add a test for an empty users response. Change only tests/test_users.py.

Use real paths from your project. Specific scope and a way to verify the result
make a task easier to review than "improve this project".

## What happens next

1. A `Processing` row appears at once, with the elapsed time, so a slow model is
   never mistaken for a frozen one. It stays pinned to the bottom of the
   transcript: reasoning, tool calls, and the answer all appear above it.
2. Reasoned text arrives collapsed under a `Thinking` row, and tool calls read
   like a log — `Read src/app.py`, `Bash pwd`.
3. When the model asks for a shell command, a panel asks first — `y` runs it
   once, `p` remembers that exact command, `s` stops asking for read-only
   commands, `a` stops asking for any, `Esc` refuses. `/permission` sets the
   same four levels directly.
4. When the request ends — answered, failed, or stopped with `Ctrl-C` — that
   same row becomes the muted line that closes it: `Processed for 12s · 09:41`.

Keep typing while it works and ZettCode asks whether your message should **steer**
the request (the agent finishes the tool batch it is in, then reads it) or **follow
up** once it is done. Everything is explained in [The interface](/guide/interface).

## Leaving and coming back

**Ctrl-D** on an empty composer (or `/quit`) exits. The shell prints the command
that reopens that session, so the way back is one copy and paste:

```
resume this session: zettcode resume 01a10b75 --workspace ~/projects/api
```

## Check the result

Read the answer and expand tool output if needed. In a Git workspace, inspect
the changes from another terminal:

```bash
git diff --stat
git diff
```

Run the project's tests before keeping the changes. ZettCode works on the local
workspace; a successful-looking answer is not a substitute for reviewing files.
If the first request fails, follow the
[connection checks](/guide/config#checking-the-connection).

Next: [The interface](/guide/interface) explains every row on the screen, or go
straight to [Keys and mouse](/guide/keys) if you would rather try it first.
