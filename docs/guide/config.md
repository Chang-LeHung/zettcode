# Configuration

Start with one working model connection, then add only the settings you need.
ZettCode reads `~/.zettcode/config.toml` at startup. You do not need to create
every section: omitted optional settings keep their defaults.

This page uses DeepSeek as a concrete example. By default ZettCode connects
through the **OpenAI-compatible API**; an entry that sets `anthropic = true`
uses Anthropic's **Messages API** instead. Either way there is no `provider`
setting.

## Files and when they apply

| File | Purpose | When a change takes effect |
| --- | --- | --- |
| `~/.zettcode/config.toml` | Model connections and optional features | Restart ZettCode. |
| `~/.zettcode/theme.toml` | One set of custom colours, laid over the palette in force | Restart; `/theme` selects a palette during a run. |
| `~/.zettcode/themes/<name>.toml` | Your own palettes, picked by name | Picked up the next time `/theme` is used. |
| `~/.zettcode/mcp.json` | External tool servers | Restart after changing server definitions. |
| `AGENTS.md` in or above the workspace | Project rules and test commands | Read again for the next request. |

`~` means your home directory. On Windows this is normally
`C:\Users\<your-name>`. The workspace is separate from configuration: start with
`zettcode -w /path/to/project`, or run `zettcode` from the project directory.

To try a different configuration without replacing your normal file:

::: code-group

```bash [macOS / Linux]
ZETTCODE_CONFIG="$HOME/.zettcode/deepseek.toml" zettcode -w /path/to/project
```

```powershell [Windows]
$env:ZETTCODE_CONFIG = "$HOME/.zettcode/deepseek.toml"
zettcode -w C:\projects\api
# Remove the override when finished.
Remove-Item Env:ZETTCODE_CONFIG
```

:::

The selected file **replaces** the default config; the two are not merged.
Relative workspace paths resolve from the directory where you launch ZettCode.

## Models

### Adding models with /config {#adding-models-with-config}

You do not have to edit the file to add a model. `/config` opens a panel over the conversation:

```text
Models
~/.zettcode/config.toml
 ▸ 1. DeepSeek Pro (current)   deepseek-v4-pro · chat · https://api.deepseek.com
   2. DeepSeek Flash           deepseek-flash · chat · https://api.deepseek.com
   + Add a model               from a provider, or any endpoint
```

**Add a model** asks which provider it is at, then only what that provider does not already say. A
provider is a known host — its address and API are filled in, so you give the **model id** and
your **token**:

| Provider | API | Address |
| --- | --- | --- |
| `openai` | chat completions | `https://api.openai.com/v1` |
| `anthropic` | Messages API | `https://api.anthropic.com` |
| `deepseek` | chat completions | `https://api.deepseek.com` |
| `openrouter` | chat completions | `https://openrouter.ai/api/v1` |
| `groq` | chat completions | `https://api.groq.com/openai/v1` |
| `ollama` | chat completions | `http://localhost:11434/v1` |
| `custom` | **you choose** | **you give it** |

`custom` is any other endpoint. It first asks which **API** it speaks (`chat` for chat completions,
`responses` for the Responses API, `anthropic` for the Messages API), on a list of its own, and then shows
the form below. An Anthropic-API endpoint has no address line: the SDK has one. Plugins can add providers to
this list; see [Plugins](/guide/plugins#providers).

A provider is added on **one form**, not a question at a time:

```text
Add a model at DeepSeek
Tab moves between the lines; Enter saves them all.

› Model id *    deepseek-chat
  Token         ••••••••••••••
  Address       https://api.deepseek.com
  Shown name    the model id
  Temperature   the provider's default
```

**Tab** (or **↓**) moves to the next line and **Shift-Tab** (or **↑**) to the previous one, going round at the ends;
**Enter** saves all of it; a hint under the form explains the line the cursor is in. Only the **model id** is required
(and the address for `custom`). The **token may be empty**: a local server (Ollama, LM Studio, vLLM) wants none, and
the environment's `OPENAI_API_KEY` is used when there is one. A line that cannot be saved — an address that is not
http or https, a temperature out of range — is named above the form, the cursor goes to it, and everything you typed
stays.

The token is typed as bullets and never shown again — not in the panel, not in `/config list`, not
in the line that says the model was added. **Escape goes back one step**: from the form to the provider list (for
`custom`, to the list of APIs), from the list to the models, and only from the models
panel does it close. Nothing is written until you press Enter on the form, so going back never costs anything.

Choose a model in the panel to **use** it, change its **token**, **API** (`chat`, `responses` or
`anthropic`), **address**, **model id**, **shown name** or **temperature**, or **remove** it (it asks first, and *Keep it* is the answer Enter gives).

Three more rows are about what the model can carry, and each takes effect in the running session at once:

| Row | What it sets | How to write it |
| --- | --- | --- |
| **Images** | Whether the model accepts images (`multimodal`). With *No*, a picture is refused here and the model gets no `view_image`. | Pick *Yes* or *No*; it starts on the current answer. |
| **Context window** | How many tokens the model can carry (`context_window`), which `/context` measures against. | `128000`, `128,000`, `128k`, `1m` or `1.5m`. Under 1,000 is refused, because it is nearly always a window written in thousands — write `200k`. Empty uses 128,000. |
| **Compress at** | The share of the window at which the conversation is summarized before the next request (`compact_percent`). | A percentage above 0 and up to 100: `80` or `80%`. Empty uses 80. |

The window and the share together decide when compaction happens — at 200k and 75% that is 150,000 tokens —
and the panel says what they come to when you set them. The values are not asked when you *add* a model
(the provider does not know them); set them here afterwards, or give `--context` and `--compact` on the line.

The same thing on one line, asking only for what the line leaves out:

```text
/config add deepseek --model deepseek-chat --token sk-...
/config add custom --api chat --url https://llm.example/v1 --model my-model --token sk-... --name "My model"
/config add anthropic --model claude-sonnet-4-5          # opens the form for the rest
/config remove 3          # or the name: /config remove "My model"
/config add custom --api chat --url https://llm.example/v1 --model big --token sk-... --context 1m --compact 60
/config list              # the models, what they take and where they compress, never a token
/config providers         # what `add` accepts
```

| Option | Meaning |
| --- | --- |
| `--model ID` | The model id the provider calls it. |
| `--token KEY` | The credential. Left out, the form has a hidden token line, which may stay empty. |
| `--url URL` | The address, replacing the provider's. Required for `custom` (except `--api anthropic`). |
| `--api chat\|responses\|anthropic` | Which API. A provider has its own; this overrides it, e.g. `openai --api responses`. |
| `--name SHOWN` | The name in the header and `/model` (`display_model`). |
| `--multimodal` | The model accepts images. |
| `--context TOKENS` | The context window: `200000`, `200k`, `1m`. |
| `--compact PERCENT` | Summarize at this share of the window: `75` or `75%`. |
| `--temperature T` | The sampling temperature, from 0 to 2 (0 to 1 for `anthropic`). |

::: tip Prefer the panel for a token
A line you type stays in the composer's in-memory history, so pressing `Up` shows it again until
you quit. Leave `--token` off and type the token into the hidden prompt instead.
:::

What `/config` does to the file:

- It changes **only the `[[models]]` entries**. Your comments, other tables, and layout stay exactly
  as written, and the result is checked before it is saved: if it would not hold exactly the models
  meant, or would change anything else, nothing is written.
- A model you add is available **at once** — no restart. Adding is not choosing: the model in use
  stays. Removing the one in use switches to its neighbour and says so.
- The file keeps its permissions. A new file is created readable by you alone, since it holds keys.
- `/config` reads the file each time, so models you added by hand since starting show up in it.
- Comments *inside* a model you edit are not kept (those above it and everywhere else are).
- A file that writes its models another way — an inline `models = [ … ]` array — is left alone with
  a message to edit it by hand, and the last remaining model cannot be removed.

### A working DeepSeek example

Create an API key on the [DeepSeek platform](https://platform.deepseek.com/).
Create `~/.zettcode/` if it does not exist, and save this as `config.toml`:

```toml
[[models]]
model = "deepseek-v4-pro"             # API model id, not a friendly label
display_model = "DeepSeek Pro"        # name in the header and /model picker
token = "sk-..."                      # replace with your DeepSeek API key
base_url = "https://api.deepseek.com"  # API root, not the chat website
responses_api = false                 # Chat Completions, not /responses
multimodal = false                    # Pro is text-only
context_window = 1000000               # token limit; check the endpoint's reference
compact_percent = 80                  # summarize at 80% of that limit
```

The example follows DeepSeek's
[current model reference](https://api-docs.deepseek.com/quick_start/pricing).
Model ids, context limits, and image support can change; a third-party gateway
may expose different limits. Use the values your actual endpoint publishes.
Setting a larger window here does not make the remote model accept more tokens.

::: warning Keep credentials private
`sk-...` is a placeholder. Never commit your real key to Git or include it in a
screenshot, exported conversation, or bug report. A chat subscription or login
is not an API key. On macOS/Linux you can restrict file access with
`chmod 600 ~/.zettcode/config.toml`.
:::

### Every model key

| Key | Type | Default | What to put here |
| --- | --- | --- | --- |
| `model` | string | Required | Exact model id accepted by the API, such as `deepseek-v4-pro`. Non-empty; the only key a model has to have. |
| `display_model` | string | Model id | Your readable label, such as `DeepSeek Pro`. It is not sent as the model id. |
| `token` | string | `OPENAI_API_KEY`, else none | API key for this endpoint. A non-empty file value takes precedence over the environment. An `anthropic` entry reads `ANTHROPIC_API_KEY` instead. May be left out: a local server (Ollama, LM Studio, vLLM) wants no key, and the model is called without one. A server that does want one answers `401`. |
| `base_url` | string | The vendor's address | Where the client appends its route. Set it explicitly for DeepSeek or another non-OpenAI endpoint. Defaults to `https://api.openai.com/v1`, or to `https://api.anthropic.com` for an `anthropic` entry. |
| `anthropic` | boolean | `false` | `true` calls Anthropic's Messages API instead of an OpenAI-compatible one. Cannot be combined with `responses_api` or `chat`. |
| `responses_api` | boolean | `false` | `false` uses Chat Completions; `true` uses Responses. Choose a protocol the endpoint supports. Not available for an `anthropic` entry. |
| `chat` | boolean | `false` | `true` says outright that the endpoint speaks Chat Completions, which is what an entry with neither of the other two already does. It is for the reader of the file; it cannot be combined with `anthropic` or `responses_api`. |
| `temperature` | number | the provider's own | Sampling temperature sent with every request, from `0` (the most deterministic) to `2`; an `anthropic` entry stops at `1`. Left out, none is sent. Some reasoning models reject a temperature, so set it only for a model that takes one. |
| `multimodal` | boolean | `false` | Enable only for a model and endpoint that accept image input. |
| `context_window` | integer | `128000` | Positive context-window size in tokens, not characters or the output limit. |
| `compact_percent` | number | `80` | Automatic compaction threshold: greater than `0`, at most `100`. Decimals such as `75.5` are allowed. |
| `reasoning_efforts` | array of strings | every level | The reasoning levels this model accepts, from `off`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`. List them when the endpoint rejects the rest; see [Reasoning levels a model takes](#reasoning-levels-a-model-takes). |

`base_url` is where the client appends its route — `/chat/completions`,
`/responses`, or `/v1/messages` for an `anthropic` entry — so the route is not
part of it. Writing the route out is a common reading, so an entry that ends
with one has just that part removed: either way the request reaches
`…/v1/messages` once, not twice. What precedes the route is kept as written, so
a gateway that serves the API under a prefix keeps that prefix. DeepSeek's
example does not need `/v1`; other services often do. Copy the address your
provider calls the **API root** rather than guessing from its website URL.

When `multimodal` is false, image submission is refused locally with an error,
and the model is not offered the `view_image` tool. Setting it to true does not
add vision to a text-only model. See [Pictures and pastes](/guide/interface#pictures-and-pastes).

### Reasoning levels a model takes {#reasoning-levels-a-model-takes}

Not every endpoint accepts every reasoning level, and an unsupported one can fail the whole request. An
entry names the levels its model takes:

```toml
[[models]]
model = "deepseek-v4-pro"
token = "sk-..."
base_url = "https://api.deepseek.com"
context_window = 1000000
compact_percent = 80
reasoning_efforts = ["low", "high", "max"]
```

Leave the key out and every level is offered. When it is set:

- `/effort` shows only those levels, and typing another (`/effort ultra`) is refused with the list the model
  does take, so nothing changes without your noticing.
- Switching models with `/model` moves the level in force to the nearest one the new model takes, so a
  request is never sent with a level its endpoint would reject. Switching back does not restore it.
- A subagent (the `task` tool) runs on the model of the request that started it, at its profile's default
  level (`explore` low, `coding` medium, `reasoning` high) moved to the nearest the model takes. The model
  can also pass `reasoning_effort` to the `task` tool to choose how hard that child thinks; only the levels
  this model takes are offered to it.

A tie between two levels goes to the cheaper one.

### Anthropic models

`anthropic = true` calls Anthropic's Messages API rather than an
OpenAI-compatible one. Everything else about an entry works the same, and the
`/model` picker names the API each row speaks:

```toml
[[models]]
model = "claude-sonnet-4-5"              # API model id, not a friendly label
display_model = "Claude Sonnet 4.5"      # name in the header and /model picker
token = "sk-ant-..."                     # replace with your Anthropic API key
anthropic = true                         # Messages API, through Anthropic's SDK
# base_url = "https://api.anthropic.com"  # uncomment for a gateway or proxy
context_window = 200000                  # this model's window; check its model page
compact_percent = 80                     # summarize at 80% of that limit
multimodal = true                        # Claude accepts images
```

`base_url` defaults to `https://api.anthropic.com`, and `token` falls back to
`ANTHROPIC_API_KEY` rather than `OPENAI_API_KEY`. A gateway that speaks the
Messages protocol but lives elsewhere needs its own root here.

`anthropic` and `responses_api` are not layers: the Responses API belongs to
OpenAI-compatible endpoints, and the Messages API has no such mode. An entry
that sets both is refused at startup instead of quietly picking one.

`/effort` reaches Anthropic as a thinking budget, so `medium` and above buy
reasoning before the answer; `off` disables it. As with any other model, this
window and this key are the endpoint's business, not ZettCode's: it does not
verify either before your first request.

### Keeping the key out of the file

Remove the `token` line from the model table, then launch from a terminal with
the key in its environment:

::: code-group

```bash [macOS / Linux]
export OPENAI_API_KEY="your-deepseek-api-key"
zettcode
```

```powershell [Windows]
$env:OPENAI_API_KEY = "your-deepseek-api-key"
zettcode
```

:::

The variable is named `OPENAI_API_KEY` even for DeepSeek. ZettCode does not read
`DEEPSEEK_API_KEY` or expand `${VARIABLE}` inside TOML strings; the one entry
that reads a differently named variable is an `anthropic` one, which falls back
to `ANTHROPIC_API_KEY`. An environment variable set this way applies to that
terminal and its child processes, not to all future terminal windows. These
commands can also enter your shell history; use your usual secret-management
method on a shared machine.

If several model entries omit `token`, they all receive the same environment
key. For endpoints with different credentials, give each entry its own `token`
or use separate config files.

### Configuring more than one model

Each `[[models]]` starts a new model entry. Its settings do not inherit from
the previous entry, so repeat the endpoint, key, and limits when needed:

```toml
[[models]]
model = "deepseek-v4-pro"
display_model = "DeepSeek Pro"
token = "sk-..."
base_url = "https://api.deepseek.com"
context_window = 1000000
compact_percent = 80
multimodal = false

[[models]]
model = "deepseek-flash"
display_model = "DeepSeek Flash"
token = "sk-..."
base_url = "https://api.deepseek.com"
context_window = 1000000
compact_percent = 80
multimodal = true
```

DeepSeek's current Flash model accepts images; Pro does not. If your gateway
does not expose Flash's vision capability, keep `multimodal = false` there too.

The first entry is selected at startup. Inside ZettCode, run `/model` and choose
an entry, or type `/model DeepSeek Flash`. Switching changes later requests;
it does not start a new session or interrupt a request already running. Entries
added with [`/config`](#adding-models-with-config) are available at once; after editing the
file by hand, restart to load new entries.

### Choosing the compaction threshold

For `context_window = 1000000` and `compact_percent = 80`, the automatic trigger
is about **800,000 tokens**. At `60`, it is about **600,000 tokens**. A lower
threshold leaves more room for a large tool result or the next reply, but may
summarize earlier and incur more model calls. `100` leaves no safety margin;
it is usually better to keep some room.

These are estimated thresholds, not a guarantee that every request fits: the
provider's counting and a large incoming result can differ from the estimate.
`/compact` summarizes immediately when you want to make room yourself. See
[Models and context](/guide/models) for what gets preserved.

## Optional features

### Complete config with the defaults made explicit

This is a **single complete file**, not a fragment to append to an existing
model entry. Replace the key, then remove sections you do not need. Every
optional setting below is at its default value.

```toml
[[models]]
model = "deepseek-v4-pro"
display_model = "DeepSeek Pro"
token = "sk-..."
base_url = "https://api.deepseek.com"
anthropic = false              # true would call Anthropic's Messages API
responses_api = false
multimodal = false
context_window = 1000000
compact_percent = 80

[transcript]
max_entries = 1024             # displayed blocks, not terminal lines
mouse_scroll_speed = 1           # rows one wheel event scrolls
tips = true                    # a small tip under Processing

[agents_md]
enabled = true                 # use project instructions

[ask_user]
enabled = true                 # allow the model to ask for your input

[skills]
enabled = true
roots = []                     # extra directories before the scope's own
scope = "both"                 # "both", "workspace" or "global"; see Skills and MCP

[mcp]
enabled = true
config = "~/.zettcode/mcp.json" # server definitions, not this TOML file
scope = "both"                 # "both", "workspace" or "global"

[compaction]
self = false                   # let the model compact its own context; /self-compact overrides per session

[plugins]
enabled = true                 # load installed third-party plugins
disable = []                   # entry-point names to skip

[update]
enabled = true                 # background PyPI version checks

[ui]
# theme = "nord"               # start in a palette by name (see Colours); unset follows the terminal
# pet = "cat"                  # which pet stands over the conversation (see The pet); unset is the cat
# pet_position = [1.0, 0.5]    # where it stands, across and down from 0 to 1; written when you drag it

[statusline]
# Every part of the header and status line is shown. Name one to hide it; /statusline edits these.
# ctx = false
# speed = false

[sessions]
enabled = true                 # let sessions message each other; `false` joins no broker

[harness]
subagent = true                # offer the `task` tool and its child profiles
subagent_max_iterations = 512  # model calls one child may make for one task
todowrite = false              # offer `todo_write`, which draws the plan panel
```

Put these top-level sections outside the model table, as shown. In TOML, keys
belong to the most recent table heading; an `enabled` key immediately under
`[[models]]` would be an invalid model key.

### Optional settings reference

| Table / key | Default | Effect and constraints |
| --- | --- | --- |
| `transcript.max_entries` | `1024` | Positive integer. Limits visible conversation blocks; older blocks leave the scrollback, but saved history and model context are not deleted. |
| `transcript.mouse_scroll_speed` | `1` | Rows one mouse-wheel event scrolls the conversation, from just above 0 to 20; a fraction such as `0.5` is a row every second event, and `3` is three rows a notch. Whatever the value, one frame moves the view at most half a screen. |
| `transcript.tips` | `true` | Show a small tip under the `Processing` row once a request has run for five seconds. `false` turns them off. |
| `agents_md.enabled` | `true` | Read `AGENTS.md` from the workspace and its ancestors. See [Project instructions](/guide/instructions). |
| `ask_user.enabled` | `true` | Allow the question panel with single-choice, multiple-choice, and typed answers. `false` removes that tool; it does not prevent all questions in normal prose. |
| `skills.enabled` | `true` | Discover skill names/descriptions and allow their instructions to be loaded when needed. |
| `skills.roots` | `[]` | Array of directory strings. Extra roots are searched in order before the scope's own directories; the first matching skill name wins. |
| `skills.scope` | `"both"` | Where skills live: `"both"` (the default) reads `<workspace>/.zettcode/skills` and `~/.zettcode/skills` together, the project's first so its version of a skill wins inside it; `"workspace"` reads only the project's, `"global"` only yours. See [Skills and MCP](/guide/skills-and-mcp#where-they-live). |
| `mcp.enabled` | `true` | Enable MCP tools when a server config exists. A missing default file means no servers are loaded. |
| `mcp.config` | `~/.zettcode/mcp.json` | Path to the user's JSON server configuration. Use an absolute path or `~` to make its location unambiguous. |
| `mcp.scope` | `"both"` | Which server files to read: `"both"` (the default) merges the user's file and `<workspace>/.zettcode/mcp.json`, the project's entry winning a name; `"workspace"` or `"global"` reads just one. A workspace file is a command a checkout asks you to run, so set `"global"` if you do not want a repository's servers started. |
| `compaction.self` | `false` | Whether a session lets the model compact its own context unless it chose otherwise. `/self-compact` opens a panel to set it for one session or for all; see [Self-compaction](/guide/commands#self-compaction). |
| `statusline.<part>` | `true` | Set a part of the header or the status line to `false` to hide it; every part not named is shown, except `pet`, which is hidden until you set it to `true`. The parts are `app`, `session`, `handle`, `workspace`, `model`, `effort`, `state`, `mode`, `self-compact`, `tokens`, `cache`, `speed`, `ctx`, `keys` and `pet` (the small companion over the conversation, see [The pet](/guide/interface#the-pet)); an unknown name is an error. `/statusline` edits the table for you. See [Choosing what is shown](/guide/interface#choosing-what-is-shown). |
| `plugins.enabled` | `true` | Load installed third-party plugins. Built-in UI functionality remains available when false. |
| `plugins.disable` | `[]` | Array of plugin **entry-point names** to skip, not necessarily their pip package names. |
| `update.enabled` | `true` | Check PyPI in the background and offer newer releases on a later start; does not automatically install them. |
| `sessions.enabled` | `true` | Register with the background session broker so this session can be messaged with `@name` and can message others; the model gets `list_sessions` and `send_message`. See [Talking between sessions](/guide/messaging). |
| `harness.subagent` | `true` | Offer the `task` tool, so the model can delegate to a child agent with its own context and session log. |
| `harness.subagent_max_iterations` | `512` | Model calls one child agent may make for one task. A child exploring or editing a real codebase makes dozens (the library's own default of 18 ended such tasks halfway); this is a ceiling against one that never stops, not a target. Children are also given your project's `AGENTS.md`. |
| `harness.todowrite` | `false` | Offer `todo_write`, whose checklist the shell draws in its plan panel. Keeping a plan costs turns, so it is off unless asked for. |

Example: keep less scrollback, add project-local skills, and disable remote
tool servers for a run configured from this file:

```toml
[transcript]
max_entries = 256

[skills]
roots = [".zettcode/skills", "~/team-skills"]

[mcp]
enabled = false
```

Merge this fragment into your existing file by editing the corresponding
sections; do not define the same table twice. The relative skill path resolves
against the **workspace**, so with `zettcode -w ~/projects/api` it means
`~/projects/api/.zettcode/skills`.

## Colours

Without a choice, ZettCode tries to detect the terminal's background and
selects a matching dark or light palette; those two leave the page background
to the terminal.

### Palettes by name

Every other palette has a name, and the name is a file. Sixteen ship with the program:

| Dark | Light |
| --- | --- |
| `catppuccin-mocha`, `tokyo-night`, `nord`, `gruvbox-dark`, `rose-pine`, `kanagawa`, `dracula`, `one-dark`, `solarized-dark`, `github-dimmed`, `ayu-mirage` | `catppuccin-latte`, `rose-pine-dawn`, `gruvbox-light`, `solarized-light`, `github-light` |

`/theme nord` switches to one for the current run. Typing `/theme ` and a space opens the menu of every palette, and
**the menu previews**: as you move the highlight with `↑` `↓` the whole interface, the conversation in front of you
included, is repainted in that palette. `Enter` keeps it; `Esc`, or deleting the draft, puts back the one you had.
These palettes paint their own page background, so they look the same in any terminal. So do `dark` and `light`
when you pick them by name; only the automatic choice at startup leaves the page to your terminal.

**The choice is remembered.** `/theme nord` writes `theme = "nord"` under `[ui]` in `config.toml` (one line; the
rest of the file is untouched), so the next start opens in it. Walking the menu with the arrows remembers nothing;
only `Enter`, or typing the name, does. If `config.toml` cannot take the line (it does not exist, or it spells
`[ui]` in a way that cannot be edited safely) the palette is still switched on, and you are told it will not last.

To start in one, name it in `config.toml`:

```toml
[ui]
theme = "nord"
```

The frame painted before the shell is built is already in that palette, so a light one does not flash dark first.
A palette only a plugin offers cannot be named that early; it arrives with the shell, one frame later.

### Adding your own

Put a file in `~/.zettcode/themes/` and its name is the palette's name: `~/.zettcode/themes/sunset.toml` is
`/theme sunset`, and it is in the menu the next time you open it, with no restart. The file is the same format as
`theme.toml` below, plus an optional one-line `description` shown beside the name:

```toml
description = "warm and low-contrast"
base = "dark"            # what any colour you leave out comes from

[ui]
surface_alt = "#3a322b"          # leave `background` out to keep the terminal's own page
accent = "#e0a458"
```

A file with the name of a shipped palette replaces it, which is how to adjust one: copy it, change what you
dislike, keep the name. `dark` and `light` cannot be replaced. A name is one word (letters, digits, `.`, `_`, `-`).
A file that cannot be read is still listed, and says why when you pick it.

The shipped palettes are listed with every component drawn in each of them in
`docs/internal/palettes.html`, which `make palettes` generates. The page is a build product and is not in the
repository: regenerate it after changing a palette or the theme code.

### One file over any palette

For a persistent custom palette, create `~/.zettcode/theme.toml`. This is a
separate file: do not paste these sections into `config.toml`.

```toml
base = "dark"                  # dark or light; defaults to dark

[ui]
accent = "#a7c080"
accent_bright = "#83c092"
surface_side = "#393a44"       # background for /btw messages
surface_peer = "#313244"       # background for messages between sessions
# background = "#232a2e"      # leave commented to use the terminal background

[tools]
read = "#89b4fa"
shell = "#fab387"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"            # Markdown `inline code`
```

Only named colours change; the rest come from `base`, or from the palette `[ui] theme` names when there is one
(the file is laid over it). A theme file takes
precedence over automatic light/dark detection. `/theme` can still choose a
palette during that run; it does not rewrite any file.

| Section | Colour keys |
| --- | --- |
| `ui` | `background`, `surface`, `surface_alt`, `surface_side`, `surface_peer`, `text`, `muted`, `subtle`, `accent`, `accent_bright`, `warning`, `error`, `diff_added`, `diff_removed`, `diff_added_fill`, `diff_removed_fill`, `border`, `focus`, `selection` |
| `tools` | `read`, `search`, `image`, `write`, `delete`, `shell`, `plan`, `subagent`, `message` |
| `code` | `inline`, `text`, `keyword`, `string`, `comment`, `number`, `function`, `builtin`, `operator`, `punctuator` |

`diff_added` and `diff_removed` colour the lines of an edit's diff and the `+N -M` beside a file. Left out,
they follow `accent` and `error`, so changing those changes the diff too; set them to colour the diff on its own.
`diff_added_fill` and `diff_removed_fill` are the bands behind those lines; left out, each is its line colour mixed
into the page, so the band follows the palette.

Colours use quoted six-digit hex strings such as `"#83c092"`. Do not use
`"green"`, three-digit hex, or the TOML string `"None"` for transparency; omit
`background` to keep the terminal's background. Check both text and background
contrast after changing a surface colour.

## Environment

| Variable | Effect |
| --- | --- |
| `ZETTCODE_CONFIG` | Select a different complete config file. |
| `OPENAI_API_KEY` | Key for model entries without a non-empty `token`. |
| `ANTHROPIC_API_KEY` | Key for `anthropic` entries without a non-empty `token`. |
| `TIKTOKEN_CACHE_DIR` | Where the token counter keeps the vocabulary it downloads once. Defaults to `~/.zettcode/cache/tiktoken`; the OS temp directory would be emptied sooner or later, and refilling it takes seconds. |
| `ZETTCODE_REDUCED_MOTION` | Set to `1` to suppress decorative sweep motion. |
| `ZETTCODE_BROKER_DIR` | Where the session broker keeps its files. Defaults to `~/.zettcode/broker`. |
| `ZETTCODE_BROKER_IDLE` | Seconds the broker stays after the last session leaves. Defaults to `30`. |
| `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY` | Standard proxy settings used by the model's HTTP client. |

Session storage stays in `~/.zettcode/sessions`, grouped by workspace. Do not
add `store`, `session`, `provider`, `theme`, or `reasoning_effort` to this config:
they are not supported keys. Use `-r` or `/resume` for a session, `/effort` for
reasoning, and `theme.toml` for colours.

## Checking the connection

Config validation checks spelling, types, and required values at startup. It
does **not** contact the API to verify a key or model id. The model connection
is created when you first use it, so `zettcode --dry-run` is not an API health
check.

If your first message fails:

1. Confirm the selected `model` is an id your endpoint offers.
2. Check `base_url` against the provider's API example, including whether it
   requires `/v1`.
3. Check the key belongs to that endpoint and the account has API access/balance.
4. Check the chosen API protocol and image support match the endpoint.

To test DeepSeek outside the TUI, set `OPENAI_API_KEY` as above, then run:

::: code-group

```bash [macOS / Linux]
curl https://api.deepseek.com/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"Reply with OK."}]}'
```

```powershell [Windows]
$headers = @{ Authorization = "Bearer $env:OPENAI_API_KEY" }
$body = @{
    model = "deepseek-v4-pro"
    messages = @(@{ role = "user"; content = "Reply with OK." })
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "https://api.deepseek.com/chat/completions" `
    -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

:::

This sends a small, billable API request. Do not post the authorization header
or your shell history in an issue.

## Common configuration mistakes

| Symptom | What to check |
| --- | --- |
| `No models configured` | Create the selected config file and add at least one `[[models]]` entry. |
| `Missing token for model ...` | Supply `token`, or set the variable of that API in the launching terminal: `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` for an `anthropic` entry. A placeholder is non-empty and only fails later at the API. |
| `Unknown config keys ...` | Use only the keys listed here. For example, `model_name` should be `model`. |
| `must be bool` / `must be int` | Use `true`, not `"true"`; use `1000000`, not `"1000000"`. |
| `Invalid config file ...` | Check quotes, table headings, and duplicate keys. TOML syntax errors include parser location information. |
| `cannot use both APIs` | An entry set `anthropic` and `responses_api`. Keep one: they are different protocols, not two halves of one. |
| `HTTP 401` / `HTTP 403` in an error | The server refused the token. Check `token` for that entry, or the variable of its API. The message the server gave is shown after the status. |
| `HTTP 404` in an error | The model id or the address is wrong for that endpoint. Check `model` and `base_url`. |
| `HTTP 429` / `HTTP 5xx` in an error | The provider is limiting or failing, not ZettCode. The request was already retried a few times before it was reported. |
| `Processing` with `nothing from the model for …` | The model has said nothing for a while. A long silence from a reasoning model is normal; press `Esc` to stop if it is not. |
| API rejects the model or protocol | Check the endpoint's supported model ids and its protocol: `responses_api`, or `anthropic` for the Messages API. The UI label is not the API id. |
| Image input is refused | Select a vision-capable model and enable `multimodal` only for that entry. |

Restart after correcting `config.toml`. For session, display, and MCP problems,
continue with [Problems and questions](/guide/faq).
