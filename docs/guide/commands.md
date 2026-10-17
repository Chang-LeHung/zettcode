# Commands

Type `/` to see the menu; it filters as you type, and `Enter` or `Tab` fills in
the highlighted name. A command with an argument takes it after a space —
`/title users endpoint` — and running one never leaves the screen.

A command that takes a fixed first word lists it once you type the command and a space:
`/config ` offers `add`, `remove`, `list` and `providers`, `/theme ` the palettes, `/permission `
its levels, `/model ` the models you have configured. `Tab` fills one
in, and `Enter` picks the highlighted one and runs it at once — `/model ` then `↓` `Enter` switches
the model without opening the picker. The two `/config` words that need more (`add`, `remove`) are only filled in.

Only a name from the list is a command. Anything else that starts with a slash — a path such as
`/var/log/syslog`, a typo, `/tmp is full` — is ordinary text and goes to the model like any other message.
A command is drawn in a different colour as soon as it is one, so you can see which it will be.

| Command | What it does |
| --- | --- |
| `/help` | List the commands and the keys. |
| `/new` | Start a fresh session. The old one stays on disk. |
| `/clear` | Clear the visible conversation, keeping this session. |
| `/resume` | Pick a recent session from a panel; `/resume <id>` opens one directly. |
| `/continue` | Carry on a request that was cut short — stopped with `Esc`, failed, dropped by the provider, or ended at the output limit — from where it stopped. See [Carrying on](#continue). |
| `/fork` | Carry this conversation into a new session and continue there. |
| `/model` | Pick the model for later requests from a panel. |
| `/config` | Add, change or remove models, and set whether one takes images, its context window and when it is compressed, without editing the file: `/config`, `/config add <provider> …`, `/config remove <n>`. See [Adding models with /config](/guide/config#adding-models-with-config). |
| `/effort` | Choose how much the model reasons with a knob on a rail: `/effort` opens it, ← → slide, `Enter` applies; `/effort high` sets one directly. |
| `/permission` | Choose how much of the shell may run without asking: `/permission` lists the levels in the menu; `/permission safe` sets one. |
| `/btw` | Ask something that is answered here but never joins the conversation: `/btw <question>`. |
| `/theme` | Choose a palette by name: `/theme` opens the menu, which previews each palette as you move through it; `/theme nord` switches in one step. Your own palettes (`~/.zettcode/themes/<name>.toml`) are in the menu too. |
| `/context` | Show how full the context window is, how close it is to being compacted, and what is filling it — as bars, with the file this session is stored in. See [The context window](/guide/context). |
| `/usage` | Open a page of what this project's sessions have spent: tokens by model, by session, and a calendar of the days. See [Token usage](/guide/usage). |
| `/compact` | Summarize the conversation now, instead of waiting for the window to fill. |
| `/self-compact` | Self-compaction: let the model compact its own context when it decides the detail is no longer needed. `/self-compact` opens a panel with a rail for this session and one for the default of every session; `on` / `off` / `default` set this session, `global on` / `global off` write the default into `config.toml`. See [Self-compaction](#self-compaction). |
| `/title` | Name this session: `/title users endpoint`. On its own, it reports the current name. |
| `/export` | Write this session to a standalone HTML file: `/export [path]`. |
| `/quit`, `/exit` | Leave. The shell prints the command that reopens the session. |

Commands come from three places, and the menu shows them in that order: the
shell's own (above), the agent's (`/new`, `/compact`, `/export`), and any
[plugin](/guide/plugins) that registered one. A plugin cannot take a name that
is already used, so `/model` always does what this page says.

## Carrying on a cut-short request {#continue}

`/resume` opens an earlier *session*; `/continue` picks up the *request* that did not finish in this one. The history says how
it was interrupted, and what is done depends on that:

| How it ended | What `/continue` does |
| --- | --- |
| Stopped or failed before the model answered, or after tools finished | Asks the model again, with nothing added. |
| Stopped while tools were running | Tells the model which tools were cut short and that they may or may not have run, and lets it decide. **A tool is never run again on its own.** |
| The provider cut the reply off | Tells the model it was interrupted and to start that reply again. |
| The reply hit the output limit | Asks the model to carry on from where it stopped. |
| The provider paused it | Hands the turn back to the provider. |
| Finished, or declined, or the context window is full | Does nothing and says why: a declined request would be declined again; a full window needs `/compact` or `/new`. |

It uses the model and effort the next message would, and shows what it is about to do before it does it.

## Self-compaction {#self-compaction}

Normally the context is summarized for you: automatically when it reaches the model's `compact_percent`, or
when you type `/compact`. **Self-compaction** adds a third way. The model is given a `compact_context` tool and
can summarize its own earlier conversation when it judges that finished work no longer needs to stay in view,
for example after a completed subtask. It never compacts the turn it is in: the current request, with its
tool calls and results, is kept exactly as it is, and nothing happens when there are no older turns or the
summary would not be smaller. `/compact` and the automatic threshold keep working either way.

It is off by default. Two places decide it, and the more specific one wins:

| What | How | Applies to |
| --- | --- | --- |
| The default | `[compaction] self = true` in `config.toml`, or the second rail of the panel, or `/self-compact global on` / `off`, which edit that line for you | Every session that has not chosen for itself |
| A session's own choice | The first rail of the panel, or `/self-compact on` / `off` | That session only; saved with it and restored when you resume or fork it |
| Give the choice back | The panel's `default` stop, or `/self-compact default` | That session follows the default again |

So turning the default on does not change a session where you chose `off`, and turning it off does not change
one where you chose `on`.

### The panel

`/self-compact` on its own opens a panel in the style of `/effort`, with two rails:

```text
Self-compaction                                     in effect here: on (not applied)

▸ This session   ●━━━━━━━━━━━━━━━━━━━━━━━━◉      default (off)    off     on
  Every session  ◉────────────────────────○      off              on
```

- **This session:** `default` (no choice of its own), `off`, or `on`. The `default` stop says what it would
  be right now, `default (off)`, and changes as you move the lower rail.
- **Every session:** `off` or `on`, the config default.
- ↑ ↓ pick the row, ← → slide the knob, a click on a stop sends it there. Nothing changes until `Enter`,
  which applies both rails; `Esc` applies nothing. The title shows what would be in force and says
  `(not applied)` while the knobs are away from where they started.
- If the default cannot be written (there is no `config.toml`) you are told, and the session's choice is still
  applied. A session another process has open keeps what it has, and only the lower rail moves.

While it is on, the status line ends with `self-compact`. The typed forms still work for scripts and habit:
`/self-compact on|off|default`, and `/self-compact global on|off`. With a word, the command reports what now
applies and why. `global` needs an existing `config.toml`; it does not create one, and it reports a file it
cannot safely edit instead of guessing.

## While a request is running

Most commands wait until the request is over, because they change what it is standing on. These do
not: they only look at the session or change a setting the request does not depend on, so they run
at once, beside the request.

| Runs at once | Why it is safe |
| --- | --- |
| `/help`, `/context`, `/usage`, `/theme` | They only show something. `/context` reports the last request measured; `/usage` reads what the stored sessions recorded. |
| `/title` | Names the session; nothing running reads it. |
| `/permission` | The next shell command asks the level again, so a change lands in the request that is already running — `/permission auto` in the middle of a long task is the point. |
| `/effort` | A request starts with the effort it had, so the change applies from the next request; the running one is not touched. A level the active model does not take (see [`reasoning_efforts`](/guide/config#reasoning-levels-a-model-takes)) is refused with the ones it does. |
| `/self-compact` | The tool is offered when a request starts, so a change applies from the next request; one the model has already asked for is dropped if you switch it off. |
| `/quit`, `/exit` | Leaving does not wait for the answer. |
| `/btw` | Waits its turn and then answers, as before. |

`/model`, `/config`, `/clear`, `/new`, `/resume`, `/fork`, `/compact` and `/export` still say "busy":
they change the model a request started with, the transcript it is writing into, or the session it is
part of. A [plugin](/guide/plugins#while-a-request-is-running) chooses for its own commands.

## Token usage {#usage}

`/usage` opens a full-screen page of what the sessions in this project have spent, in three views: by model, by
session, and a calendar of the days. `Tab` switches between them, and `Esc` closes the page.

Every field, the three tabs, what is and is not counted, and where the page differs from the status line are in
[Token usage](/guide/usage).

## Panels, and the menu for short choices

`/permission` and `/theme` choose among a few fixed words, so they have no panel: typed
on their own they put the command and a space in the composer, and the menu lists the words with a
note each and `(current)` on the one in force, highlighted to begin with. `Up` / `Down` move and
`Enter` applies the highlighted one.

`/effort` opens a panel of its own: a rail with a node and a name for every level, and a knob on it.
`←` / `→` (or `Home` / `End`, or a click) send the knob along the rail, which it travels with a short
slide, lighting the stretch behind it in the colour of the scale, green for the cheap end and warm for the
dear end. Moving it changes nothing; `Enter` applies the level under it, and that is when the header's own
reasoning gauge plays. `Esc` puts the panel away and leaves the level as it was.

`/model` and `/resume` open a picker: a model can have a name with spaces in it, and a session is
best chosen with its title beside it, which a menu word cannot be. `Up` / `Down` move,
`Enter` accepts, and `Esc` goes back without changing anything. `/context`
opens a page of bars rather than a choice: read it, then press `Esc` to close it. The
report names the file this conversation is written to under `~/.zettcode/sessions`,
so a number that looks wrong leads somewhere you can look. Its total is what the
provider billed for the last request, the same figure the status line shows; the
local count only supplies the proportions, so each row is that source's share of the
total and the rows add up to it. A session restored from disk has no provider count
for the dialogue it was rebuilt from, and then the rows are the local counts. Two
rows — the environment notes
and the tool schemas — only exist inside a request the runtime has assembled, so
a report taken before the first turn of a session shows them as `pending` rather
than leaving them out. An image is counted as an estimate rather than by the size of
what was pasted, because a provider bills one by its dimensions and detail. The conversation
underneath stays visible.

Switching the model, the theme, or the effort re-lays out the screen: the header
and the status line read from the same state the panels write to, so they show
the new value before you send the next message.

## Everyday examples

These are commands to type **inside ZettCode**, not in your system shell.
For a command with an argument, complete its name, add a space, type the
argument, and press `Enter` to run it.

| Goal | What to type | What happens |
| --- | --- | --- |
| Name the current task | `/title Fix login timeout` | The session list and status show the new title. |
| Use a different configured model | `/model DeepSeek Pro` | Later requests use that model; the current session remains. |
| Give a difficult review more reasoning | `/effort high` | The selected reasoning level changes for later requests. |
| Ask about a term without affecting the main task | `/btw What does idempotent mean here?` | A read-only side question is answered separately from future context. |
| Save a reviewable record | `/export review.html` | Write an HTML export into the workspace. |
| Continue an earlier conversation | `/resume 01a10b75` | Restore that session from the current workspace's store. |

The session id above is illustrative; use an id from your own `/resume` list.
A model name must match an entry in your config, and a plugin command must be
installed before it can run.

### New conversation, clear screen, or compact?

| Command | Visible conversation | What the next model request remembers |
| --- | --- | --- |
| `/new` | Starts fresh | A new session, without the old conversation. |
| `/clear` | Clears the display | The existing session context remains. |
| `/compact` | Adds a compaction result | A summary plus recent context replace older detail. |

None of these commands deletes saved session files. Use `/new` for an unrelated
task, `/clear` to tidy the display, and `/compact` to reduce what later requests
carry. Changing models alone is not a context reset.

## `@` resources

`@` pulls a resource into a message. Two providers offer them: the workspace's
files, by path, and your [skills](/guide/skills-and-mcp), by name.

> what does @src/zettcode/cli.py do?

Type `@` and the menu lists both, files with their size. What a file reference
sends is the path, not the file: the model reads it with its own tools, so a
reference costs one sentence of context rather than a file's worth. A directory
is named as a directory, which points the model at searching rather than reading.
The listing is what you are likely to type rather than everything on disk — the
version control and dependency directories are skipped, and a very large tree is
listed up to a cap.

The draft you typed is what gets stored and shown, so reopening the session
later gives you `@src/zettcode/cli.py` back rather than the expanded
text. A skill is told to load itself — the model sees the name and reads the body
when it needs it, which is what keeps a large skill catalog out of every request.

Resources work anywhere in a message, more than one per message, and each is
removed by a single **Backspace** when the cursor is right after the chip.

For example, with `code-review` and `test-plan` skills installed:

```text
Review @code-review the current diff, then use @test-plan to suggest missing tests.
```

Both references keep their position in the sentence; the text around them is
preserved. They tell the model which skill to use, not to paste its entire body
into every request. See [Skills and MCP](/guide/skills-and-mcp) for installation.
