# The interface

The screen is a fixed frame around a scrolling conversation: the composer stays near the bottom, and a panel covers
the lower part while you choose.

```
  ▐ zettcode  New session · @api · ~/projects/api   DeepSeek Pro · high  ← header
 ─────────────────────────────────────────────────────────
 ● Read src/api/users.py · 199 lines                       ← transcript
 ● Edit src/api/users.py +24 -6                         (scrolls)
 ● Bash pytest tests/test_users.py
 ─────────────────────────────────────────────────────────
   ▸ panels open here: model, context, sessions           ← panel
 ─────────────────────────────────────────────────────────
   /model  /resume  /context                              ← completions
 › add a limit/offset window to GET /users                ← composer
   ● ready  ↑18.4k ↓900 · ctx 12.3%                       ← status line
```

## The header

The left side names the program, the session and the workspace.

- The session is `New session` until it has a title. When [messaging](/guide/messaging) is on, its `@name` follows.
- The workspace is shortened to its last useful part.
- On a narrow terminal the title is cut first, then the workspace.

The right side names the model and the effort the **next** request will use.

## The transcript

Every event gets a row, in the order it happened.

- **Your message** is marked `›`.
- **Thinking** is collapsed to one row; `Ctrl-T` or a click opens the newest block, or each block on its own.
- **Tool calls** read like a log: `Read src/app.py · 199 lines`, `Bash pwd`, `Edit app.py +24 -6`, `Write src/new.py
  +40`, `Searched TODO in src`.

  A successful edit shows the change under its row: removed lines red, added lines green, one unchanged line either
  side for context. A write shows every line as added. A failed edit shows its error instead. The first five rows
  stay visible and the rest sit behind a click, up to forty; a long line is cut.
- **The files a request changed** are listed once, when it ends, above `Processed for …`. One file is one line
  (`Changed src/app.py +4 -1`); several are a short list (`Changed 3 files`, eight entries, then `and N more`). Paths
  are relative to the workspace. Only successful edits, writes and deletes count, and a stopped request still
  reports what it had done. Changes a shell command made are not seen.
- **The answer** is Markdown, with tables that survive wide CJK characters and HTML entities drawn as the character
  they name.
- **The running request** is one row pinned to the bottom: `✦ Processing (8s · ^C/Esc to interrupt)`. When the
  request ends it becomes `Processed for 12s · 22:53`, followed by what it spent: `↑12.3k ↓1.2k · 87.0% cached · 3
  model calls · 62 tok/s · 5 tool calls, 1 failed`.

  If the model says nothing for twenty seconds, the row says so in the warning colour. After five seconds a tip
  hangs under the row from the same `└` a tool result uses, replaced every fifteen seconds; `tips = false` under
  `[transcript]` turns them off.
- **A failed request** gives what the library reported and, in brackets, what the server answered, and names the
  setting to check. A provider or network failure ends with `/continue tries the request again from where it
  stopped.` A credential is replaced with `…`, so the line can be pasted into an issue.
- **A reply that did not finish** says why — the output limit, a provider that cut it off or paused, a full context
  window, a declined answer — and what to do: `/continue`, `/compact`, `/model`.
- **Notices** — a copied selection, a refused command, an exported file — are muted one-liners.

`Page Up` / `Page Down` and the wheel scroll, one row per event; no frame moves more than half a screen.
`transcript.mouse_scroll_speed` speeds the wheel up. Scrolled up, a `↓ back to bottom` badge appears; `Esc` returns
to the newest line or stops a running request.

## The composer

The `›` prompt grows with the draft, up to a share of the screen.

- **Enter** sends. **Alt-Enter** or **Shift-Enter** adds a newline.
- **`/`** opens the command menu, **`@`** the resource menu (skills, files and running sessions). `Up` / `Down`
  choose, `Enter` or `Tab` fills in, `Esc` closes.
- A paste over 512 characters, or taller than the composer grows, becomes a `[pasted text 6012 chars]` chip.
  `Backspace` removes it whole; the text returns when you send.
- **Ctrl-V** attaches an image as an `[image #N]` chip. Text and images keep the order you wrote them in.
- A `/command` or `@resource` is coloured only when it is real: the command must exist and be the first word.
  `Backspace` deletes a fake one by character, and a real one whole.

## Typing while a request runs

Type while the model works and press Enter, and ZettCode asks what the message is:

```text
You sent a message while ZettCode is working. What should it do?

› then open a pull request

▸ 1. Follow up  send it after this request finishes (f)
  2. Steer      hand it to the agent now; it replaces the rest of the current task (s)

enter choose · f follow up · s steer · esc keep editing the draft
```

`f` and `s` pick a row, `Enter` takes the highlighted one (follow up), and `Esc` keeps your draft. When only one
answer is possible — a command such as `/compact` cannot be steered — nothing is asked.

**Steer** puts the message in a `↳ steer` list above the composer. The agent reads it at its next safe point and
drops the rest of the current task; up to eight can queue. It is a new instruction for the same task and does not
undo edits. Once the agent has it, it cannot be changed.

**Follow up** puts the message in a `• follow-up` list directly above the composer. It goes out as its own message
when the conversation ends well — one at a time, in the order shown, up to eight. You can move, edit, convert to a
steer or delete one; the keys are in [Keys and mouse](/guide/keys).

Stopping a request does not send the list or lose it: it reads `held until your next reply completes`, and goes out
after the next reply that completes. `/new`, `/resume` and `/fork` hand the list back as text in the composer, and a
steering message the agent never read goes back there too. If you need the agent to stop now, press `Esc`.

## Panels and approvals

A command that needs a choice opens a panel. `Up` / `Down` move, `Enter` accepts, `Esc` goes back to the composer,
and the transcript waits underneath.

- `/model` picks the model for later requests. `/resume` picks a recent session, with its title and when it changed.
- `/context` shows what is filling the context window. `/usage` shows what this project's sessions spent, and takes
  the whole screen. See [Token usage](/guide/commands#usage).
- **Approvals** ask whether to run a shell command.

`/theme` and `/permission` use the command menu instead; `/effort` opens a rail you slide with `←` `→`.

When the model asks a question — a format, a file, whether to continue — the panel is as tall as the question.
`Up` / `Down` and `Enter` work the choices, and typing answers in your own words. `Esc` declines.

### Approvals

`bash` is the tool that asks. `/permission` sets how often, between requests:

| Level | What happens to a shell command |
| --- | --- |
| `deny` | None runs. The model is told commands are off and carries on with the file tools. |
| `ask` | Each command waits for your answer. A new session starts here. |
| `safe` | Every command runs without asking, inside an operating-system sandbox. |
| `full` | Every command runs with your own access, without asking and without a sandbox. (`auto` still works.) |

The level covers the shell only. File edits and MCP tools never ask, so `deny` is not a read-only mode. A new session
starts at `ask`; a resumed session keeps the level it last used.

At `ask` the panel shows the command and its directory.

| Key | Meaning |
| --- | --- |
| `y` | Run it this once. |
| `p` | Run it, and remember this exact command for the session. The memory is the command text, not the directory. |
| `s` | Run it and stop asking: later commands run in the sandbox. Not offered at `safe`. |
| `a` | Run it and stop asking: full access, no sandbox. |
| `Esc` | Refuse. The agent is told the command failed and can react. |

### What the `safe` sandbox allows {#the-safe-sandbox}

On macOS the sandbox is Seatbelt (`sandbox-exec`); on Linux it is bubblewrap (`bwrap`). A command inside it can:

- **write** the workspace and the temporary directory, and nowhere else;
- **read** the rest of the machine, except where credentials live (`~/.ssh`, `~/.aws`, `~/.gnupg`);
- not reach the network, unless you set `network = true` under `[shell]`;
- not rewrite `.git/hooks`, `.git/config` or a shell start-up file, even inside the workspace;
- see only a short list of environment variables.

Windows, and Linux without `bwrap`, have no such sandbox: `safe` runs commands that only read and asks for anything
else.

`safe` runs a command without asking only when every part of it is on a list of reading programs (`ls`, `cat`,
`grep`, `git status`, …). `;`, `&&`, redirects and `$(…)` ask. A read-only command can still print a secret in the
workspace: `safe` means nothing changes, not that nothing is seen. A `git` configuration can name programs to run:
use `ask` where one may live.

## Side questions

`/btw <question>` asks something the model answers from what it already knows. The answer appears as any other turn,
marked `btw ›` on a tinted surface of its own.

It is written to the session file but never replayed into the model's context, so later turns do not know it.
It comes back in the transcript on resume, but not in an [export](/guide/sessions#exporting). Only the reading tools
are offered, so an edit cannot slip out of it. A side question asked during a turn waits for it; its tokens still
count and it does not trigger compaction or naming.

## Pictures and pastes

**Ctrl-V** reads the clipboard and inserts an `[image #N]` chip where the picture belongs. PNG, JPEG, WebP and GIF
are sent as image parts in that position.

Over `ssh` it cannot see a picture copied on your machine: put the file on the server and refer to it by path.

A restored session shows the chip, not the picture. A model with `multimodal = false` refuses the attach.
See [Models](/guide/models).

## Copying over `ssh` {#copying-over-ssh}

On a server, a selection is copied through your terminal with OSC 52, so it lands on the machine you sit at; the pill
says `sent`, because the program cannot see whether the terminal accepted it. If a forwarded display makes the
server's clipboard the right one, set `ZETTCODE_CLIPBOARD=system`. A terminal that ignores OSC 52 copies nothing, so
hold its own modifier (<kbd>Shift</kbd> or <kbd>Option</kbd>) and drag.

## The status line

The left half says what is happening and what it cost; the right half keeps `^C/Esc to interrupt` and `^D exit` in
view.

| Piece | Meaning |
| --- | --- |
| `●` / a blinking `✦` | Idle; the sparkle means work in progress. |
| `ready`, `running` | The state, or a one-off note. |
| `· deny`, `· safe`, `· full` | The shell permission, when it is not `ask`. |
| `↑18.4k ↓900` | Tokens sent and generated this session. |
| `71.2% cached` | The share of input served from the provider's cache. |
| `74 tok/s` | Generated tokens per second, over the session. |
| `ctx 12.3%` | How much of the model's window the newest request filled. |

### Choosing what is shown {#choosing-what-is-shown}

Every word in both bars belongs to a named part, shown until you switch it off. `/statusline` lists them — `ctx`,
`cache`, `model`, the `turn-*` items of the line a request ends on, `pet` and the rest — and `Enter` applies the
choice while `Esc` leaves it as it was. In `config.toml`, one line per hidden part:

```toml
[statusline]
ctx = false
```

`/statusline hide ctx speed` and `/statusline show all` do the same from the keyboard. On a narrow terminal the
figures that matter least are left out whole — `speed`, then `cache`, then `tokens` — and `ctx` stays.

## The pet {#the-pet}

A small companion can stand over the right of the conversation. It is off until you set `pet = true`
under `[statusline]`, or switch the `pet` part on in `/statusline`. `/pet` opens a panel and `/pet whale` picks one
in a step. Drag it with the mouse to move it, and its place is saved for later sessions. A terminal narrower than 80
columns does not draw it. See [`/pet`](/guide/commands#slash-commands) and
[Optional features](/guide/config#optional-features).

## Next steps

- [Keys and mouse](/guide/keys): every key and mouse action on one page.
- [Commands](/guide/commands): every slash command and the `zettcode` command line.
- [Configuration](/guide/config): every setting, including `[transcript]`, `[statusline]` and `[tools]`.
