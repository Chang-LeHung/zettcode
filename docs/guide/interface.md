# The interface

The screen is a fixed frame around a scrolling conversation. The composer
stays near the bottom while the conversation uses the remaining space; command
panels temporarily cover the lower part of it.

```
  ▐ zettcode  ~/projects/api          DeepSeek Pro · high  ← header
 ─────────────────────────────────────────────────────────
   ● Read src/api/users.py                                ← transcript
   ● Edited src/api/users.py (2 edits)                      (scrolls)
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
anything.

## The transcript

Every kind of output has its own row, in the order it happened:

- **Your message** is marked with `›` and a band of colour.
- **Thinking** is collapsed to one row. `Ctrl-T` or a click opens the newest one;
  each block can be opened on its own.
- **Tool calls** read like a log — `Read src/app.py`, `Ran pwd`, `Edited
  app.py (2 edits)`, `Searched TODO in src`. The first five lines of output stay
  visible and the rest is behind a click; nothing is ever dumped as JSON.
- **The answer** is rendered as Markdown: headings, lists, quotes, links,
  **bold**, *emphasis*, `inline code`, fenced code with syntax colours, and
  tables drawn with per-column rules that survive wide CJK characters.
- **Notices** — a copied selection, a refused command, an exported file — appear
  as muted one-liners.

`Page Up` / `Page Down` and the mouse wheel scroll. While you are scrolled up, a
`↓ back to bottom` badge appears; `Esc` or the badge returns to the newest line,
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

## Steering a running request

You do not have to wait for the model to stop. Type while it is working and
press Enter: the message joins a small `↳ steering` list above the composer and
the agent reads it at its next safe point — after the tool batch it is running.
Up to eight can be queued; the shell says so if you try more.

Steering is for direction, not for interruption: `Ctrl-C` is how you stop a
request you no longer want.

For example, while a pagination change is running, send:

> Keep the current API response format; only add the pagination fields.

This is a new instruction for the **same** task. It does not undo edits already
made. If you need the agent to stop immediately, press `Ctrl-C` instead.

## Panels

Commands that need a choice open a panel over the conversation instead of
printing options into it. `Up` / `Down` move, `Enter` accepts, `Esc` goes back
to the composer, and the transcript is untouched underneath:

- `/model` — pick the model for later requests.
- `/resume` — pick a recent session, with its title and how long ago it changed.
- `/theme` and `/effort` — pick a palette or a reasoning level.
- `/context` — what is filling the context window right now.
- **Approvals** — the panel that asks whether to run a shell command.

## Approvals

`run_shell` is the one tool that asks. The panel shows the exact command and
offers:

| Key | Meaning |
| --- | --- |
| `y` | Run it this once. |
| `a` | Run it, and allow every later command this run. |
| `p` | Run it, and remember this exact command for the session. |
| `Esc` | Refuse. The agent is told the command failed, and can react. |

For a command such as `pytest tests/test_users.py`, choose `y` if you want to
review the next command separately. Choose `p` only when you want that exact
command remembered for the current process. `a` grants a wider allowance; do
not choose it merely to dismiss the panel. Approval memory is not saved across
program restarts, and the tools run locally rather than in a ZettCode sandbox.

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

A terminal cannot hand a program the bytes of a pasted image, so **Ctrl-V** reads
the system clipboard itself — the macOS pasteboard in-process, `wl-paste` or
`xclip` on Linux — and inserts a chip where the picture belongs. PNG, JPEG, WebP
and GIF all arrive as themselves, and each one is sent as an image part in the
position its chip holds, so the model reads each picture where you put it.

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

- Drag in the transcript to select; the selection is copied when you release.
- Double-click selects a whole row; `Shift`-click extends.
- Drag anywhere else — a panel, a list, the header — to copy the text painted
  there; those surfaces never had selectable text of their own.
- `Ctrl-C` copies the current selection and clears it. With nothing selected it
  stops the running request, or clears the draft.

## The status line

The left half answers "what is happening, and how much has it cost"; the right
half keeps the two keys worth remembering (`^C stop`, `^D exit`) in view.

| Piece | Meaning |
| --- | --- |
| `●` / a blinking `✦` | The dot is idle; the blinking sparkle is work in progress. |
| `ready`, `running` | The current state — or a one-off note, such as the command being run or a copied selection. |
| `· auto` | Shell commands are approved for the rest of this run. |
| `New session` | The session's title, or `New session` before the agent names it. |
| `↑18.4k ↓900` | Tokens sent to the model, and tokens it generated, this session. |
| `71.2% cached` | The share of the input the provider served from its cache. |
| `74 tok/s` | Generated tokens per second of model time, averaged over the session. |
| `ctx 12.3%` | How much of the model's declared window the newest request filled. |

Those counters come from the provider's own numbers, accumulated after every
model call — nothing is estimated locally, and resuming a session seeds them
from what was stored on its branch.
