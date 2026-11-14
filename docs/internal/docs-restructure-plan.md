# Documentation restructure: the plan

Why: the guide is accurate but organised by *feature page*, so a reader never learns what ZettCode does that other
terminal agents do not. The README opens on one idea (the JIT harness) and buries the rest. Install says `uv tool
install zettcode`, which leaves out the plugins most of the differentiating features need.

## What changes

1. **Install is `zettcode[all]` everywhere** (README, getting-started, the site's home page, FAQ). `all` = monitor, recap,
   models, code-agents. `pip install zettcode` still works and is said to be the smaller install.
2. **README = pitch + a quick start that shows each capability once, with a command that works.** Order: what is
   different (one line each) -> install -> connect a model -> first task -> *the five things worth trying* (each 3-6
   lines with the real command) -> where to read more.
3. **New guide page `guide/capabilities` ("What it can do")**: one section per differentiator, each with *what it is,
   why it is different, how to use it (commands that exist), where the details are*. Linked first in the sidebar.
4. **Sidebar regrouped by what the reader is doing**, not by feature page:
   - Start: Overview, Capabilities, Getting started
   - Use it alone: Interface, Keys, Commands, Sessions, Code review
   - Work with several agents: Messaging & groups, Background agents, Web gateway, Codex & Claude Code, Desktop & phone
   - Configure & extend: Models/Context/Usage, Config, Instructions, Memory, Skills & MCP, Plugins
   - Help: FAQ
5. **New pages**: `capabilities`, `code-review`, `code-agents` (the plugin README is the only doc today),
   `harness` (JIT harness has no page of its own; it lives in config.md and commands.md).
6. Outdated text corrected as found (desktop/phone were fixed in #324; check install lines, `zettcode[models]` only).
7. Both languages, same structure. Every command shown is run or checked against `--help` before it is written.

## The differentiators (the facts each section may state)

| Capability | What is true (checked in code/docs) |
| --- | --- |
| JIT harness | `[harness] jit = true` or `/harness gen`; the model writes a Python tool into `~/.zettcode/harness/...`, `repo_load` imports it in a child process; below `full` it runs in the `safe` sandbox; `BAN_TOOLS` forbids names. |
| Code review | `/code-review [focus]`: the model starts or reuses a daemon named `code-review` (read-only by instruction, at the reader's own shell level, never above it), sends it the diff request, loops until it has nothing to change; if a round gets no answer it reads the reviewer's last assistant message. |
| Daemons | `zettcode daemon spawn/list/stop/kill/delete/update/prompt/log`; a session with nobody at the keyboard; reached by `send_message`; survives the terminal; restartable (`stop` keeps the record). |
| Messaging | Every session registers with a local broker (127.0.0.1, token file). `@name` references a session; the model sends with `send_message`. steer vs follow-up while busy. |
| Groups | `#name`, `manage_group` tool or `POST /groups`; message goes to every connected member; limits 64/20/200. |
| Graph | Gateway **Graph** page: sessions as nodes, groups as regions, live packets, replay of up to 20,000 stored messages. |
| Gateway | `zettcode gateway start`; web page for daemons, sessions, groups; token sign-in, read-only token, metrics, audit log; works on a phone; desktop (Electron) and Android shells open it. |
| Codex / Claude Code | `zettcode-code-agents`: both appear on the gateway's New page, join groups, are addressed with `@`; permission `full` by default (the plugin's choice); settings in `~/.zettcode/code-agents/config.json`. |

Not claimed anywhere: that raw mode / direct prompts are widely used, that Windows/Linux desktop installers were run by
us on those systems (only built), or that Codex `workspace`/`read` limits a *resumed* run (the plugin README says it is
unverified).

## Out of scope here

Rewriting `plugins.md` (1,320 lines, an API reference), the SDK/server pages, or the internal docs.
