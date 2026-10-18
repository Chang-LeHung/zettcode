---
title: Client & configuration
---

# Client & configuration

`Client` is where a program starts. This page covers how to create one, where its configuration comes from, how to choose the model, reasoning effort and permission level, and how to close it.

## Creating a client

```python
import zettcode.sdk as zc

async with zc.Client("~/project", model="gpt-5", effort="high", permission="safe") as client:
    print(client)       # Client('/Users/me/project', session='...')
```

| Argument | Meaning |
| --- | --- |
| `workspace` | The directory the agent works in. `None` is the current directory (or `config.workspace`). `~` is expanded, and it must exist. |
| `config` | A ready `ZettCodeConfig`. Nothing is read from disk and the embedding defaults are not applied. |
| `config_path` | A config file to read instead of `$ZETTCODE_CONFIG` or `~/.zettcode/config.toml`. |
| `models` | Models to use without any config file; the first is active. See [below](#models-without-a-config-file). |
| `model` | The model to start on, by the name `client.models` lists. |
| `effort` | The reasoning level to start on. |
| `permission` | The shell permission level: `deny`, `ask`, `safe` or `auto`. |
| `resume` | A session id to continue instead of starting a new conversation. |
| `**settings` | Any other configuration field by name: `store=`, `mcp_enabled=`, `max_iterations=`, and so on. |

The constructor is synchronous and does its work at once: a bad value raises here, not on the first prompt.

```python
try:
    zc.Client(".", permission="sometimes")
except zc.ConfigurationError as error:
    print(error)       # Unknown permission: sometimes. Try one of: deny, ask, safe, auto
```

## Where the configuration comes from

In order of precedence:

1. **`config=`**, a ready `ZettCodeConfig`, used as given.
2. **`models=`**, laid over the defaults. The config file is not read at all.
3. **The config file**: `config_path=`, else `$ZETTCODE_CONFIG`, else `~/.zettcode/config.toml`. This is the same file the terminal reads, so [models](/guide/models) and [settings](/guide/config) you have already set up apply.

Keyword settings are laid over whichever of the three you used. This is the whole story: there is no hidden fourth source.

## Models without a config file

Pass the models directly when the program should not depend on what is installed on the machine, as in CI or a container:

```python
async with zc.Client(
    ".",
    models=[
        {"model": "claude-sonnet-4-5", "token": "sk-ant-...", "anthropic": True, "multimodal": True},
        {"model": "gpt-5", "token": "sk-...", "context_window": 400_000},
    ],
    store="/tmp/zettcode-sessions",
) as client:
    print([m.name for m in client.models])       # ['claude-sonnet-4-5', 'gpt-5']
```

An entry is a `ModelConfig` or a dict of the same fields:

| Field | Default | Meaning |
| --- | --- | --- |
| `model` | required | The model id sent to the endpoint. |
| `token` | required | The credential. Read it from the environment rather than writing it into code. |
| `display_model` | `None` | The name to show and to pass to `use_model`. Give one when two entries share a model id. |
| `base_url` | `None` | The API root. A trailing `/chat/completions`, `/v1/messages` or `/responses` is dropped. |
| `anthropic` | `False` | Speak Anthropic's Messages API. |
| `responses_api` | `False` | Use the Responses API on an OpenAI-compatible endpoint. Not combinable with `anthropic`. |
| `multimodal` | `False` | Whether the model accepts images. |
| `context_window` | `128000` | Tokens the model can carry. |
| `compact_percent` | `80.0` | The share of the window at which the conversation is compacted. |
| `reasoning_efforts` | all levels | The reasoning levels the model accepts. |

::: warning
A token written into source ends up in version control. Read it from the environment: `{"model": "gpt-5", "token": os.environ["OPENAI_API_KEY"]}`.
:::

A malformed entry raises `ConfigurationError` that names the entry and the problem.

## Settings

Any other keyword is a field of `ZettCodeConfig`, so everything the config file can say, a client can say in code. The ones a program usually wants:

| Setting | Default | Effect |
| --- | --- | --- |
| `store` | `~/.zettcode/sessions` | Where sessions are kept. Point it at a temporary directory in tests. |
| `max_iterations` | `360` | Tool-call rounds allowed in one turn. |
| `mcp_enabled` | `True` | Load MCP servers. |
| `skills_enabled` | `True` | Discover local skills and offer them to the model. |
| `agents_md_enabled` | `True` | Give the model the `AGENTS.md` files that apply to the workspace. |
| `ask_user_enabled` | `True` | Give the model the `ask_user` tool. Switch it off for runs nobody can answer. |
| `subagent_enabled` | `True` | Offer the `task` tool, which runs a child agent. |
| `todowrite_enabled` | `False` | Offer the `todo_write` tool. |
| `plugins_enabled` | `True` | Load third-party plugins. |
| `parallel_tool_call` | `True` | Let the model issue tool calls in parallel. |
| `sessions_enabled` | `False` here | Join the broker so terminal sessions can message this one. |
| `update_enabled` | `False` here | Check PyPI for a new release. |

Strings are accepted where a path is expected (`store="~/runs"`), and choices are accepted in any case (`reasoning_effort="HIGH"`). A mistyped name is reported with a suggestion:

```python
zc.Client(".", max_iteration=50)
# ConfigurationError: Unknown setting: 'max_iteration' (did you mean 'max_iterations'?)
```

A value the configuration refuses is reported as `ConfigurationError("Invalid configuration: ...")`, with the original error as `__cause__`.

### A hermetic client

For a test or a sandboxed job, switch off everything that reads from or reaches outside the workspace:

```python
client = zc.Client(
    workspace,
    models=[{"model": "gpt-5", "token": token}],
    store=scratch / "sessions",
    mcp_enabled=False,
    skills_enabled=False,
    agents_md_enabled=False,
    plugins_enabled=False,
    subagent_enabled=False,
)
```

## Choosing the model, effort and permission

These are set when the client is made, or changed at any time between runs.

```python
async with zc.Client(".") as client:
    for info in client.models:
        marker = "*" if info.active else " "
        print(marker, info.name, info.context_window, info.efforts)

    client.use_model("gpt-5")
    client.use_effort("high")
    client.use_permission("safe")

    print(client.model.name, client.effort, client.permission)
```

| Member | Returns |
| --- | --- |
| `client.models` | A tuple of `ModelInfo(name, model, context_window, multimodal, efforts, active)`. |
| `client.model` | The `ModelInfo` of the active model. |
| `client.use_model(name)` | Makes a model active and returns its `ModelInfo`. Takes the name or a `ModelInfo`. |
| `client.effort`, `client.efforts` | The current level, and the levels the active model accepts. |
| `client.use_effort(name)` | Sets the level and returns it. |
| `client.permission`, `client.permissions` | The current level, and `("deny", "ask", "safe", "auto")`. |
| `client.use_permission(name)` | Sets the level; it applies from the next shell command, even in a run that is already going. |

A name that does not exist, or a reasoning level the active model does not take, raises `ConfigurationError` with the valid choices in the message.

```python
async with zc.Client(".", models=[{"model": "a", "token": "t"}, {"model": "b", "token": "t"}]) as client:
    try:
        client.use_model("c")
    except zc.ConfigurationError as error:
        print(error)       # Unknown model: c. Configured: a, b
```

The model change takes effect for the next run. A conversation can move between models: the history is kept.

### Permission levels

The permission level decides who answers when the model wants to run a shell command. It governs the shell only; file tools and MCP tools are not behind it.

| Level | A shell command… |
| --- | --- |
| `deny` | …never runs. The model is told and carries on with the file tools. |
| `ask` | …is put to you (the `ApprovalRequested` event). This is the default. |
| `safe` | …runs unasked when it provably cannot change anything (`git status`, `ls`); anything else is put to you. |
| `auto` | …runs unasked. Only for a workspace and a model you would trust with a shell. |

See [Approvals & questions](./approvals) for how to answer.

## Looking at what loaded

```python
async with zc.Client(".") as client:
    report = client.plugins
    print(report.loaded)       # ('shell', 'skills', ..., 'coding', ..., 'ask-user', 'mcp', 'compaction')
    print(report.failures)     # one message per plugin that could not load; never fatal
    print(client.config.workspace, client.config.store)
    print(client.usage)        # what the current session has spent
```

`client.config` is the `ZettCodeConfig` in force, which is frozen: build a new client to change a setting that is not one of the `use_*` methods.

## Closing

```python
client = zc.Client(".")
try:
    await client.prompt("hello")
finally:
    await client.aclose()
```

`async with` does this for you. Closing stops a run in progress, releases the provider connection and the session lock, and restores the process's working directory when the last client closes. It is safe to call twice. After it, every method raises `ClientClosedError`.

::: tip
If the constructor raises, nothing is left open: the lock and the working directory are released before the error reaches you.
:::

## One workspace per process

A client changes the process's working directory to its workspace because the coding tools resolve relative paths against it. Two clients on the **same** workspace are fine. A client on a **different** one raises `WorkspaceConflictError` until the first closes.

```python
from zettcode.sdk.errors import WorkspaceConflictError

async with zc.Client("/work/a") as a:
    try:
        zc.Client("/work/b")
    except WorkspaceConflictError as error:
        print(error)
```

To work on two workspaces at once, use two processes: `multiprocessing`, a subprocess, or a job queue.

## Resuming a stored session

```python
async with zc.Client(".", resume="3f8a1c20") as client:
    print(client.session.title)
    result = await client.prompt("where were we?")
```

An id that cannot be read raises `SessionNotFoundError` from the constructor. See [Sessions](./sessions) for finding ids.
