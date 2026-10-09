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
- An OpenAI-compatible endpoint — a hosted API or a local server — and a token
  for it.

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
| `-w`, `--workspace DIR` | The directory to work in. Defaults to the current directory. |
| `-r`, `--resume SESSION` | Open a stored session instead of starting a new one. |
| `--dry-run` | Run the startup, paint one frame, and exit. Useful for profiling. |

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
   like a log — `Read src/app.py`, `Ran pwd`.
3. When the model asks for a shell command, a panel asks first — `y` runs it
   once, `a` allows the rest of the run, `p` remembers that exact command,
   `Esc` refuses.
4. When the request ends — answered, failed, or stopped with `Ctrl-C` — that
   same row becomes the muted line that closes it: `Processed for 12s · 09:41`.

Keep typing while it works and your message becomes a **steering** message: the
agent finishes the tool batch it is in, then reads what you added. Everything is
explained in [The interface](/guide/interface).

## Leaving and coming back

**Ctrl-D** on an empty composer (or `/quit`) exits. The shell prints the command
that reopens that session, so the way back is one copy and paste:

```
resume this session: zettcode --resume 01a10b75 --workspace ~/projects/api
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
