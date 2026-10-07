# Configuration

One file, `~/.zettcode/config.toml`, holds everything except the workspace.
Unknown keys and wrong types are reported on startup with the key that is wrong
— `zettcode: Config key 'models[2] key 'model'' must be str` — instead of being
ignored.

```bash
ZETTCODE_CONFIG=/path/to/other.toml zettcode   # use a different file
```

## Models

At least one `[[models]]` table is required; the first is active at startup, and
`/model` switches between them for later requests.

```toml
[[models]]
model = "gpt-4o"                       # required: the id sent to the endpoint
token = "sk-..."                       # required: or set OPENAI_API_KEY
display_model = "GPT-4o"               # optional: what the header shows
base_url = "http://localhost:8787/v1"  # optional: OpenAI-compatible API root
responses_api = false                  # use the Responses API instead
multimodal = true                      # accepts images as well as text
context_window = 200000                # tokens this model can carry
compact_percent = 80                   # compact when a request reaches this share
```

| Key | Default | Notes |
| --- | --- | --- |
| `model` | — | Required. Blank is rejected. |
| `token` | `$OPENAI_API_KEY` | Required in the end: the file or the environment. |
| `display_model` | the model id | Shown in the header and the picker. |
| `base_url` | the client's default | Any OpenAI-compatible gateway. |
| `responses_api` | `false` | Set it when the endpoint speaks `/responses`. |
| `multimodal` | `false` | Off means an attached image is refused, not sent. |
| `context_window` | `128000` | What `/context` measures against. |
| `compact_percent` | `80` | The share of the window that triggers compaction. |

`context_window` and `compact_percent` are worth setting to the truth: a model
that carries 200k tokens but is configured for 128k compacts earlier than it
must, and one configured larger than it is will fail at the endpoint. See
[Models and context](/guide/models).

## The rest of the file

```toml
[transcript]
max_entries = 1024             # conversation rows kept on screen

[agents_md]
enabled = true                 # read AGENTS.md from the workspace upwards

[ask_user]
enabled = true                 # let the model ask a question mid-turn

[skills]
enabled = true
roots = ["~/team-skills"]      # searched before ~/.zettcode/skills

[mcp]
enabled = true
config = "~/.zettcode/mcp.json"

[plugins]
enabled = true
disable = ["greeter"]          # entry-point names not to load

[update]
enabled = true                 # look for a newer release in the background
```

| Table | Key | Default | Notes |
| --- | --- | --- | --- |
| `transcript` | `max_entries` | `1024` | Bounds the scrollback only; the session keeps everything. |
| `agents_md` | `enabled` | `true` | See [Project instructions](/guide/instructions). |
| `ask_user` | `enabled` | `true` | Give the model the `ask_user` tool, so it can pause a turn and ask. |
| `skills` | `enabled` | `true` | See [Skills and MCP](/guide/skills-and-mcp). |
| `skills` | `roots` | `[]` | A relative root resolves against the workspace. |
| `mcp` | `enabled` | `true` | See [Skills and MCP](/guide/skills-and-mcp). |
| `mcp` | `config` | `~/.zettcode/mcp.json` | JSON file naming the servers. |
| `plugins` | `enabled` | `true` | See [Plugins](/guide/plugins). |
| `plugins` | `disable` | `[]` | Switch one distribution off without uninstalling. |
| `update` | `enabled` | `true` | Ask PyPI for a newer release in the background, and offer it on a later start. |

Session storage is deliberately **not** configurable: a session belongs to the
workspace it was written in, and `~/.zettcode/sessions` is where every workspace
looks for it.

## Colours

The palette is a separate file, `~/.zettcode/theme.toml`, because it is personal
rather than per-project. Create it and the shell stops guessing; every key is
optional, and only the ones you name change.

```toml
base = "dark"                  # dark | light — what to start from

[ui]
accent = "#a7c080"
accent_bright = "#83c092"
background = "#232a2e"         # omit to use the terminal's own background
surface_side = "#393a44"       # fill of the `/btw` row, which is not a turn

[tools]                        # every role ships the same violet
read = "#b8a6e0"
shell = "#7fbbb3"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"
```

At startup the shell asks the terminal a single question — what is your
background colour? — and picks the dark or light palette to match. A theme file
turns that off: choosing colours is a decision, and the file is used as written.
`/theme` overrides either way for the rest of the run.

## Environment

| Variable | Effect |
| --- | --- |
| `ZETTCODE_CONFIG` | Use a different config file. |
| `OPENAI_API_KEY` | Token for a model that does not set one. |
| `ZETTCODE_REDUCED_MOTION` | Suppress decorative animation. |
| `NO_COLOR`, `TERM`, `COLORTERM` | The usual terminal hints, for colour depth. |

## Files ZettCode writes

| Path | What it is |
| --- | --- |
| `~/.zettcode/config.toml` | This file. |
| `~/.zettcode/theme.toml` | Optional palette, read when it exists. |
| `~/.zettcode/sessions/` | Sessions and their index. |
| `~/.zettcode/log/tui.log` | Anything written to stderr while the frame owns the screen. |
| `~/.zettcode/skills/` | Skills, one directory each. |
| `~/.zettcode/mcp.json` | MCP servers, when you do not point elsewhere. |
| `~/.zettcode/update.json` | What the release check found, and the version you skipped. |

That log file exists because a child process — an MCP server announcing itself,
say — cannot know the screen is taken, and painting over the interface would
corrupt the frame. Its output goes to the file instead.
