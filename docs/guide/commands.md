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

`/model`, `/resume`, `/theme`, `/effort` and `/context` open a panel because the
answer is one choice out of a list. `Up` / `Down` move, `Enter` accepts, `Esc`
goes back without changing anything — and the conversation underneath is not
touched, so you can open and dismiss them in the middle of reading an answer.

Switching the model, the theme, or the effort re-lays out the screen: the header
and the status line read from the same state the panels write to, so they show
the new value before you send the next message.

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
