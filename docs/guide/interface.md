# The interface

The screen is a fixed frame around a scrolling conversation. The composer
stays near the bottom while the conversation uses the remaining space; command
panels temporarily cover the lower part of it.

```
  ▐ zettcode  ~/projects/api          DeepSeek Pro · high  ← header
 ─────────────────────────────────────────────────────────
 ● Read src/api/users.py                                ← transcript
 ● Edited src/api/users.py (2 edits) +24 -6             (scrolls)
 ● Ran pytest tests/test_users.py
 ─────────────────────────────────────────────────────────
   ▸ panels open here: model, context, sessions           ← panel
 ─────────────────────────────────────────────────────────
   /model  /resume  /context                              ← completions
 › add a limit/offset window to GET /users                ← composer
   ● ready  New session  ↑18.4k ↓900 · ctx 12.3%          ← status line
```

## The header

The left side names the application and the workspace, shortened to the last
useful part of the path. The right side names the model and the reasoning effort
that the **next** request will use, so a switch is visible before you send
anything. Changing the effort plays an animation in that corner for a few seconds: a hairline gauge with one cell per level fills from the level you left to the level you chose, and a soft glow travels over it and then over the word. Colour is a position on the scale, not a state: the cheap end is your theme's accent and the dear end its error colour, with a smooth blend between, so `ultra` is the one that is red. The gauge fades in and out rather than cutting, and gives the corner back when it is done. It does not appear while a request runs (the waiting row is moving then) or under reduced motion, where the level still changes and the transcript still says so.

## Terminal tabs

ZettCode sets its window title to `◈ zettcode · New session`, then replaces
`New session` with the active session's title. Naming a session with `/title`,
resuming another one, or starting a new one updates the title automatically.
On macOS and Linux, the foreground process is also named `zettcode` rather
than `python3`, including iTerm2's job label.

VS Code's default terminal tab shows the **process**, not the title a program
sets. To show the ZettCode marker and session name, open **Preferences: Open
User Settings (JSON)** and add these keys to the existing object:

```json
{
  "terminal.integrated.tabs.title": "${sequence}",
  "terminal.integrated.tabs.description": "${process}"
}
```

This applies to all integrated terminals. A manually renamed tab takes
precedence; reset its name through the terminal's **Rename** action if needed.
ZettCode does not modify your editor settings. The `◈` is a text brand marker:
VS Code's separate tab icon cannot be replaced with our pixel SVG by terminal
output; a custom image icon requires an editor extension.

## The transcript

Every kind of output has its own row, in the order it happened:

- **Your message** is marked with `›` and a band of colour.
- **Thinking** is collapsed to one row. `Ctrl-T` or a click opens the newest one;
  each block can be opened on its own.
- **Tool calls** read like a log — `Read src/app.py`, `Ran pwd`, `Edited
  app.py (2 edits) +24 -6`, `Searched TODO in src`. An edit's added lines are
  painted green and its removed ones red, whether the call is still running or
  done. The first five lines of output stay visible and the rest is behind a
  click; nothing is ever dumped as JSON.
- **The answer** is rendered as Markdown: headings, lists, quotes, links,
  **bold**, *emphasis*, `inline code`, fenced code with syntax colours, and
  tables drawn with per-column rules that survive wide CJK characters. An HTML
  entity is drawn as the character it names, so `&nbsp;` indents a line and
  `&lt;` writes an angle bracket.
- **The running request** is one row pinned to the bottom of the transcript:
  `✦ Processing (8s · ^C/Esc to interrupt)`. Reasoning, tool calls, and the answer all appear
  above it, and when the request ends — answered, failed, or stopped — that same
  row becomes `Processed for 12s · 22:53`. It is the only row that moves: its
  marker and the highlight crossing the word pulse together — a second of
  movement, then a second at rest — while the clock and the stop key stand
  beside it in parentheses, in the quiet ink a notice uses, counting whole
  seconds and minutes.
- **Notices** — a copied selection, a refused command, an exported file — appear
  as muted one-liners.

`Page Up` / `Page Down` and the mouse wheel scroll. The wheel is one line a notch when you nudge it, and
gathers speed the longer you keep turning (up to ten lines a notch); a pause, or turning the other way,
starts again at one line. While you are scrolled up, a
`↓ back to bottom` badge appears; `Esc` or the badge returns to the newest line.
While a request is running, `Esc` stops it, exactly as `Ctrl-C` does: the key that
means "get me out of this" should not depend on remembering which of the two the
shell reserved for it.
and the view starts following the tail again.

## The composer

The `›` prompt is where you type. It grows as the draft grows, up to a share of
the screen.

- **Enter** sends. **Alt-Enter** or **Shift-Enter** adds a newline.
- **`/`** opens the command menu, **`@`** opens the resource menu (your skills).
  `Up` / `Down` choose, `Enter` or `Tab` fills in, `Esc` closes.
- A long paste — over 512 characters, or taller than the composer grows — is
  replaced by a `[pasted text 6012 chars]` chip. **Backspace** removes the whole
  chip; the text is restored when the draft is sent.
- **Ctrl-V** attaches an image from the desktop clipboard as an `[image #N]`
  chip. Text and images keep the order you wrote them in. See
  [Pictures and pastes](#pictures-and-pastes).
- A `/command` or an `@resource` is coloured only when it is real. The command must exist and be
  the first word of the draft (that is the only place a command runs); the resource must be one
  that exists. Anything else — `/usr/bin` in a sentence, `@someone` — is just text, and
  **Backspace** deletes it one character at a time. A real one is deleted whole.

## Typing while a request runs

You do not have to wait for the model to stop. Type while it is working and press
Enter, and ZettCode asks what the message is — the text alone cannot say:

```text
You sent a message while ZettCode is working. What should it do?

› then open a pull request

▸ 1. Follow up  send it after this request finishes (f)
  2. Steer      hand it to the agent now; it replaces the rest of the current task (s)

enter choose · f follow up · s steer · esc keep editing the draft
```

`f` and `s` pick a row directly, `Enter` takes the highlighted one (**Follow up**, the
choice that cannot interrupt anything), and `Esc` closes the question and leaves your
draft in the composer, so pressing Enter too early costs nothing. When only one answer
is possible — a command such as `/compact` is running, which cannot be steered — nothing
is asked and the message waits as a follow-up.

### Steer: change what it is doing

A steering message joins a small `↳ steer` list above the composer. The agent reads it at
its next safe point — after the tool batch it is running — and drops the rest of the
current task for it. Up to eight can be queued. It is a new instruction for the **same**
task and does not undo edits already made.

Both lists show one line per message. A message too long for the line is cut and ends in `…`, and
so does one with more lines after the first (a pasted block shows its first line and `…`); the whole
text is still what is sent.

By the time you see it in the list the agent already has it, and the agent offers no way
to take a message back, so **a steering message cannot be edited, removed or reordered**.
If you are not sure you want it, send it as a follow-up: that one stays in your hands.

### Follow up: do this next

A follow-up waits in its own `• follow-up` list, directly above the composer, and goes out
as a message of its own when the conversation ends well — one at a time, in the order shown,
each starting when the one before it is done. Up to eight can wait. Steering messages and
follow-ups can wait together: the steering list sits above, and every key below works on
the follow-ups.

Because a follow-up is still in your hands, you can change it. `Option` is the key marked
`⌥` on a Mac (`Alt` on other keyboards, and that is what the hints say there):

| Key | What it does |
| --- | --- |
| <kbd>Option</kbd>+<kbd>Up</kbd> / <kbd>Option</kbd>+<kbd>Down</kbd> | With nothing highlighted: walk into the list. `Option-Up` lands on the row nearest the composer and `Option-Down` on the first. **With a message highlighted: move that message** one place earlier or later; the highlight goes with it. |
| <kbd>Up</kbd> / <kbd>Down</kbd> | With a message highlighted: move the highlight. `Down` past the last row goes back to the composer. Without a highlight these are the composer's, as always. |
| <kbd>Enter</kbd> | Take the highlighted message out of the list and into the composer to change it. Sending it again puts it back **in the slot it left**, not at the end. |
| <kbd>Delete</kbd> / <kbd>Backspace</kbd> | Remove the highlighted message; it will not be sent. The line above the composer names what was removed. |
| <kbd>Esc</kbd> | Let go of the highlight. The request keeps running; a second `Esc` stops it as usual. |

The list names these keys itself — the row under it reads `option+↑/↓ to select`, and once a
message is highlighted it lists the rest — so there is nothing to memorise. Typing anything
also lets go of the highlight, and `Enter` will not overwrite a draft you have already
started: finish or clear it (`Ctrl-C`) first.

::: tip In VS Code's terminal
VS Code rewrites `Option-↑` and `Option-↓` before the terminal sees them — it sends the keys
`Ctrl-↑` and `Ctrl-↓` instead — so ZettCode treats the two spellings as the same key, and the
list works the same there as in iTerm2. (Only while a follow-up list exists: with nothing queued
the keys are left alone.)
:::

::: tip If your terminal swallows Option-Up
Some terminals use `Option-Up` themselves. ZettCode reads the usual spellings, including
the "Option sends Esc+" setting of macOS Terminal and iTerm2. If yours still keeps the key,
turn on "Use Option as Meta" (Terminal) or set the left Option key to "Esc+" (iTerm2).
:::

### When the conversation does not end well

`Esc` (or `Ctrl-C`) stops a request you no longer want, and that is *all* it does. The follow-ups
are your own list: stopping does not send them, and it does not take them away either. They stay
in the list, which now reads `held until your next reply completes`, and the transcript says how
many are held. Say what you meant to say instead — and when **that** reply completes, the held
follow-ups go out behind it, in order. A request that failed does the same.

So a follow-up is only ever attached to a conversation that finished smoothly. A side question
(`/btw`) finishing in between is not a reply and does not release them. The list belongs to its
conversation: `/new`, `/resume` and `/fork` hand it back as text in the composer rather than send
it into a conversation it was not written for.

One thing is different. A *steering* message the agent never got to read was written to redirect
the request that just ended, so it goes back into the composer, after whatever you had typed there.

For example, while a pagination change is running, send this as a **steer**:

> Keep the current API response format; only add the pagination fields.

and this as a **follow-up**:

> Then add a test for the last page.

If you need the agent to stop immediately, press `Esc` instead.

## Panels

Commands that need a choice open a panel over the conversation instead of
printing options into it. `Up` / `Down` move, `Enter` accepts, `Esc` goes back
to the composer, and the transcript is untouched underneath:

- `/model` — pick the model for later requests.
- `/resume` — pick a recent session, with its title and how long ago it changed.
- `/theme`, `/effort`, and `/permission` — pick a palette, a reasoning level, or how much of the shell may run without asking.
- `/context` — what is filling the context window right now.
- **Approvals** — the panel that asks whether to run a shell command.

## Approvals

`bash` is the one tool that asks. How often it asks is a setting with four
levels, which `/permission` changes at any time between requests:

| Level | What happens to a shell command |
| --- | --- |
| `deny` | None runs. The model is told the commands are off, and carries on with the file tools. |
| `ask` | Each one waits for your answer. This is where every run starts. |
| `safe` | Commands that only read run; anything else asks. |
| `auto` | Every command runs without asking. |

The level covers the shell only. File edits and MCP tools are not behind a
prompt in ZettCode, so `deny` is not a read-only mode for your workspace. It is
not saved across restarts either: the next run starts at `ask` again.

At `ask` and `safe` the panel shows the exact command, the level it is asking
at, and offers:

| Key | Meaning |
| --- | --- |
| `y` | Run it this once. |
| `p` | Run it, and remember this exact command for the session. |
| `s` | Run it, and stop asking for read-only commands (switches to `safe`). Not offered at `safe`, where it would change nothing. |
| `a` | Run it, and stop asking for any command this run (switches to `auto`). |
| `Esc` | Refuse. The agent is told the command failed, and can react. |

`s` and `a` are the same change `/permission safe` and `/permission auto` make:
the level, the line in the conversation, and the status line all agree whichever
door you used. Mid-request they are the way to change it, because a typed
command waits for the request to end.

For a command such as `pytest tests/test_users.py`, choose `y` if you want to
review the next command separately. Choose `p` only when you want that exact
command remembered for the current process. `a` grants a wider allowance; do
not choose it merely to dismiss the panel. Approval memory is not saved across
program restarts, and the tools run locally rather than in a ZettCode sandbox.

### What `safe` runs

`safe` runs a command without asking only when it recognises every part of it
as unable to change anything: a short list of reading programs (`ls`, `cat`,
`grep`, `head`, `wc`, `diff`, …), `rg` and `find` without the options that run
something or write a file, and `git status`, `log`, `diff`, `show`, and other
read-only subcommands, optionally joined with `|`. Anything it does not know
asks, including `;`, `&&`, redirects, `$(…)`, and every program not on the list.

Two things it does not promise. A read-only command can still print a secret
that sits in the workspace, so `safe` means *nothing will change*, not *nothing
will be seen*. And `git` reads its own configuration, which can name programs to
run: a repository whose config does is not trusted, and your global git
configuration is not checked. If a workspace may hold such files, use `ask`.

## When the model asks you a question

Some decisions are not the model's to guess — which format, which of two files,
whether to keep going. It can ask, and the turn waits for you. The panel is only
as tall as the question needs, and it says which kind of answer it wants:

```
  Which format should I write the summary in?
       1. Markdown
   ▸ ✓ 2. Plain text
  › up/down choose, enter sends · or type an answer · esc cancels
```

- `Up` / `Down` move through the choices, and `Enter` acts on the highlighted
  row. A one-answer question sends it straight away, the way `/model` and
  `/resume` work; the `✓` marks the row `Enter` would pick.
- A question that allows several choices ticks instead, and grows a `send` row
  to finish with:

  ```
     ✓ 1. Summary
     ✓ 2. Diff
       3. Tests
     ➤ send (2 chosen)
  ```

  `Enter` on a ticked row unticks it, and `➤ send` answers with everything
  ticked.
- Under the choices sits the answer line, with no label of its own: it shows the
  keys until you type, and what you type from then on. So you can pick a choice
  or answer in your own words — and a question with no choices is nothing but
  that line. A multiple-choice answer is its ticks *plus* whatever you type
  beside them, in that order however you wrote them, and a word that is already
  ticked is not repeated.
- Typing takes the panel over: the choices fold away, and the `▸` marker and the
  band move to the answer line, because that is where the cursor is. `Up`/`Down`
  bring the choices back with your text still in the line — and on a one-answer
  question no row is marked then, since the answer is what you wrote.
- A chosen row keeps a raised background and an accent-coloured `✓`, so what you
  have picked is visible at a glance; the row your cursor is on is banded more
  strongly still.
- On a one-answer question, choosing after typing asks first: the note
  `one answer only` appears beside the question, and a second `Enter` replaces
  what you wrote.
- The header counts the questions when the model asked several in one turn, and
  each is asked in turn: answer the one on screen, and the next appears.
- `Esc`, or `Ctrl-C`, declines the question. The model is told the question was
  cancelled and carries on rather than waiting for an answer that is not coming.

The panel sits over the conversation like the approval prompt, and the run stays
suspended until it is answered. `[ask_user] enabled = false` takes the tool away
altogether, and then the model answers from what it already knows instead of
asking.

## Side questions

`/btw <question>` asks something the model should answer from what it already
knows — "what does this function do?", "which of these two is faster?" — and the
answer appears here like any other turn, marked `btw ›` on a tinted surface of
its own, so the aside stands out from the turns around it (the
[`surface_side`](/guide/config#colours) role, if you want to recolour it).

What makes it *side* is what is not kept:

- The exchange is written into the session file, but never replayed into the
  model's context, so later turns do not know it happened.
- It *is* replayed into the transcript when the session is resumed, marked
  `btw ›` like it was when you asked it — you saw that answer, so it comes back —
  but it is not in an [export](/guide/sessions#exporting).
- Only the reading tools are offered. An edit made while asking would be
  invisible to the conversation that continues afterwards, so the model would
  carry on with a false picture of the workspace.

Ask one while a turn is running and it waits for that turn instead of being
refused; its tokens still count in the status line, and it does not trigger
automatic compaction or naming.

For example, during a task to update an API endpoint:

```text
/btw What is the difference between offset and cursor pagination?
```

Use a normal message instead if that answer should guide the continuing task.
If a normal request is still running, the side question waits for it to finish;
it is not a second simultaneous writer to the workspace.

## Pictures and pastes

A picture can be sent like any other message, including **while a request is running**: as a
follow-up it goes out with its picture in the place its chip holds, and as steering it reaches the
agent as one message with the picture in it. Taking a message back out to edit it, or getting back
one the agent never read, restores its pictures as chips.

A terminal cannot hand a program the bytes of a pasted image, so **Ctrl-V** reads
the system clipboard itself — the macOS pasteboard in-process, `wl-paste` or
`xclip` on Linux — and inserts a chip where the picture belongs. PNG, JPEG, WebP
and GIF all arrive as themselves, and each one is sent as an image part in the
position its chip holds, so the model reads each picture where you put it.

This reads the clipboard of the machine ZettCode runs on, so **over `ssh` it cannot see an image
you copied on your own machine**: a terminal can carry text across the connection (that is how
[copying works](#copying-over-ssh)) but has no way to carry a picture. Over `ssh` Ctrl-V therefore
does not look at all; it says why and what to do instead — put the file on the server and refer to
it by path, or set `ZETTCODE_CLIPBOARD=system` if a display forwarded over `ssh` makes the
server's clipboard the right one.

On a machine with no clipboard tool (a bare Linux server has neither `wl-paste` nor `xclip`),
Ctrl-V says `no image on the clipboard`. A tool that is missing, cannot be run, or does not
answer within three seconds never ends the session.

Two things follow from the chip being text:

- a restored session shows `[image #3]` where the picture was, and does not
  re-send it;
- a model configured with `multimodal = false` refuses the attach with a notice
  instead of failing later, and is never offered the `view_image` tool.

Every other paste still goes through the terminal's own paste key
(`Cmd-V` on macOS, `Ctrl-Shift-V` or `Alt-V` elsewhere). A terminal that pastes
an image *as text* is recognised too — VS Code's integrated terminal turns a
clipboard image into base64 — so a `data:image/…;base64,` URI, or base64 that
decodes to a known image, becomes the same chip instead of a wall of characters.

## Selecting and copying

- Drag in the transcript to select; the selection is copied when you release, and
  the row above the composer says so for a moment — a small highlighted pill, `✓ copied 42
  chars to clipboard` — before the next thing typed takes that row back. The pill is the
  only thing on screen that shows a copy happened, which is why it has a fill of its own;
  it hugs its words rather than running across the screen.
- Double-click selects a whole row; `Shift`-click extends.
- Drag anywhere else — a panel, a list, the header — to copy the text painted
  there; those surfaces never had selectable text of their own.
- `Ctrl-C` copies the current selection and clears it. With nothing selected it
  stops the running request, or clears the draft.

### Copying over `ssh`

When ZettCode runs on a server you reach with `ssh`, the clipboard you will paste from is
the one on **your** machine, not the server's. A clipboard tool on the server can only reach
the server's, so ZettCode does not use it there: it asks your terminal to do the copy
(an [OSC 52](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html) escape sequence), and
that travels over the connection like everything else it prints. The pill then reads

```text
✓ sent 42 chars to your terminal's clipboard
```

and says "sent" rather than "copied" on purpose: the program is on another machine and cannot
see whether your terminal accepted it. Several terminals ask first or refuse by default.

| Terminal | What it needs |
| --- | --- |
| iTerm2 | Turn on the setting that lets applications in the terminal access the clipboard — in Settings → General → Selection, "Applications in terminal may access clipboard" |
| kitty, Alacritty, Ghostty | Nothing: they allow a program to *write* the clipboard by default |
| WezTerm, Windows Terminal | Support it |
| tmux | `set -g set-clipboard on` — tmux's default, `external`, does not accept it from programs inside — or `set -g allow-passthrough on`, in `~/.tmux.conf` |

A terminal that does not support OSC 52 ignores it, and the text goes nowhere. Then copy with
that terminal's own selection, which you get by holding its modifier (<kbd>Shift</kbd> or
<kbd>Option</kbd>) while dragging.

ZettCode decides where to copy from the environment: `SSH_CONNECTION`, `SSH_CLIENT` or `SSH_TTY`
means it is on the far side of a connection. Where that guess is wrong — `sudo` drops the
variables, or you forwarded an X display and the server's clipboard is the one you want —
say so with `ZETTCODE_CLIPBOARD=terminal` or `ZETTCODE_CLIPBOARD=system`.

## The status line

The left half answers "what is happening, and how much has it cost"; the right
half keeps the two keys worth remembering (`^C/Esc to interrupt`, `^D exit`) in view.

| Piece | Meaning |
| --- | --- |
| `●` / a blinking `✦` | The dot is idle; the blinking sparkle is work in progress. |
| `ready`, `running` | The current state — or a one-off note, such as the command being run or a copied selection. |
| `· deny`, `· safe`, `· auto` | The shell permission, when it is not the default `ask`. |
| `New session` | The session's title, or `New session` before the agent names it. |
| `↑18.4k ↓900` | Tokens sent to the model, and tokens it generated, this session. |
| `71.2% cached` | The share of the input the provider served from its cache. |
| `74 tok/s` | Generated tokens per second of model time, averaged over the session. |
| `ctx 12.3%` | How much of the model's declared window the newest request filled. |

Those counters come from the provider's own numbers, accumulated after every
model call — nothing is estimated locally, and resuming a session seeds them
from what was stored on its branch.
