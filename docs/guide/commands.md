# Commands

Everything you type: slash commands and `@` references inside ZettCode, and the `zettcode` command line.

Type `/` to see the menu; it filters as you type, and `Enter` or `Tab` fills in the highlighted name. A command with
an argument takes it after a space. Only a name from the list is a command — `/var/log/syslog` and `/tmp is full`
are ordinary text and go to the model like any message.

A command with a fixed first word lists the words once you type a space: `/config ` offers `add`, `remove`, `list`
and `providers`, `/theme ` the palettes, `/model ` the configured models. `Enter` runs the highlighted one, so
`/model ` `↓` `Enter` switches without opening the picker.

## Slash commands

| Command | What it does | Example |
| --- | --- | --- |
| `/help` | List the commands and the keys. | `/help` |
| `/new` | Start a fresh session; the old one stays on disk. | `/new` |
| `/clear` | Clear the visible conversation, keeping this session. | `/clear` |
| `/resume` | Open a stored session: a searchable panel of recent ones, or one by id. | `/resume 01a10b75` |
| `/continue` | Carry on a request that was cut short. See [below](#continue). | `/continue` |
| `/fork` | Carry this conversation into a new session and continue there. | `/fork` |
| `/model` | Switch the model for later requests; plugin models are listed too. | `/model DeepSeek Pro` |
| `/config` | Add, change or remove models without editing the file. | `/config add --model gpt-4o --token sk-… --url …` |
| `/effort` | Set how much the model reasons, for the next request. | `/effort high` |
| `/permission` | Set how much of the shell may run without asking. | `/permission safe` |
| `/plugins` | Switch a plugin on or off; the change applies at the next start. | `/plugins disable recap` |
| `/harness` | The terminal's panel browses harnesses, tools and files; the chat gets the same command's state and its `gen` / `reset` / `use` / `save` / `fork` words. `gen` takes up to 4000 characters (120 shown in the row). | `/harness gen a tool that lists TODOs` |
| `/btw` | Ask a side question that never joins the conversation. | `/btw what is idempotent here?` |
| `/code-review` | Review the uncommitted changes; text says what to look for. | `/code-review check error handling` |
| `/bash` | Open a full-screen shell over the workspace. See [below](#bash). | `/bash git status` |
| `/theme` | Choose a palette; the menu previews each. | `/theme nord` |
| `/pet` | Choose the pet over the conversation. | `/pet whale` |
| `/context` | Show how full the context window is, what fills it, and the session's directory and file. | `/context` |
| `/usage` | Show what this project's sessions have spent. | `/usage` |
| `/hub` | Who is here, the daemons, and who talked to whom; the chat gets the sessions, daemons and message pairs as a document, without the graph layout. | `/hub` |
| `/compact` | Summarize the conversation now, instead of waiting for the window to fill. | `/compact` |
| `/statusline` | Choose which named parts of the header and status line are shown. | `/statusline hide ctx` |
| `/title` | Name this session; on its own, report the current name. | `/title users endpoint` |
| `/export` | Write this session to a standalone HTML file. | `/export review.html` |
| `/quit`, `/exit` | Leave; the shell prints the command that reopens the session. | `/quit` |

Commands come from the shell, the agent, and any [plugin](/guide/plugins) that registered one, and the menu shows
them in that order. A plugin cannot take a name that is already used, so `/model` always does what this page says.

Where a command has a panel, the keys inside it belong to the panel: `Esc` cancels, `Enter` applies. `/permission`
and `/theme` choose among a few words, so they list them in the menu instead. `/model` and `/resume` open a picker,
because a model name can hold spaces and a session is best chosen with its title beside it. `/effort` opens a rail
you slide; `/context` a page of bars you read.

Most commands wait until the request in flight ends. These do not: `/help`, `/plugins`, `/context`, `/usage` and
`/theme` only show something, `/bash` runs your own commands, `/title` writes a name nothing is reading, and
`/permission`, `/effort` and `/model` change what the next request uses. `/quit` does not wait for the answer, and
`/btw` and `/code-review` wait their turn. `/new`, `/clear`, `/resume`, `/fork`, `/compact`, `/export` and `/config`
answer "busy".

### Carrying on a cut-short request {#continue}

`/resume` opens an earlier session; `/continue` picks up the request that did not finish in this one. What it does
depends on how the request ended:

| How it ended | What `/continue` does |
| --- | --- |
| Stopped or failed before an answer, or after tools finished | Asks the model again, with nothing added. |
| Stopped while tools were running | Names the tools that were cut short and lets the model decide. A tool is never run again on its own. |
| The provider cut the reply off, or the reply hit the output limit | Asks the model to continue that reply. |
| The provider paused it | Hands the turn back to the provider. |
| Finished, declined, or the context window is full | Does nothing and says why; a full window needs `/compact` or `/new`. |

It uses the model and effort the next message would, and shows what it will do before it does it.

### Self-compaction {#self-compaction}

Self-compaction is the model compacting its own context when it judges the detail is no longer needed. It is on by
default (`[compaction] self` in `config.toml`), `/plugins` shows it as the `self-compaction` switch, and the status
line ends with `self-compact` while it is on. See [The context window](/guide/context).

### The shell panel {#bash}

`/bash` opens a full-screen command line over the workspace, and `/bash <command>` opens it already running that
command. It is your own shell run by your own hand: it asks no permission, the model sees nothing of it, and its
output is gone when you close the panel. It opens beside a running request.

| Key | What it does |
| --- | --- |
| <kbd>Enter</kbd> | Run the command. |
| <kbd>Tab</kbd>, <kbd>Shift</kbd>+<kbd>Tab</kbd> | Complete the word under the cursor; press again for the next candidate. |
| <kbd>↑</kbd> <kbd>↓</kbd>, <kbd>Ctrl</kbd>+<kbd>R</kbd> | Walk through, or search, earlier commands. |
| <kbd>Ctrl</kbd>+<kbd>C</kbd>, <kbd>Esc</kbd> | Stop the running command; with nothing running, close the panel. |

Each command runs in its own process in the workspace, with your own shell, and a program that asks a question gets
the end of its input instead. A bare `cd` stays for the next command. `fish` starts without its configuration.
History comes from bash, zsh, fish and PowerShell, and what you type here is kept in `~/.zettcode/command_history`.

### Token usage {#usage}

`/usage` opens what this project's sessions have spent, in three views: by model, by session, and a calendar of the
days. Every field, and where it differs from the status line, is in [Token usage](/guide/usage).

## `@` references

`@` pulls a resource into a message: a file of the workspace by path, a [skill](/guide/skills-and-mcp) by name, or
another [session](/guide/messaging).

> what does @packages/zettcode/src/zettcode/cli.py do?

Type `@` and the menu lists them, files with their size. A file reference sends the path, not the file: the model
reads it with its own tools, so it costs a sentence of context rather than a file's worth. A directory points the
model at searching. The draft you typed is what is stored, so reopening the session shows `@path` again. Each chip
is removed with one **Backspace**.

## The `zettcode` command line

`zettcode --help` lists everything the command line takes, which is short.

| Flag | What it does |
| --- | --- |
| `-v`, `-V`, `--version` | Print the version — ZettCode, the zett-agent it runs on, and Python — and exit. Quote it when you report a problem. |
| `-w`, `--workspace DIR` | The directory to work in. Defaults to the current directory. |
| `-r`, `--resume SESSION` | Open a stored session instead of starting a new one. |
| `--full`, `--auto`, `--yolo` | Run shell commands with full access and without asking, for this run. The same as `/permission full`. |
| `--dry-run` | Run the startup, paint one frame, and exit. Useful for profiling. |

Subcommands are separate programs under the same executable:

| Subcommand | What it does |
| --- | --- |
| `resume SESSION` | The same as `--resume`; `-w DIR` may go before or after it. |
| `update`, `upgrade` | Install the newest release and exit. See the [FAQ](/guide/faq#a-new-version-is-offered). |
| `doctor` | Ask every model in your config one short question and print which answer, how fast, or why not. Exits 1 if one does not. |
| `prompt` | Send one prompt, print the answer, exit. See [below](#zettcode-prompt). |
| `daemon` | Start, list, log, stop or kill a [background agent](/guide/daemons). |
| `broker` | Run the local [session broker](/guide/messaging). |
| `gateway` | Serve the [web gateway](/guide/gateway). |
| `plugin` | Install, remove and switch [plugins](/guide/plugins). |

## `zettcode prompt` {#zettcode-prompt}

`zettcode prompt` sends one prompt, prints the answer, and exits — for a script or a pipe. Without `-m` and `-s` it
uses the first model in the config file and a new session.

```bash
zettcode prompt "explain what this repository does"
git diff | zettcode prompt "review this change"
zettcode prompt -m "Claude Sonnet" -s 01a10b75 "and the tests?"
zettcode prompt --continue -s 01a10b75
```

| Option | What it does |
| --- | --- |
| `PROMPT` | What to ask. Leave it out, or give `-`, to read it from standard input. |
| `-m`, `--model NAME` | The model, by the name `/model` lists. |
| `-s`, `--session ID` | Continue a stored session. |
| `-c`, `--continue` | No prompt: pick up a cut-short request, as [`/continue`](#continue) does. Needs `-s`. |
| `-e`, `--effort LEVEL` | The reasoning level. |
| `-w`, `--workspace DIR` | The directory to work in. |

Standard output holds the answer and nothing else; the tools used and `session: <id>` go to standard error. Nobody
can be asked here, so the shell permission is always `auto`: the model's commands run without asking. Use it only in
a workspace you would trust with a shell.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Answered. |
| `1` | The run failed or stopped early. `doctor` also exits 1 when a model does not answer. |
| `2` | Arguments that cannot be used. |
| `3` | `--continue` found nothing to pick up. |

## Next steps

- [Sessions](/guide/sessions): where a conversation is stored, and how to come back to it.
- [The interface](/guide/interface): what every row on the screen means.
- [Configuration](/guide/config): every key, and the models a command can add.
- [Plugins](/guide/plugins): the commands a plugin adds.
