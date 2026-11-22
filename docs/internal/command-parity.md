# The command surface every front end shares

The terminal, the server and the editor behind it offer slash commands. This page is the contract they are held to:
which commands exist, which process owns the effect, and which are deliberately one front end's own. It exists
because the three registries — the terminal's `ctx.tui`, a plugin's `ctx.commands`, and the editor's `/` menu — can
drift apart without a test noticing.

## What "aligned" means

A command is aligned when every front end that offers it produces the same effect, not the same screen. `/usage` is a
full-screen page in the terminal and a webview panel in the editor, and that is fine: both read `GET /usage` and show
the same numbers. `/code-review` is aligned when both front ends run the same preset through an ordinary turn.

## The three kinds of command

| Kind | Effect | Lives in | Examples |
| --- | --- | --- | --- |
| **Turn** | starts a model turn, or asks a side question | a plain command in a distribution every process loads (`ctx.commands`) | `/code-review`, `/harness gen`, `/recap` |
| **State** | changes the session, configuration, model or permission | a server/SDK endpoint; each front end draws its own picker or form | `/new`, `/resume`, `/fork`, `/model`, `/config`, `/plugins`, `/export` |
| **View** | opens a page, or shows data with no state change | the front end that has the page; the server supplies the data | `/usage`, `/context`, `/hub`, `/monitor`, `/help` |

`/quit` and `/exit` are lifecycle, and belong to whichever front end has a window to close.

## The rule that keeps them apart

**One name, one form per process.** A plugin that has both a plain and a terminal form branches once, in `activate`:

```python
if ctx.tui is None:
    ctx.commands.register("/name", summary, self.plain_handler, when_busy=...)
    return
ctx.tui.register_command("name", summary, self.tui_handler, when_busy=...)
```

It never registers both: the shell merges the two registries into one namespace and refuses a duplicate. A plugin
that only draws things starts with `if ctx.tui is None: return`; a plugin whose effect needs no screen must register
the plain form instead of returning.

A plain command's words cross `GET /commands` as `subcommands`, and the ones that cannot run alone as `needs_more`; a
front end fills one of those in and waits for the rest, rather than running it and starting a turn on one Enter.

Plain commands get their model access from the services, not from the shell: `LLM` (`ModelAccess.ask`) for a side
question, `HARNESS` for the harness switch, `SESSION_STORE`/`USAGE_LEDGER` where they apply. `HOST_LINK` and
`CommandHost` are for drawing and for the transcript, and a command that needs them is a terminal command.

## Where each command belongs

| Command | Kind | Plain | Terminal | Editor | Notes |
| --- | --- | --- | --- | --- | --- |
| `/code-review` | Turn | yes | same plain command | same plain command | moved to `zettcode-sdk`; `GET /commands` lists it |
| `/harness` | Turn + View | `gen` / `reset` | panel + TUI preset | plain form | the panel needs a screen; the switch and the preset do not |
| `/recap` | Turn | `LLM.ask` | own TUI form | plain form | the idle recap is terminal-only until turn hooks leave `ctx.tui` |
| `/monitor` | View + state | `on` / `off` / `images` / `export` | panel | text + exported file | the panel needs a screen; the switches and export are the host's session and workspace |
| `/new`, `/resume`, `/continue`, `/fork`, `/compact`, `/title`, `/model`, `/effort`, `/permission`, `/config`, `/export`, `/doctor`, `/name`, `/stop` | State | — | own picker/form | own picker/form | endpoints exist; the editor owns its menus and save dialogs |
| `/plugins` | State + View | — | page | panel | switches a plugin for the next start |
| `/usage`, `/context` | View | — | page | panel | same endpoints |
| `/help` | View | — | page | document | the editor builds it from its command list |
| `/hub` | View | document | page | document | the host reads the broker and daemons; the graph is the terminal's page |
| `/ssh` | State + View | — | panel | no | terminal-only: it selects the target the terminal's tools run against, and the panel needs a screen. A daemon inherits the target as plugin state instead |
| `/theme`, `/pet`, `/statusline`, `/bash`, `/quit`, `/exit` | Terminal | — | yes | no | terminal interaction or window lifecycle; not a missing editor feature |

Editor-only names — `/rename`, `/name`, `/doctor`, `/stop` — are the editor's spellings of a state change or an
endpoint it already has. `/rename` is an alias of `/title` and must not be a second visible command in the menu.

The first pass is in place: `/code-review` reaches both front ends; the editor queues a preset with
`when_busy="queue"` (and a side question), takes `/resume <id>` and `/export <path>`, spells `/title` with `/rename`
as an alias, and offers `/config`, `/plugins` and `/help`. `/harness gen|reset` and `/recap` now reach the editor as
plain commands too, and `/hub` and `/monitor` get documents, text and an exported file where the terminal has pages.

## Keeping the table honest

The table is the review checklist; the code is held by tests:

- `packages/zettcode-server/tests/test_sdk_plugins.py` builds a real headless client and asserts the plain commands it
  lists, including that `/code-review` answers with a preset that names the focus and no host.
- `packages/zettcode-app/tests/test_plugins.py` asserts that the same review reaches a terminal, that the three
  headless-only commands do not, and that `/hub` is not registered beside the terminal's page.
- `packages/zettcode-commands/tests/test_plugin.py` asserts the terminal command groups and that the review is not
  one of them.
- `packages/zettcode-sdk/tests/test_review.py` asserts the brief's levels, the `REVIEW_NAME` placeholder, and the
  turn the command returns.
- `packages/zettcode-jit-harness/tests/test_plain_harness.py` asserts the screenless `/harness gen|reset`, the lock
  refusal, and the usage words.
- `packages/zettcode-recap/tests/test_recap.py` asserts the screenless `/recap` asks through `LLM` and answers with a
  document.
- `packages/zettcode-sdk/tests/test_hub.py` asserts the `/hub` document and the plain command that opens it.
- `packages/zettcode-monitor/tests/test_monitor.py` asserts the screenless `/monitor` switches and exports through the
  host's session and workspace.
- `clients/vscode/test/` asserts the editor's own menu, its aliases, the queue, and the messages each command posts.

When a command is added, add it to this table **and** to the side that is supposed to offer it. A command that is in
neither the plain registry nor the editor's own list is a command that is silently sent to the model as prose, which
is the failure this page exists to catch.
