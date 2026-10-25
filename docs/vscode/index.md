---
title: ZettCode in VS Code
---

# ZettCode in VS Code

The extension puts the same agent the terminal app runs into the editor's secondary side bar: ask for a change, watch
it work, review the files it touched, and keep control of every shell command. It speaks to `zettcode-server` over
HTTP on your own machine, and the server does the work.

- **Ask and watch.** Answers stream in with coloured code, tables, formulas and diagrams. Every file read, edit and
  command is a row you can open to see what happened; a failed one opens with the reason.
- **Jump to the code.** A path in an answer is a link: it opens the file at the line.
- **Review what changed.** Each request ends with a card of the files it changed, with lines added and removed, and a
  normal VS Code diff behind each one.
- **Stay in control.** Shell commands ask before they run, questions wait for an answer, and you can steer a request
  while it is going.
- **Reopen, and the pictures are there.** A stored conversation comes back whole, images included.

## Install

The extension is on the [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode),
under the publisher **zettcode**.

1. Open the extensions view (`Ctrl/Cmd+Shift+X`), search for **ZettCode**, and install it. Or install the `.vsix`:

   ```bash
   code --install-extension zettcode-0.1.7.vsix
   ```

   The [marketplace page](https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode) says which version is
   the newest; a `.vsix` from the [releases page](https://github.com/Chang-LeHung/zettcode/releases) can be newer still.

2. Open a folder. The extension serves one folder per window; in a multi-root workspace the first folder is used.
3. Click the ZettCode icon in the secondary side bar on the right, or run **ZettCode: Focus Chat**. Prefer the left
   side? Drag the icon there.
4. **Nothing else to install.** The first time the chat starts, the extension looks for a `zettcode-server` on your
   `PATH` or in the folder's `.venv`; if there is none, it installs one into an environment of its own
   (`globalStorage/server/venv`), with `uv` or your `python3`. It is the same package as the terminal's agent, in an
   environment of its own, apart from your project. To do it by hand instead:

   ```bash
   uv tool install zettcode
   ```

   Turn that off with `zettcode.server.autoInstall` if you would rather it never did.

5. **Add a model** from the welcome card: the model id, and optionally an API key. Models you set up in the terminal
   app are used as they are, because the configuration file is the same one.
6. Ask something, for example *Explain this codebase*.

VS Code asks you to trust the folder first: the agent runs commands and edits files in it.

## Asking for work

| You want to | Do this |
| --- | --- |
| Send | `Enter`; `Shift+Enter` for another line |
| Say something while it works | `Enter` queues a follow-up; `Ctrl/Cmd+Enter` steers the request that is going |
| Stop | `Esc`, or the stop button |
| Find in the conversation | `Ctrl/Cmd+F` while the chat has the cursor; `Enter` / `Shift+Enter` for the next and previous match, `Esc` to close |
| Mention a file | Type `@` and pick one |
| Attach a picture | Paste it, drop it on the view, or press the paperclip |
| Attach any other file | Press the paperclip and pick it: a PDF or an archive goes into the message as its **path**, which the agent opens with its own tools |
| Paste a copied file | Copy a file in the explorer or the file manager and paste it: its full **path** goes into the box, not its bare name. A page is given a file's name and contents but no path, so the extension asks the system's clipboard for the real one (macOS, Windows and Linux; a file of any size, from anywhere, such as a PDF on the Desktop). Failing that it uses the workspace file with the very same contents, else keeps a copy of the contents in its own storage; a file over 10 MB can only be found by name. In a remote window (SSH, WSL, a container) the clipboard is not the one you copied on, so the contents are used |
| Run a command | Type `/`: `new`, `resume`, `continue`, `compact`, `fork`, `rename`, `export`, `model`, `effort`, `permission`, `harness`, `usage`, `context`, `doctor`, `btw` |
| Ask without adding to the conversation | `/btw your question` |

The pictures you attach are sent to a model that can see images, and are kept with the conversation, so reopening the
session shows them again instead of only counting them.

### Moving around the conversation

- **The rail** on the left edge marks each message you sent. Point at it and the bars near the pointer swell and show
  their message; press one to go there. When there are so many that the bars would touch, one bar stands for ten
  messages: press it and the ten are listed beside the rail, and you pick one.
- **Show earlier requests** loads older messages a page at a time, keeping your place.
- **Compaction** appears as a row where it happened; press it to read the summary it left.

### Several sessions at once

A request keeps running when you look at another session. Open the session list and start a new session, or open an
older one, while the agent works: the work goes on where it is, and a small spinner (with the word *running*) marks that
session in the list. Open it again and its conversation is there as it got to, still streaming if it is not done. Each
session has its own approvals, questions and steering, so a command waiting for you in one session does not appear in
another; the extension says when a session in the background is waiting for an answer or has finished.

### Messages between sessions

Write `@name` at the start of a message to send it to another ZettCode session (a terminal, or another editor window)
instead of asking this chat's model: the message shows as *to @name* with what you said. What another session sends
to this one arrives as its own request, marked *from @name*, and the agent answers it here; if it should answer the
sender too, it sends a message back. A message the agent sends shows its text above the delivery line.

### Approvals, questions, steering

The shell permission decides what the agent may run on its own:

| Level | What happens |
| --- | --- |
| `deny` | No shell commands at all. |
| `ask` | Every command waits for your approval. |
| `safe` | Every command runs in a sandbox that writes only the workspace and `/tmp`, with no network. |
| `full` | Every command runs with your own access, without asking. (`auto` is the old name.) |

The level chosen in the chat is remembered for the next new session in the workspace. An approval waits
`zettcode.answerTimeout` seconds, then the safe answer is used. A question waits until you answer it; it has no timeout.

## Pictures, diagrams and code

Anything too small for the column opens in one lightbox over the conversation: a picture, a Mermaid diagram, a table
or a code block. What it is decides how much it can be enlarged.

| What | What happens |
| --- | --- |
| A picture you sent | Press it (in the message, or in the strip under the box) to open it over the conversation, fitted to the window |
| A Mermaid diagram | A ```` ```mermaid ```` fence is drawn, not shown as code. Press it, or the expand button in its header, to open it larger |
| A table | The expand button in its corner opens it at full width |
| A code block | The expand button in its header opens it at full width, without the column's narrow limit |

In the lightbox, the mouse wheel zooms at the pointer, `+` and `−` zoom, `0` fits the content again, dragging
moves it, and a double click switches between fitted and real size. `Esc` closes it, and does not reach the message
box, so it never stops a request running behind it. A diagram that cannot be drawn stays as its code with the first
line of the reason, and the source of any diagram is one press away.

## Models, effort and permission

The chips under the message box pick the model, the reasoning effort and the shell permission; the same three are in
the Command Palette as **Select Model**, **Select Reasoning Effort** and **Select Shell Permission**. **Add Model**
writes a new entry to the same `config.toml` the terminal app uses.

The add-model form takes the same keys as the terminal's `/config`. Only the **model id** is required; the **API key**
can be left empty for a local server (Ollama, LM Studio, vLLM), or to use `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`.
**API** is a choice of **Chat completions** (written as `chat = true`), the **Responses API** or the **Anthropic
Messages API**, one of the three. **Temperature** is a number from 0 to 2 (0 to 1 for Anthropic), and left empty none is
sent. **Web search** lets the provider search the web for the model, and a **tool name** overrides what its API sends
by default (`web_search`, `web_search_20260318` for Anthropic, `web_search_20250305` for DeepSeek); DeepSeek is accepted
only over the Anthropic API, and the form says so before anything is sent. **Edit Model** changes the same things on a
model that is already there: choosing another API takes the old
flag out of the file instead of leaving `anthropic = false` behind, and clearing the temperature or turning search off
removes the key.

## Spending

**ZettCode: Usage** opens a page with the terminal's three tabs — models, sessions and calendar — for **this
workspace only**: each folder keeps its own ledger, so another project's spending is not in it. The page says which
folder it is for, under its title.

## Settings

Search for *ZettCode* in Settings:

| Setting | Default | Meaning |
| --- | --- | --- |
| `zettcode.permission` | `ask` | The shell permission a session starts with when you have not chosen one: `deny`, `ask`, `safe` (a sandbox) or `full` |
| `zettcode.harness` | `false` | Start with the tool harness on: the model may write small Python tools of its own and run them, outside the shell permission. `/harness on` or `/harness off` switches it for a session |
| `zettcode.restoreSession` | `true` | Reopen the conversation this folder had last |
| `zettcode.autoTitle` | `true` | Let the model name an untitled conversation after its first answer |
| `zettcode.answerTimeout` | `90` | Seconds an approval waits |
| `zettcode.historyLimit` | `50` | How many stored conversations **Recent Sessions** lists |
| `zettcode.server.command` | `zettcode-server` | Where the server is, if not on your `PATH` or in the folder's `.venv` |
| `zettcode.server.args` | `[]` | Extra arguments for it |
| `zettcode.server.port` | `0` | A fixed port; `0` picks a free one |
| `zettcode.server.autoStart` | `true` | Start the server with the chat |
| `zettcode.server.autoInstall` | `true` | Install the server into the extension's own environment when it cannot be found |
| `zettcode.server.externalUrl` | empty | Use a server you started yourself instead of launching one |
| `zettcode.server.externalToken` | empty | Its token, when it needs one |
| `zettcode.server.useToken` | `true` | Protect the server the extension starts with a token per window |

Skills, MCP servers and `AGENTS.md` work in the editor exactly as they do in the terminal: see
[Skills & MCP](/guide/skills-and-mcp) and [Project instructions](/guide/instructions). `<workspace>/.agents/skills`,
`~/.agents/skills` and the matching `mcp.json` files are read too, so a skill written for another coding agent is
found without copying it.

## When something goes wrong

| What you see | What to do |
| --- | --- |
| The chat says the server is not running | **ZettCode: Show Server Log** has the reason; **ZettCode: Restart Server** after fixing it |
| No model | **ZettCode: Add Model**, or copy the `[[models]]` entry from `~/.zettcode/config.toml` |
| A command was refused | The shell permission is `deny`; pick `ask`, `safe` or `full` under the message box |
| A diagram says it could not be drawn | The fence is not valid Mermaid; the source is in the block, and the reason is on its first line |

## Only in the terminal

`/theme`, `/pet` and the rest of the full-screen interface belong to the terminal app. The editor has its own theme,
and its own shortcuts.
