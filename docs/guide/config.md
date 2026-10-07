# Configuration

Start with one working model connection, then add only the settings you need.
ZettCode reads `~/.zettcode/config.toml` at startup. You do not need to create
every section: omitted optional settings keep their defaults.

This page uses DeepSeek as a concrete example. ZettCode still connects through
the **OpenAI-compatible API**; there is no `provider` setting.

## Files and when they apply

| File | Purpose | When a change takes effect |
| --- | --- | --- |
| `~/.zettcode/config.toml` | Model connections and optional features | Restart ZettCode. |
| `~/.zettcode/theme.toml` | Custom colours | Restart; `/theme` selects a built-in palette during a run. |
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
| `model` | string | Required | Exact model id accepted by the API, such as `deepseek-v4-pro`. Non-empty. |
| `display_model` | string | Model id | Your readable label, such as `DeepSeek Pro`. It is not sent as the model id. |
| `token` | string | `OPENAI_API_KEY` | API key for this endpoint. A non-empty file value takes precedence over the environment. |
| `base_url` | string | `https://api.openai.com/v1` | API root. Set it explicitly for DeepSeek or another non-OpenAI endpoint. |
| `responses_api` | boolean | `false` | `false` uses Chat Completions; `true` uses Responses. Choose a protocol the endpoint supports. |
| `multimodal` | boolean | `false` | Enable only for a model and endpoint that accept image input. |
| `context_window` | integer | `128000` | Positive context-window size in tokens, not characters or the output limit. |
| `compact_percent` | number | `80` | Automatic compaction threshold: greater than `0`, at most `100`. Decimals such as `75.5` are allowed. |

`base_url` should not include `/chat/completions` or `/responses`: the client
adds the route. DeepSeek's example root does not need `/v1`; other services
often do. Copy the **API root** from your provider's instructions rather than
guessing from its website URL.

When `multimodal` is false, image submission is refused locally with an error,
and the model is not offered the `view_image` tool. Setting it to true does not
add vision to a text-only model. See [Pictures and pastes](/guide/interface#pictures-and-pastes).

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
`DEEPSEEK_API_KEY` or expand `${VARIABLE}` inside TOML strings. An environment
variable set this way applies to that terminal and its child processes, not to
all future terminal windows. These commands can also enter your shell history;
use your usual secret-management method on a shared machine.

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
it does not start a new session or interrupt a request already running. Restart
after editing the file to load new entries.

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
responses_api = false
multimodal = false
context_window = 1000000
compact_percent = 80

[transcript]
max_entries = 1024             # displayed blocks, not terminal lines

[agents_md]
enabled = true                 # use project instructions

[ask_user]
enabled = true                 # allow the model to ask for your input

[skills]
enabled = true
roots = []                     # extra directories before ~/.zettcode/skills

[mcp]
enabled = true
config = "~/.zettcode/mcp.json" # server definitions, not this TOML file

[plugins]
enabled = true                 # load installed third-party plugins
disable = []                   # entry-point names to skip

[update]
enabled = true                 # background PyPI version checks
```

Put these top-level sections outside the model table, as shown. In TOML, keys
belong to the most recent table heading; an `enabled` key immediately under
`[[models]]` would be an invalid model key.

### Optional settings reference

| Table / key | Default | Effect and constraints |
| --- | --- | --- |
| `transcript.max_entries` | `1024` | Positive integer. Limits visible conversation blocks; older blocks leave the scrollback, but saved history and model context are not deleted. |
| `agents_md.enabled` | `true` | Read `AGENTS.md` from the workspace and its ancestors. See [Project instructions](/guide/instructions). |
| `ask_user.enabled` | `true` | Allow the question panel with single-choice, multiple-choice, and typed answers. `false` removes that tool; it does not prevent all questions in normal prose. |
| `skills.enabled` | `true` | Discover skill names/descriptions and allow their instructions to be loaded when needed. |
| `skills.roots` | `[]` | Array of directory strings. Extra roots are searched in order before `~/.zettcode/skills`; the first matching skill name wins. |
| `mcp.enabled` | `true` | Enable MCP tools when a server config exists. A missing default file means no servers are loaded. |
| `mcp.config` | `~/.zettcode/mcp.json` | Path to the JSON server configuration. Use an absolute path or `~` to make its location unambiguous. |
| `plugins.enabled` | `true` | Load installed third-party plugins. Built-in UI functionality remains available when false. |
| `plugins.disable` | `[]` | Array of plugin **entry-point names** to skip, not necessarily their pip package names. |
| `update.enabled` | `true` | Check PyPI in the background and offer newer releases on a later start; does not automatically install them. |

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

Without a theme file, ZettCode tries to detect the terminal's background and
selects a matching dark or light palette. Both built-in palettes leave the
page background to the terminal. `/theme dark` or `/theme light` switches for
the current run without editing any files.

For a persistent custom palette, create `~/.zettcode/theme.toml`. This is a
separate file: do not paste these sections into `config.toml`.

```toml
base = "dark"                  # dark or light; defaults to dark

[ui]
accent = "#a7c080"
accent_bright = "#83c092"
surface_side = "#393a44"       # background for /btw messages
# background = "#232a2e"      # leave commented to use the terminal background

[tools]
read = "#b8a6e0"
shell = "#7fbbb3"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"            # Markdown `inline code`
```

Only named colours change; the rest come from `base`. A theme file takes
precedence over automatic light/dark detection. `/theme` can still choose a
built-in palette during that run; it does not rewrite the custom file.

| Section | Colour keys |
| --- | --- |
| `ui` | `background`, `surface`, `surface_alt`, `surface_side`, `text`, `muted`, `subtle`, `accent`, `accent_bright`, `warning`, `error`, `border`, `focus`, `selection` |
| `tools` | `read`, `search`, `image`, `write`, `delete`, `shell`, `plan`, `subagent` |
| `code` | `inline`, `text`, `keyword`, `string`, `comment`, `number`, `function`, `builtin`, `operator`, `punctuator` |

Colours use quoted six-digit hex strings such as `"#83c092"`. Do not use
`"green"`, three-digit hex, or the TOML string `"None"` for transparency; omit
`background` to keep the terminal's background. Check both text and background
contrast after changing a surface colour.

## Environment

| Variable | Effect |
| --- | --- |
| `ZETTCODE_CONFIG` | Select a different complete config file. |
| `OPENAI_API_KEY` | Key for model entries without a non-empty `token`. |
| `ZETTCODE_REDUCED_MOTION` | Set to `1` to suppress decorative sweep motion. |
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
| `Missing token for model ...` | Supply `token` or set `OPENAI_API_KEY` in the launching terminal. A placeholder is non-empty and only fails later at the API. |
| `Unknown config keys ...` | Use only the keys listed here. For example, `model_name` should be `model`. |
| `must be bool` / `must be int` | Use `true`, not `"true"`; use `1000000`, not `"1000000"`. |
| `Invalid config file ...` | Check quotes, table headings, and duplicate keys. TOML syntax errors include parser location information. |
| API rejects the model or protocol | Check the endpoint's supported model ids and `responses_api`. The UI label is not the API id. |
| Image input is refused | Select a vision-capable model and enable `multimodal` only for that entry. |

Restart after correcting `config.toml`. For session, display, and MCP problems,
continue with [Problems and questions](/guide/faq).
