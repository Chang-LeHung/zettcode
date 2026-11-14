# The JIT harness

With the just-in-time harness on, the model can write a small Python tool of its own, load it and call it in the same
turn, instead of working only with the tools it shipped with. It is on by default.

## What happens

1. The model creates a repository with the `repo_create` tool and writes a tool into it with its file tools. The tool is
   plain Python under `~/.zettcode/harness/<workspace>/<session id>/`.
2. It loads the repository with `repo_load`. The code is imported in a **child process** of its own, so a crash or a hang
   stays out of your window.
3. It calls the tool like any other. Every step is a row in the conversation that you can expand and read.

A session keeps one repository. If it already has one, the model is told to reuse it rather than create a second.

## Turn it on or off

The harness is on by default. Every run starts with its four tools, and the model may write a tool of its own whenever
it decides one is worth keeping. To change that:

| How | Effect |
| --- | --- |
| `[harness] jit = false` | Starts every run with the harness off. |
| `/plugins` | Switches it on or off for the next start. |
| `/harness gen [description]` | Turns the harness on for this run and asks the model, as one turn of this conversation, to build one small tool for this workspace and report it. |
| `/harness reset` | Turns it off for this run. Later requests have none of its tools. Nothing is deleted: what the session wrote stays in the harness folder, and the command names the path. |

```toml
# ~/.zettcode/config.toml
[harness]
jit = false
```

```text
/harness gen list the TODO comments in this repository, grouped by file
```

Anything after `gen` is your own description of what you want. The model is told to treat it as a requirement that
outranks the command's own advice, so a "do not touch X" in it is obeyed and the report says whether it was met. A
description longer than 4000 characters is cut, and the message says where. `gen` turns the harness on for every session
in the window. It is not taken while a request is running.

The `gen` brief asks for a small, specific tool, one or two tools using the standard library where that is enough,
that the model runs at least once on your workspace before it says it works. It also tells the model to keep its writes in
the harness folder and not to edit your project's files. That is an instruction to the model, not a sandbox.

## The `/harness` panel

`/harness` opens a read-only, full-screen table of every repository under `~/.zettcode/harness`, including other
workspaces' sessions. `Tab` switches between **Harnesses**, **Tools** and **Files**. It reads the declaration files
without importing anything, so it shows what a repository says it defines, not what its code does.

`Enter` on a row borrows that harness for the current conversation: `gen` and `repo_create` then write into the other
session's folder, until the window closes or you choose a row of your own session.

## Where the code runs

The child process is the boundary between the model's code and your session. What limits the code inside it depends on
your shell level:

| Shell level | The harness code runs |
| --- | --- |
| `full` | With your own access. |
| `safe` or `ask` | Inside the boundary `safe` uses. The two share it, so moving between them costs nothing. |
| `deny` | Still runs the Python the model writes, inside the `safe` boundary, because it is not a shell command. |

On a machine with no sandbox (Windows, or Linux without a working `bwrap`), the harness says so once per session, so
the code the model writes is never unbounded without a word.

Changing the level to or from `full` changes the boundary. The child is closed, the next request starts a new one, and
the model's own tools are gone until it runs `repo_load` again.

## MANIFEST and BAN_TOOLS

A repository declares itself in a `MANIFEST` beside its `__init__.py`: a name, a version, a description, and optionally
the `tools` it declares. A repository is loadable only with one. Declaring the tools in `MANIFEST` is what makes
`repo_load` check the model's work.

A `BAN_TOOLS` file beside it names tools the repository may not define.

## How tools have done

`profile_tools` shows the model how its tools have done: for each one the calls, the success rate, how long a call
takes, how much it hands back, and its most recent distinct errors. It works for every tool the session has run, the
model's own, the application's and an MCP server's. A tool that was never called shows zeros, which is also an answer.
Without names it gives an overview of the model's own tools and of every tool called so far, most called first; with
up to ten names it gives those tools, each with its last three errors.

The numbers are read from the session's stored conversation, not counted while a call runs. That is why they survive a
restart and why nothing is wrapped around a call to measure it. A session with no stored conversation yet answers with
zeros and says so.

A conversation can be hundreds of megabytes, so it is never read whole. Only its last 32 MB is read, on a worker thread
so the window does not stop, and a single result longer than 2 MB is left out and counted. The answer's `window` field
says what was read: `the whole of this session`, or `the last 32.0 MB of 128.1 MB of this session; older calls are not
counted`. Reading a conversation of that size takes a fraction of a second.

## What it cannot do

- **It is not a sandbox at `full`.** At that level the code has your access, as the commands the model runs do.
- **It does not make `/harness gen` safe by itself.** Keeping writes in the harness folder is something the model is asked to
  do.
- **`reset` does not delete** what the session wrote. It only stops later requests from having the harness's tools.
- **It cannot reach another session's tools** unless you borrow that session's harness in the panel.
- **A session open in another ZettCode process** holds the session: there, `gen` answers `Nothing was changed`, because a
  turn cannot start. `reset` still flips this window's switch and takes nothing from the other process.

Setting reference: [`harness.jit`](/guide/config#optional-settings-reference) and [Commands](/guide/commands).
