# ZettCode for VS Code

<p align="center">
  <img src="https://raw.githubusercontent.com/Chang-LeHung/zettcode/main/clients/vscode/media/icon.png" width="128" height="128" alt="ZettCode: the mascot riding a sword past the moon" />
</p>

<p align="center"><strong>A coding agent next to your code.</strong></p>

ZettCode reads your project, edits files and runs commands, and asks you before it does anything risky. This
extension puts the same agent as the [ZettCode terminal app](https://github.com/Chang-LeHung/zettcode) in VS Code's
side bar, so you can ask for a change and watch it happen without leaving the editor.

## What you can do

- **Ask, and watch it work.** Answers appear as they are written, with highlighted code, tables and formulas. Every
  file it reads, every edit and every command is a row; a command is written on its row (cut short when it is long),
  counts its own time while it runs, and opens to its output.
- **Jump to the code.** A file name in an answer is a link: it opens in the editor at the right line.
- **Review what changed.** After each request a card lists the files it changed with the lines added and removed.
  Open any of them as a normal VS Code diff.
- **Stay in control.** Approve or refuse a shell command, answer its questions, steer it while it works, or stop it
  with `Esc`.
- **Choose the model and how hard it thinks.** Switch the model, the reasoning effort and the shell permission from
  the box you type in. The conversation marks each change.
- **Find your way back.** A strip of small bars on the left edge marks each message you sent. Hover over it and the bars
  near the pointer swell and show the message; click one to jump there.
- **Pick up where you left off.** Conversations are saved per workspace. Reopen one, rename it, fork it, compact a long
  one to free up room, or export it as a web page.
- **Attach images and files.** Paste or drop a picture for a model that can see it; type `@` to mention a file.
- **See where your tokens go.** `/usage` shows spending by model, by session and by day, in a calendar like GitHub's.

## Getting started

1. **Nothing to install first.** The first time the chat starts, the extension installs its server into a folder of
   its own, with `uv` if you have it and your `python3` otherwise; the server ships in the same package as the agent,
   in that one environment, apart from your project. To use a server you already have (a `zettcode-server` on your
   `PATH`, or in the workspace's `.venv`), it is found first and nothing is installed. To do it by hand instead:

   ```bash
   uv tool install zettcode
   ```

2. **Open a folder** in VS Code and click the ZettCode icon in the side bar on the right, or run
   **ZettCode: Focus Chat** from the Command Palette. Prefer the left? Drag the icon there.
3. **Add a model** from the welcome card: the model name, and an API key. If you already use the ZettCode terminal app,
   the models you set up there are used as they are.
4. **Ask something**, for example *Explain this codebase* or *Fix the failing tests*.

The agent runs tools and shell commands inside your workspace, so VS Code will ask you to trust the folder first.

## Using the chat

| You want to | Do this |
| --- | --- |
| Send a message | `Enter` (`Shift+Enter` for a new line) |
| Say something while it is working | Type it and press `Enter` to queue it, or `Ctrl/Cmd+Enter` to steer the current request |
| Stop | `Esc`, or the stop button |
| Find in the conversation | `Ctrl/Cmd+F` while the chat view has the cursor (or *ZettCode: Find in Conversation*), then `Enter` / `Shift+Enter` for the next and previous match, `Esc` to close |
| Mention a file | Type `@` and pick one |
| Run a command | Type `/`: `new`, `resume`, `continue`, `compact`, `fork`, `rename`, `export`, `model`, `effort`, `permission`, `usage`, `context`, `doctor`, `btw` and more |
| Ask a quick question without adding to the conversation | `/btw your question` |
| See what fills the context window | The ring beside the send button, or `/context` |

### Shell permission

The agent can run commands in your workspace. You decide how freely:

| Level | What happens |
| --- | --- |
| `deny` | No shell commands at all. |
| `ask` | Every command waits for your approval. |
| `safe` | Every command runs in a sandbox that writes only the workspace and `/tmp`, with no network. |
| `full` | Every command runs with your own access, without asking. (`auto` is the old name.) |

## Settings

Open **Settings** and search for *ZettCode*. The ones you are most likely to want:

| Setting | Default | Meaning |
| --- | --- | --- |
| `zettcode.permission` | `ask` | The shell permission a session starts with when you have not chosen one. A level you pick in the chat is remembered for that session, and starts the next new session in the workspace. |
| `zettcode.restoreSession` | `true` | Reopen the conversation this folder had last. |
| `zettcode.autoTitle` | `true` | Let the model name an untitled conversation after its first answer. |
| `zettcode.answerTimeout` | `90` | Seconds an approval or question waits before the safe answer is used. |
| `zettcode.server.command` | `zettcode-server` | Where the server is, if it is not on your `PATH` or in the workspace's `.venv`. |
| `zettcode.server.autoInstall` | `true` | Install the server into the extension's own environment when the command cannot be found. |
| `zettcode.server.externalUrl` | empty | Connect to a server you started yourself instead of launching one. |

## Your code and your keys

The agent runs on your machine. The server it talks to listens only on your own computer and is protected by a token
made for each window. Your code goes to the model provider you configure, and nowhere else.

## Good to know

- One folder per window: in a multi-root workspace the first folder is used.
- Terminal-only features such as `/theme` and `/pet` are not part of the extension.
- Something wrong? Run **ZettCode: Show Server Log**, or [open an issue](https://github.com/Chang-LeHung/zettcode/issues).

## Learn more

- [ZettCode on GitHub](https://github.com/Chang-LeHung/zettcode)
- [Documentation](https://chang-lehung.github.io/zettcode/)
