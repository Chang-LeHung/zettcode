# Commands

Type `/` to see the menu; it filters as you type, and `Enter` or `Tab` fills in
the highlighted name. A command with an argument takes it after a space —
`/title users endpoint` — and running one never leaves the screen.

| Command | What it does |
| --- | --- |
| `/help` | List the commands and the keys. |
| `/new` | Start a fresh session. The old one stays on disk. |
| `/clear` | Clear the visible conversation, keeping this session. |
| `/resume` | Pick a recent session from a panel; `/resume <id>` opens one directly. |
| `/model` | Pick the model for later requests from a panel. |
| `/effort` | Pick how much the model reasons: `/effort high`. |
| `/btw` | Ask something that is answered here but never joins the conversation: `/btw <question>`. |
| `/theme` | Pick a palette from a panel; `/theme dark` or `/theme light` switches in one step. |
| `/context` | Show what is filling the context window right now. |
| `/compact` | Summarize the conversation now, instead of waiting for the window to fill. |
| `/title` | Name this session: `/title users endpoint`. On its own, it reports the current name. |
| `/export` | Write this session to a standalone HTML file: `/export [path]`. |
| `/quit`, `/exit` | Leave. The shell prints the command that reopens the session. |

Commands come from three places, and the menu shows them in that order: the
shell's own (above), the agent's (`/new`, `/compact`, `/export`), and any
[plugin](/guide/plugins) that registered one. A plugin cannot take a name that
is already used, so `/model` always does what this page says.

## Panels, not arguments

`/model`, `/resume`, `/theme`, and `/effort` open a picker. `Up` / `Down` move,
`Enter` accepts, and `Esc` goes back without changing anything. `/context`
opens a report rather than a choice: read it, then press `Esc` to close it.
The conversation underneath stays visible.

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

`@` pulls a resource into a message. What it expands to is decided by the
provider that owns it; today that is your [skills](/guide/skills-and-mcp):

> Review @code-review the diff I just made

The menu lists the skills it found, with the description from each `SKILL.md`.
The draft you typed is what gets stored and shown, so reopening the session
later gives you `@code-review` back rather than the expanded text. The model is
told to load the skill — it sees the name and reads the body when it needs it,
which is what keeps a large skill catalog out of every request.

Resources work anywhere in a message, more than one per message, and each is
removed by a single **Backspace** when the cursor is right after the chip.

For example, with `code-review` and `test-plan` skills installed:

```text
Review @code-review the current diff, then use @test-plan to suggest missing tests.
```

Both references keep their position in the sentence; the text around them is
preserved. They tell the model which skill to use, not to paste its entire body
into every request. See [Skills and MCP](/guide/skills-and-mcp) for installation.
