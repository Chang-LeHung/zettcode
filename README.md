<p align="center">
  <img src="clients/vscode/media/logo.svg" width="120" alt="ZettCode mascot riding a sword past the moon" />
</p>
<h1 align="center">ZettCode</h1>
<p align="center"><strong>A terminal coding agent that can write its own tools and work with other agents.</strong></p>
<p align="center">
  <strong>English</strong> · <a href="README.zh-CN.md">简体中文</a><br />
  <a href="https://chang-lehung.github.io/zettcode/guide/getting-started">Get started</a> ·
  <a href="https://chang-lehung.github.io/zettcode/guide/capabilities">What it can do</a> ·
  <a href="https://chang-lehung.github.io/zettcode/">Documentation</a> ·
  <a href="https://chang-lehung.github.io/zettcode/guide/commands">Commands</a> ·
  <a href="https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode">VS Code extension</a>
</p>

<p align="center">
  <img src="docs/public/terminal.svg" width="1000" alt="ZettCode showing a task, thinking, file reads, a code edit, passing tests, and a Markdown answer" />
</p>
<p align="center"><sub>Illustrative conversation, rendered with ZettCode’s actual terminal widgets.</sub></p>

ZettCode works in your terminal on the files of one workspace: it shows its reasoning and tool calls as readable rows,
asks before it runs shell commands, and lets you resume any conversation. Beyond that single session it can write small
tools for itself, hand a review to a second agent, run agents in the background, and let sessions message each other and
share groups, including Codex and Claude Code, from one web page.

## What is different

| Capability | In one line | Try it |
| --- | --- | --- |
| **JIT harness** | The model writes a small Python tool, loads it in a child process and calls it in the same turn. | `/harness gen` |
| **Code review** | A second agent reads your uncommitted changes while you keep the conversation. | `/code-review` |
| **Background agents** | A session with nobody at the keyboard; it keeps running when you close the terminal. | `zettcode daemon spawn` |
| **Messaging, `@` and groups** | Sessions on one machine message each other; `@name` points the model at one, a group reaches all its members. | `@name` in the composer |
| **The Graph page** | Sessions as nodes, groups as regions, messages as they travel, with replay. | `zettcode gateway start` |
| **Web gateway** | A page for daemons, sessions and groups. Also on a phone, and in a desktop or Android shell. | `zettcode gateway start` |
| **Codex and Claude Code** | Both run as members you can message and put in groups. | New → External agent |

[What it can do](https://chang-lehung.github.io/zettcode/guide/capabilities) has a section on each: what it is, how it
differs from one terminal session, and what to run.

## Get running

You need **Python 3.10+**, a UTF-8 terminal, and an **OpenAI-compatible API** (or Anthropic's **Messages API**).
Works on macOS, Linux, and Windows (use Windows Terminal).

### 1. Install

```bash
uv tool install "zettcode[all]"
# or: pip install "zettcode[all]"
```

Keep the quotes: `fish` and `zsh` read an unquoted `[all]` as a pattern. `zettcode` alone is the smaller install
(terminal, gateway, server, SDK). `[all]` adds `/monitor`, `/recap`, official vendor models and Codex/Claude Code in the
gateway; the extras are `monitor`, `recap`, `models` and `code-agents` if you want only some. The vendor models stay
off until `[plugins] enable = ["models"]` names them. Codex and Claude Code also
need their own command-line tools installed and signed in.

### 2. Connect a model

Create `~/.zettcode/config.toml` (and its parent directory) with one model:

```toml
[[models]]
model = "deepseek-v4-pro"             # the model id sent to DeepSeek
display_model = "DeepSeek Pro"        # the name shown in ZettCode
token = "sk-..."                      # replace with your DeepSeek API key
base_url = "https://api.deepseek.com"  # DeepSeek's OpenAI-compatible API root
context_window = 1000000               # verify against the endpoint's current limits
multimodal = false                    # this model accepts text, not images
```

Get a key from the [DeepSeek platform](https://platform.deepseek.com/), not from the chat website. Alternatively, omit
`token` and set `OPENAI_API_KEY` to that key. Add more `[[models]]` entries to switch with `/model`; the first is
selected at startup. See the [configuration reference](https://chang-lehung.github.io/zettcode/guide/config) for
complete examples, defaults, and troubleshooting.

### 3. Start a task

```bash
cd /path/to/project
zettcode
# or: zettcode --workspace /path/to/project
```

Describe a change and press **Enter**. Type `/` for commands, `@` to reference a skill or another session, and
**Ctrl-C** to stop a request. **Ctrl-D** with an empty composer exits and prints the command to resume your session.

## Five minutes: try each capability

Each step stands on its own. Run them from a project directory, in a git checkout for step 2.

**1. Let the model write a tool.** In a ZettCode session:

```text
/harness gen list the TODO comments in this repository, grouped by file
```

The model writes a tool under `~/.zettcode/harness/`, loads it with `repo_load` and runs it, and reports the result. Or
start every run with it on by putting `jit = true` under `[harness]` in `config.toml`. It is off by default, and at
the `full` shell level the code it writes has your own access. `/harness reset` turns it off again.

**2. Have the change reviewed.** With uncommitted changes in the workspace:

```text
/code-review
/code-review the error handling in src/api.py
```

The model starts (or reuses) a background session named `code-review`, sends it the diff request, and goes round again
after each fix. The reviewer runs at your own shell level (at `safe` when yours is `ask`) and is told to read, not
change; that is an instruction, not a sandbox.

**3. Run an agent in the background and talk to it.**

```bash
zettcode daemon spawn --name builder --title "tool builder" --permission safe
zettcode daemon list
```

Then, in a terminal session, type `@` and pick it from the menu: its name comes from the title, so here it is
`@tool-builder`.

```text
❯ @tool-builder write a helper that lists TODO comments, then tell me its name
```

<p align="center">
  <img src="docs/public/demo/daemon.gif" width="800" alt="A background agent builds, loads and runs a find_todos tool, then answers a follow-up" />
</p>

A daemon asks nobody, so nobody can approve its commands: `--permission` defaults to `full` (no sandbox) and there is no
`ask`. Use `safe` (sandboxed) or `deny` (no shell) unless the workspace is one you would give a shell to.
`zettcode daemon stop <session-id>` stops it and keeps its record.

**4. Open the gateway, make a group, watch the Graph.**

```bash
zettcode gateway start
```

Open the address it prints. **Chats** lists your daemons and sessions; **New group** makes a group and a message to it
reaches every connected member. **Graph** draws sessions as nodes and groups as regions, with each message travelling
along its line, and can replay up to 20,000 stored messages. The page works on a phone (listening beyond this machine
needs `--token`; see the [gateway guide](https://chang-lehung.github.io/zettcode/guide/gateway)).

<p align="center">
  <img src="docs/public/demo/group.gif" width="800" alt="Creating a group, mentioning the builder agent, and reading its reply" />
</p>
<p align="center">
  <img src="docs/public/demo/graph.gif" width="720" alt="The Graph page: eight sessions in one group, messages flowing between them" />
</p>

**5. Add Codex or Claude Code.** With `[all]` installed and the `codex` or `claude` CLI signed in for your user:

```bash
zettcode gateway restart
```

In the gateway, open **New**, choose the **External agent** tab, pick Codex or Claude Code, optionally give a group to
join, and press **Start external agent**. Their permission defaults to `full` and `--no-full` does not limit them;
narrow it in `~/.zettcode/code-agents/config.json` (see the
[guide](https://chang-lehung.github.io/zettcode/guide/code-agents)).

## Built for the way you work

| | |
| --- | --- |
| **See every step** | Reasoning, answers, and tool calls stream as readable rows, not raw JSON. |
| **Keep the decision** | Review shell commands before they run. When the agent needs your input, choose an option or type an answer. |
| **Keep moving** | Type during a reply and choose: steer it now, or queue a follow-up you can edit and reorder. `/btw` asks a side question that stays out of later context. |
| **Come back later** | `/resume` restores a conversation; `/export` saves a readable HTML record. |
| **Understand the context** | Monitor token usage and caching, inspect `/context`, and compact when needed. |
| **Bring your tools** | Project `AGENTS.md` instructions, skills, MCP servers, and Python plugins. |

## Find your next step

The **[user guide](https://chang-lehung.github.io/zettcode/guide/overview)** is available in English and
[简体中文](https://chang-lehung.github.io/zettcode/zh/guide/overview).

| Start | Use it alone | Work with several agents | Configure & extend |
| --- | --- | --- | --- |
| [Getting started](https://chang-lehung.github.io/zettcode/guide/getting-started) | [The interface](https://chang-lehung.github.io/zettcode/guide/interface) | [Talking between sessions](https://chang-lehung.github.io/zettcode/guide/messaging) | [Configuration](https://chang-lehung.github.io/zettcode/guide/config) |
| [What it can do](https://chang-lehung.github.io/zettcode/guide/capabilities) | [Commands](https://chang-lehung.github.io/zettcode/guide/commands) | [Background agents](https://chang-lehung.github.io/zettcode/guide/daemons) | [Models & context](https://chang-lehung.github.io/zettcode/guide/models) |
| [Problems & questions](https://chang-lehung.github.io/zettcode/guide/faq) | [Code review](https://chang-lehung.github.io/zettcode/guide/code-review) · [JIT harness](https://chang-lehung.github.io/zettcode/guide/harness) | [Web gateway](https://chang-lehung.github.io/zettcode/guide/gateway) · [Desktop & phone](https://chang-lehung.github.io/zettcode/guide/app) | [Skills & MCP](https://chang-lehung.github.io/zettcode/guide/skills-and-mcp) · [Plugins](https://chang-lehung.github.io/zettcode/guide/plugins) |
| | [Sessions](https://chang-lehung.github.io/zettcode/guide/sessions) | [Codex & Claude Code](https://chang-lehung.github.io/zettcode/guide/code-agents) | [Project instructions](https://chang-lehung.github.io/zettcode/guide/instructions) |

Embedding it elsewhere: the [**SDK**](https://chang-lehung.github.io/zettcode/sdk/) drives the agent from Python, and the
[**server**](https://chang-lehung.github.io/zettcode/server/) exposes it over HTTP — prompts streamed as they run,
with sessions, approvals, steering and models. For VS Code, the
[extension](https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode) is a sidebar chat built on the same
server; its sources are in [`clients/vscode/`](clients/vscode/README.md).

## Development

```bash
uv sync                          # install the package
make check                      # what this change needs: Ruff, mypy, tests, the JS clients — only what it touched
make check-all                  # every suite, whether or not the change needs it
make client                     # build and test the TypeScript client
make vscode                     # type-check, test and build the VS Code extension
make hooks                      # enforce mypy before commits
make demo                       # browse terminal widgets
make docs                       # preview the user guide locally
uv run zettcode --workspace .    # run from the checkout
```

ZettCode provides the terminal application and its HTTP server; the agent runtime is
[`zett-agent`](https://github.com/Chang-LeHung/zett-agent). The repository is a uv workspace of one distribution per
subsystem under `packages/` — the program a reader installs, the engine it is built on, the widget framework, the
broker, the SDK, the server and the gateway, the terminal application, and the plugin API — sharing one `zettcode`
namespace; the plugins (`/monitor`, `/recap`, the vendor models and Codex/Claude Code, all in `zettcode[all]`) are
published beside them. `clients/typescript/` is the TypeScript
client for the server, and `clients/vscode/` is the
VS Code sidebar built on that client. Contributor notes and
invariants live in [`AGENTS.md`](AGENTS.md) and
[`docs/internal/`](docs/internal/), separately from the user guide. See
[`docs/internal/site-design.md`](docs/internal/site-design.md) for preview and
asset-generation instructions.

## License

MIT. See [`LICENSE`](LICENSE).
