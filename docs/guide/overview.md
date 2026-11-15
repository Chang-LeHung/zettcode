# Find your next step

ZettCode is a coding agent that runs in your terminal, on the files of one directory, and asks before it runs a shell
command. Pick the route that matches what you are doing now.

## First time here

- **[Getting started](/guide/getting-started).** Install, connect a model, run a first task. You need Python 3.10+ and
  a token for an OpenAI-compatible or Anthropic endpoint.
- **[What it can do](/guide/capabilities).** The eight things it does beyond one session in one terminal, each with a
  command that starts it.
- **[The interface](/guide/interface) and [keys](/guide/keys).** What each row on the screen means; Enter submits,
  Ctrl-C stops a request, Ctrl-D exits when the composer is empty and nothing runs.

## Every day

- **[Commands](/guide/commands).** Every slash command and every `zettcode` option, in tables.
- **[Sessions](/guide/sessions) and [the context window](/guide/context).** Resume yesterday's conversation, export it
  to HTML, and read how full the model's window is.
- **[The JIT harness](/guide/harness).** The model writes the small tool the task needs, loads it, and calls it.

Typing while the agent works asks whether to **steer** the running request or **follow up** after it, as a message of
its own. `/btw <question>` gets an answer that never joins the context of later requests; [The
interface](/guide/interface) covers all three.

## Several agents

- **[Code review](/guide/code-review).** A second agent reads your uncommitted changes and reports what it would fix.
- **[Background agents](/guide/daemons).** A session with nobody at the keyboard, which keeps running after you close
  the terminal.
- **[Talking between sessions](/guide/messaging), [the web gateway](/guide/gateway), [desktop & phone apps](/guide/app),
  [Codex & Claude Code](/guide/code-agents).** Sessions message each other, join groups, and can be watched from a
  browser.

## Make it yours

[Configuration](/guide/config) covers models, permissions and theme; [project instructions](/guide/instructions) put
your conventions in `AGENTS.md`; [skills & MCP](/guide/skills-and-mcp) and [plugins](/guide/plugins) add commands and
tools. The [SDK](/sdk/) drives the same agent from Python.

Stuck? [Problems & questions](/guide/faq) has the common failures. For a reproducible bug, open an [issue on
GitHub](https://github.com/Chang-LeHung/zettcode/issues) with the OS, the terminal, the version and the steps.
