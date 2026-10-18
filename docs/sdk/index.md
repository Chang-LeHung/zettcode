---
title: ZettCode SDK
---

# ZettCode SDK

The ZettCode SDK brings the coding agent to your Python programs without a terminal. Everything the terminal application offers — running prompts, streaming progress, answering approvals, managing sessions, switching models, compacting, exporting — is available from code, running the same agent, tools, plugins, MCP servers, skills, and project instructions.

## What it does

```python
import zettcode.sdk as zc

result = await zc.prompt("fix the failing test", workspace=".", permission="safe")
print(result.text)
```

- **Run prompts** and read the result, or stream events as they happen
- **Answer approvals and questions** with handlers or by responding to events
- **Manage sessions** — create, continue, fork, export, and read history
- **Switch models and permission levels** mid-conversation
- **Resume interrupted requests** from where they stopped
- **Compact, measure context, check usage** programmatically

The same session can be started in code and continued in the terminal, or the other way round. The SDK uses the same session store.

## Who it's for

- **Scripts** that need an agent to run unattended: test fixtures, CI pipelines, batch processing
- **Tools** that embed ZettCode: editors, IDEs, automation frameworks
- **Custom UIs** that want the agent without the terminal application's interface
- **Research and experimentation** where the conversation is data

## Installation

```bash
pip install zettcode
```

The SDK is part of the `zettcode` package. Importing it costs nothing; the agent loads when a client is made.

```python
import zettcode.sdk as zc
```

## First steps

- [**Quickstart**](./quickstart) — one prompt, one conversation, streaming progress
- [**Core concepts**](./concepts) — how clients, sessions, runs, and events fit together
- [**Client & configuration**](./client) — models, settings, workspaces

## Guides

- [**Running prompts**](./running) — `prompt()`, `run()`, `stream()`, and what they return
- [**Streaming events**](./events) — `TextDelta`, `ToolStarted`, `ApprovalRequested`, and the rest
- [**Approvals & questions**](./approvals) — handlers, answering inline, permission levels
- [**Sessions**](./sessions) — creating, switching, forking, history, export
- [**Errors & timeouts**](./errors) — what raises what, retrying, partial results

## Examples

The [**Cookbook**](./cookbook) shows complete programs:

- Unattended scripts with approval rules
- Progress bars and live output
- Multi-session workflows
- Error handling and retry logic
- Integration with existing code

## Reference

[**API reference**](./reference) — every class, method, and attribute

## Key differences from the terminal

- **No broker by default**: `sessions_enabled=False`, so terminal sessions cannot message SDK clients
- **No release checks**: `update_enabled=False`
- **Working directory**: creating a client changes it to the workspace; closing the last client restores it
- **One workspace per process**: two clients on different workspaces cannot be open at once

## Next

Start with the [**Quickstart**](./quickstart) to see the SDK in action, then move to [**Core concepts**](./concepts) for how the pieces fit together.
