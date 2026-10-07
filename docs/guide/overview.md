# Find your next step

ZettCode works in your terminal, on the files in your workspace. This guide is
organized around what you want to do — start a first task, keep a conversation
moving, or set up the tools and models that suit your project.

## First time here?

1. **[Install and connect a model](/guide/getting-started).** You need Python
   3.10+, a terminal, and an OpenAI-compatible API. The quickstart takes you from
   installation to your first task.
2. **[Get to know the screen](/guide/interface).** Understand thinking, tool
   output, the composer, and the status line.
3. **[Keep the essentials handy](/guide/keys).** Enter submits, Ctrl-C stops a
   request, and Ctrl-D exits when the composer is empty.

## Working on a project

| I want to… | Go to |
| --- | --- |
| Switch models, change reasoning effort, or ask a side question | [Commands](/guide/commands) |
| Select text, paste an image, or scroll back to an answer | [Keys & mouse](/guide/keys) |
| Continue an earlier session or export it to HTML | [Sessions](/guide/sessions) |
| Understand context usage, compaction, and caching | [Models & context](/guide/models) |

Typing while the agent works sends a **steering message** that it picks up at
the next tool or model boundary. Use `/btw <question>` instead when you want an
answer that will not join the context of later requests. See
[The interface](/guide/interface) for both.

## Make it yours

- **[Configuration](/guide/config):** model connections, optional capabilities,
  and your theme. Start here when you want to change a setting.
- **[Project instructions](/guide/instructions):** write `AGENTS.md` to explain
  conventions, test commands, and boundaries for your workspace.
- **[Skills & MCP](/guide/skills-and-mcp):** give the agent reusable instructions
  or connect external tools.
- **[Plugins](/guide/plugins):** install Python extensions that add commands and
  customize the interface.

## Something not working?

Start with [Problems & questions](/guide/faq). For a reproducible bug, open an
[issue on GitHub](https://github.com/Chang-LeHung/zettcode/issues). Include the
OS, terminal, ZettCode version, and the steps to reproduce it; leave API tokens
and private conversation content out.
