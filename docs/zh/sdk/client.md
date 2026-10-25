---
title: Client 与配置
---

# Client 与配置

`Client` 是程序的起点。本页讲怎么创建一个 client、它的配置从哪里来、怎么选择模型、推理强度和权限级别，以及怎么关闭。

## 创建 client

```python
import zettcode.sdk as zc

async with zc.Client("~/project", model="gpt-5", effort="high", permission="safe") as client:
    print(client)  # Client('/Users/me/project', session='...')
```

| 参数 | 含义 |
| --- | --- |
| `workspace` | agent 工作的目录。`None` 表示当前目录（或 `config.workspace`）。会展开 `~`，且必须存在。 |
| `config` | 现成的 `ZettCodeConfig`。不读磁盘，也不应用嵌入场景的默认值。 |
| `config_path` | 要读取的配置文件，代替 `$ZETTCODE_CONFIG` 或 `~/.zettcode/config.toml`。 |
| `models` | 不用配置文件时直接指定的模型，第一个是当前模型。见[下文](#不用配置文件指定模型)。 |
| `model` | 起始使用的模型，用 `client.models` 列出的名字。 |
| `effort` | 起始的推理级别。 |
| `permission` | shell 权限级别：`deny`、`ask`、`safe` 或 `full`（`full` 的旧名 `auto` 仍然可用）。 |
| `resume` | 要继续的会话 id，而不是新开一段对话。 |
| `**settings` | 其他任意配置字段，按字段名传入：`store=`、`mcp_enabled=`、`max_iterations=` 等。 |

构造函数是同步的，立即完成工作：错误的值在这里就会抛出，而不是等到第一个 prompt。

```python
try:
    zc.Client(".", permission="sometimes")
except zc.ConfigurationError as error:
    print(error)  # Unknown permission: sometimes. Try one of: deny, ask, safe, full
```

## 配置从哪里来

按优先级：

1. **`config=`**，一份现成的 `ZettCodeConfig`，原样使用。
2. **`models=`**，叠加在默认值之上，完全不读配置文件。
3. **配置文件**：`config_path=`，否则 `$ZETTCODE_CONFIG`，否则 `~/.zettcode/config.toml`。这就是终端读的那个文件，所以你已经配好的[模型](/zh/guide/models)和[设置](/zh/guide/config)都会生效。

关键字设置会叠加在你用的那一种之上。故事就是这些，没有隐藏的第四个来源。

## 不用配置文件指定模型

当程序不该依赖机器上装了什么时（比如 CI 或容器里），直接传模型：

```python
async with zc.Client(
    ".",
    models=[
        {"model": "claude-sonnet-4-5", "token": "sk-ant-...", "anthropic": True, "multimodal": True},
        {"model": "gpt-5", "token": "sk-...", "context_window": 400_000},
    ],
    store="/tmp/zettcode-sessions",
) as client:
    print([m.name for m in client.models])  # ['claude-sonnet-4-5', 'gpt-5']
```

一个条目是 `ModelConfig`，或者字段相同的 dict：

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `model` | 必填 | 发给端点的模型 id。 |
| `token` | `""` | 凭证。本地服务器不需要时可以留空，也可以取自 `OPENAI_API_KEY`（Anthropic 模型取自 `ANTHROPIC_API_KEY`）。请从环境变量读取，不要写进代码。 |
| `display_model` | `None` | 展示用的名字，也是传给 `use_model` 的名字。两个条目模型 id 相同时给其中一个起别名。不能有两个条目用同一个名字显示，读配置时发现就会报错。 |
| `base_url` | `None` | API 根地址。末尾的 `/chat/completions`、`/v1/messages` 或 `/responses` 会被去掉。 |
| `anthropic` | `False` | 使用 Anthropic 的 Messages API。 |
| `responses_api` | `False` | 在 OpenAI 兼容端点上使用 Responses API。不能与 `anthropic` 同时使用。 |
| `chat` | `False` | 明确写出端点使用 chat completions，这也是前两者都没设置时本来的含义。不能与 `anthropic` 或 `responses_api` 同时使用。 |
| `multimodal` | `False` | 模型是否接受图片。 |
| `temperature` | `None` | 随每个请求发送的采样温度，0 到 2（Anthropic 模型为 0 到 1）。不写就用提供商的默认值。 |
| `context_window` | `128000` | 模型能承载的 token 数。 |
| `compact_percent` | `80.0` | 占窗口多大比例时压缩对话。 |
| `reasoning_efforts` | 全部级别 | 模型接受的推理级别。 |

::: warning
写进源码的 token 会进入版本控制。请从环境变量读取：`{"model": "gpt-5", "token": os.environ["OPENAI_API_KEY"]}`。
:::

格式错误的条目会抛出 `ConfigurationError`，指明是哪个条目、什么问题。

## 设置

其余任何关键字都是 `ZettCodeConfig` 的字段，所以配置文件能表达的，client 在代码里也能表达。程序常用的几项：

| 设置 | 默认值 | 作用 |
| --- | --- | --- |
| `store` | `~/.zettcode/sessions` | 会话保存的位置。测试里请指向临时目录。 |
| `max_iterations` | `360` | 一轮里允许的工具调用轮数。 |
| `mcp_enabled` | `True` | 加载 MCP 服务器。 |
| `skills_enabled` | `True` | 发现本地 skills 并提供给模型。 |
| `agents_md_enabled` | `True` | 把适用于工作区的 `AGENTS.md` 交给模型。 |
| `ask_user_enabled` | `True` | 给模型 `ask_user` 工具。没人能回答的运行请关掉。 |
| `subagent_enabled` | `True` | 提供运行子 agent 的 `task` 工具。 |
| `todowrite_enabled` | `False` | 提供 `todo_write` 工具。 |
| `plugins_enabled` | `True` | 加载第三方插件。 |
| `parallel_tool_call` | `True` | 允许模型并行发起工具调用。 |
| `sessions_enabled` | 此处为 `False` | 连接 broker，让终端会话可以给它发消息。 |
| `update_enabled` | 此处为 `False` | 向 PyPI 检查新版本。 |

需要路径的地方可以传字符串（`store="~/runs"`），选项不区分大小写（`reasoning_effort="HIGH"`）。拼错的名字会附带建议：

```python
zc.Client(".", max_iteration=50)
# ConfigurationError: Unknown setting: 'max_iteration' (did you mean 'max_iterations'?)
```

配置拒绝的值会报成 `ConfigurationError("Invalid configuration: ...")`，原始错误保存在 `__cause__`。

### 封闭的 client

测试或沙箱任务里，把所有会读取或触及工作区之外的东西都关掉：

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

## 选择模型、推理强度和权限

创建 client 时设置，也可以在两次 run 之间随时更改。

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

| 成员 | 返回 |
| --- | --- |
| `client.models` | 一组 `ModelInfo(name, model, context_window, multimodal, efforts, active, compact_percent)`。 |
| `client.model` | 当前模型的 `ModelInfo`。 |
| `client.use_model(name)` | 让某个模型成为当前模型并返回它的 `ModelInfo`。接受名字或 `ModelInfo`；名字先当显示名找，没人用它显示时才当模型 id。 |
| `client.effort`、`client.efforts` | 当前级别，以及当前模型接受的级别。 |
| `client.use_effort(name)` | 设置级别并返回。 |
| `client.use_compact_percent(percent)` | 从下一次请求起,改变对话在窗口的多大比例(大于 0、至多 100)时被总结。返回当前的 `ModelInfo`,以及配置文件没有被改写的原因(改写了就是 `None`):那样这次改动只在本次运行有效。 |
| `client.permission`、`client.permissions` | 当前级别，以及 `("deny", "ask", "safe", "full")`。 |
| `client.harness` | just-in-time harness 是否开启：模型可以自己写小的 Python 工具并运行。默认关闭；`Client(jit_harness=True)` 让客户端一开始就开启。 |
| `client.use_harness(on)` | 从下一次 prompt 起开启或关闭，返回新状态。 |
| `client.use_permission(name)` | 设置级别；从下一条 shell 命令起生效，正在进行的 run 里也一样。 |

不存在的名字，或当前模型不接受的推理级别，会抛出 `ConfigurationError`，消息里列出可选项。

```python
async with zc.Client(".", models=[{"model": "a", "token": "t"}, {"model": "b", "token": "t"}]) as client:
    try:
        client.use_model("c")
    except zc.ConfigurationError as error:
        print(error)  # Unknown model: c. Configured: a, b
```

模型的切换对下一次 run 生效。同一段对话可以在不同模型之间移动，历史会保留。

### 权限级别

权限级别决定模型想运行 shell 命令时由谁来回答。它只管 shell；文件工具和 MCP 工具不受它约束。

| 级别 | shell 命令…… |
| --- | --- |
| `deny` | ……永远不运行。模型会被告知，改用文件工具继续。 |
| `ask` | ……交给你决定（`ApprovalRequested` 事件）。这是默认值。 |
| `safe` | ……在操作系统沙箱（macOS 上是 Seatbelt，Linux 上是 bubblewrap）里直接运行：只能写工作区和 `/tmp`，没有网络，也碰不到凭据文件。机器没有沙箱（Windows，或没有 `bwrap` 的 Linux）时，确实不会改变任何东西的命令直接运行，其他的交给你决定。 |
| `full` | ……用你自己的权限直接运行，没有沙箱。只用于你信任其 shell 的工作区和模型。旧名 `auto` 仍然可用。 |

如何回答，见[审批与提问](./approvals)。

## 查看加载了什么

```python
async with zc.Client(".") as client:
    report = client.plugins
    print(report.loaded)  # ('shell', 'skills', ..., 'coding', ..., 'ask-user', 'mcp', 'compaction')
    print(report.failures)  # one message per plugin that could not load; never fatal
    print(client.config.workspace, client.config.store)
    print(client.usage)  # what the current session has spent
```

`client.config` 是生效的 `ZettCodeConfig`，它是冻结的：要改 `use_*` 方法之外的设置，请新建 client。

## `@` 资源、用量与体检

终端能回答的另外三个问题也各有方法:`@` 能指向什么、工作区花了多少、模型能不能用。

```python
async with zc.Client(".") as client:
    for mention in client.mentions("cli", limit=5):
        print(mention.token, mention.kind, mention.description)
    ledger = await client.usage_ledger()
    print(ledger.total.total_tokens)
    for check in await client.check_models(timeout=15):
        print(check.model, check.ok, check.detail)
```

[用量与体检](./usage)讲账本、会话统计和模型体检;[会话](./sessions)讲会话里存了什么。

## 还没有 client 时的模型

上面所有方法都需要 client,而 client 至少需要一个模型。新机器上一个都没有,所以这个包也直接编辑配置文件 —— 就是终端
`/config` 编辑的那些 `[[models]]` 条目:

```python
import zettcode.sdk as zc

for model in zc.list_models():  # 文件是新的或没有模型时返回 ()
    print(model.name, model.context_window)

zc.add_model({"model": "gpt-5-mini", "token": "sk-…", "display_model": "Fast"})
zc.update_model("Fast", {"context_window": 200000})  # token 保留
zc.remove_model("Fast")  # 最后一个会被拒绝
```

`add_model` 的第一条自己写,后面的走终端那套编辑器,所以注释和文件其余部分都保留;写进去的内容在返回前会被读回并校验,
解析不过的写入会撤销。函数接受 `path=` 指定非默认的配置文件。文件里有了模型之后,就可以创建 `Client(...)`
(或 `Client(config_path=...)`)。

## 关闭

```python
client = zc.Client(".")
try:
    await client.prompt("hello")
finally:
    await client.aclose()
```

`async with` 会替你做这件事。关闭会停止进行中的 run，释放模型连接和会话锁，并在最后一个 client 关闭时恢复进程的工作目录。重复调用是安全的。关闭之后，所有方法都会抛出 `ClientClosedError`。

::: tip
构造函数如果抛出错误，不会留下任何打开的东西：在错误到达你之前，锁和工作目录已经释放。
:::

## 一个进程只有一个工作区

client 会把进程的工作目录切到它的工作区，因为编码工具按它解析相对路径。**同一个**工作区上的两个 client 没问题。**不同**工作区的 client 会抛出 `WorkspaceConflictError`，直到第一个关闭。

```python
from zettcode.sdk.errors import WorkspaceConflictError

async with zc.Client("/work/a") as a:
    try:
        zc.Client("/work/b")
    except WorkspaceConflictError as error:
        print(error)
```

要同时处理两个工作区，用两个进程：`multiprocessing`、子进程或任务队列。

## 恢复已保存的会话

```python
async with zc.Client(".", resume="3f8a1c20") as client:
    print(client.session.title)
    result = await client.prompt("where were we?")
```

读不出来的 id 会让构造函数抛出 `SessionNotFoundError`。怎么找到 id，见[会话](./sessions)。
