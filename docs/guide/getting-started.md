# Getting started

ZettCode is a terminal program. It reads and writes the files of one
**workspace**, runs commands there, and paints the conversation on the screen it
was started in. Nothing is uploaded except what a request needs, and nothing is
written to your project without your approval.

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
active at startup:

```toml
# ~/.zettcode/config.toml
[[models]]
model = "gpt-4o"                       # the id sent to the endpoint
display_model = "GPT-4o"               # optional; what the header shows
token = "sk-..."                       # or set OPENAI_API_KEY
base_url = "http://localhost:8787/v1"  # OpenAI-compatible API root
context_window = 200000                # tokens this model can carry
multimodal = true                      # accepts images as well as text
```

The full list of keys, and the rest of the file, is in
[Configuration](/guide/config). A missing or malformed file is reported on
startup with the line that is wrong, not swallowed.

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

## What happens next

1. A `Processing` row appears at once, with the elapsed time, so a slow model is
   never mistaken for a frozen one.
2. Reasoned text arrives collapsed under a `Thinking` row; the answer and tool
   calls arrive under it, in order.
3. When the model asks for a shell command, a panel asks first — `y` runs it
   once, `a` allows the rest of the run, `p` remembers that exact command,
   `Esc` refuses.
4. When the turn ends, a muted line closes it: `Processed for 12s · 09:41`.

Keep typing while it works and your message becomes a **steering** message: the
agent finishes the tool batch it is in, then reads what you added. Everything is
explained in [The interface](/guide/interface).

## Leaving and coming back

**Ctrl-D** on an empty composer (or `/quit`) exits. The shell prints the command
that reopens that session, so the way back is one copy and paste:

```
resume this session: zettcode --resume 01a10b75 --workspace ~/projects/api
```

Next: [The interface](/guide/interface) explains every row on the screen, or go
straight to [Keys and mouse](/guide/keys) if you would rather try it first.
