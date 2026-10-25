---
title: API 参考
---

# API 参考

SDK 的每一个公开名字，按模块分组。签名取自已发布的包；说明会指向在上下文里解释其行为的页面。

包本身导出常用的名字，从 `zettcode.sdk` 导入。其余都在子模块里，导入同样轻量。

| 模块 | 内容 |
| --- | --- |
| [`zettcode.sdk`](#zettcode-sdk) | `Client`、`Session`、`RunStream`、`prompt`、`prompt_sync`、`RunResult`、`Usage`、`Image`、常用事件和处理函数、三个错误 |
| [`zettcode.sdk.client`](#zettcode-sdk-client) | `Client`、`Sessions`、`PluginReport`、`prompt`、`prompt_sync` |
| [`zettcode.sdk.session`](#zettcode-sdk-session) | `Session`、`RunStream` |
| [`zettcode.sdk.events`](#zettcode-sdk-events) | 所有事件、`AnyEvent` |
| [`zettcode.sdk.types`](#zettcode-sdk-types) | 方法返回的值 |
| [`zettcode.sdk.handlers`](#zettcode-sdk-handlers) | 审批规则与处理函数类型 |
| [`zettcode.sdk.models`](#zettcode-sdk-models) | `list_models`、`add_model`、`update_model`、`remove_model` |
| [`zettcode.sdk.errors`](#zettcode-sdk-errors) | 所有错误 |

## zettcode.sdk

可以直接从包里导入的名字：

```python
from zettcode.sdk import (
    Client,
    Session,
    RunStream,
    prompt,
    prompt_sync,
    RunResult,
    Usage,
    Image,
    TextDelta,
    ReasoningDelta,
    ToolStarted,
    ToolFinished,
    ServerToolStarted,
    ServerToolFinished,
    ApprovalRequested,
    QuestionAsked,
    Finished,
    approve_all,
    approve_commands,
    deny_all,
    add_model,
    list_models,
    update_model,
    remove_model,
    ZettCodeError,
    ConfigurationError,
    RunError,
)
```

它们在第一次使用时才加载，所以导入这个包几乎没有开销。`dir(zettcode.sdk)` 能在不加载任何东西的情况下列出它们。

## zettcode.sdk.client

### `prompt`

```python
async def prompt(
    text,
    /,
    *,
    workspace=None,
    config=None,
    config_path=None,
    models=None,
    model=None,
    effort=None,
    permission=None,
    resume=None,
    images=(),
    mentions=False,
    on_approval=None,
    on_question=None,
    on_event=None,
    timeout=None,
    **settings,
) -> RunResult: ...
```

创建 client、运行一次请求、关闭 client，并返回结果。参数是 `Client` 和 `Client.run` 的并集。见[运行 Prompt](./running#一次性调用)。

### `prompt_sync`

```python
def prompt_sync(text, /, **options) -> RunResult: ...
```

`prompt` 的阻塞形式，给非异步代码用。在正在运行的事件循环里调用会抛出 `RuntimeError`。

### `Client`

```python
class Client:
    def __init__(
        self,
        workspace=None,
        *,
        config=None,
        config_path=None,
        models=None,
        model=None,
        effort=None,
        permission=None,
        resume=None,
        **settings,
    ) -> None: ...
```

某个工作区的 agent。是一个异步上下文管理器。配置的每个字段都是它自己的具名参数并带类型（`store=`、`max_iterations=`、`sessions_enabled=` …… 见[设置](./client#设置)）；不是设置的名字会直接报 `TypeError`。

| 抛出 | 何时 |
| --- | --- |
| `ConfigurationError` | 配置，或从中选出的模型、推理强度、权限不可用。 |
| `WorkspaceConflictError` | 另一个已打开的 client 在不同的目录里工作。 |
| `SendError` | `send` 没能找到任何人;`reason` 说明原因。 |
| `SessionNotFoundError` | `resume` 指向的会话读不出来。 |

#### 属性

| 属性 | 类型 | 含义 |
| --- | --- | --- |
| `workspace` | `Path` | 解析后的工作区目录。 |
| `config` | `ZettCodeConfig` | 生效的配置。 |
| `closed` | `bool` | `aclose()` 是否已运行。 |
| `session` | `Session` | 当前对话。 |
| `sessions` | `Sessions` | 已保存的对话。 |
| `models` | `tuple[ModelInfo, ...]` | 已配置的模型；当前的那个有标记。 |
| `model` | `ModelInfo` | 当前模型。 |
| `effort` | `str` | 下一次 run 使用的推理级别。 |
| `efforts` | `tuple[str, ...]` | 当前模型接受的级别。 |
| `permission` | `str` | shell 权限级别。 |
| `permissions` | `tuple[str, ...]` | `("deny", "ask", "safe", "full")`。 |
| `harness` | `bool` | just-in-time harness 是否开启。 |
| `usage` | `Usage` | 当前会话已花的用量。 |
| `plugins` | `PluginReport` | 已加载的插件，以及失败的。 |
| `self_compaction` | `bool` | 模型是否可以自己压缩这个会话。 |
| `self_compaction_choice` | `bool \| None` | 这个会话自己的选择，`None` 表示跟随配置。 |

#### 方法

| 方法 | 返回 | 作用 |
| --- | --- | --- |
| `prompt(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, raw, keep_events, defer_answers)` | `RunStream` | 在当前会话上发送 prompt。await 它得到 `RunResult`；迭代它得到事件。 |
| `stream(...)` | `RunStream` | 与 `prompt` 是同一个方法。 |
| `run(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, keep_events)` | `RunResult`（可 await） | 把 `await client.prompt(...)` 写成调用。没有 `raw`。 |
| `use_model(name)` | `ModelInfo` | 选择模型；接受名字或 `ModelInfo`。名字先当显示名找，找不到再当模型 id 找；两者都必须只指向一个模型（否则抛 `ConfigurationError`）。 |
| `config_file` | `Path` | 模型从哪个配置文件读、写到哪个文件。 |
| `model_entries()` | `tuple[tuple[ModelInfo, Mapping], ...]` | 文件里列出的每个模型及文件为它写的键（按文件顺序）。 |
| `add_model(entry)` | `ModelInfo` | 把模型加到文件和本 client；正在用的模型不变。 |
| `update_model(which, changes)` | `ModelInfo` | 按名字或在 `model_entries()` 里的位置修改模型；值为 `None` 表示删除这个键。 |
| `remove_model(which)` | `ModelInfo` | 删除模型，返回之后正在用的模型。最后一个模型不能删。 |
| `use_effort(name)` | `str` | 选择推理级别。 |
| `use_compact_percent(percent)` | `tuple[ModelInfo, str \| None]` | 从下一次请求起改变压缩点(占窗口的比例,大于 0、至多 100),并改写配置文件。第二个值说明文件为什么没有写入,写入了就是 `None`。 |
| `use_permission(name, *, remember=True)` | `str` | 选择权限级别；从下一条 shell 命令起生效。`remember=False` 不改动会话记住的级别，用于只覆盖这一次运行的选择。 |
| `mentions(query="", *, limit=50)` | `tuple[MentionInfo, ...]` | 匹配查询的 `@` 资源，用于补全菜单。开启 `sessions_enabled=True` 时，正在运行的其他会话排在最前，和终端一致。 |
| `await join_sessions(on_message)` | `bool` | 加入会话 broker，让其他 ZettCode 会话找得到它、给它发消息。`on_message` 收到每条 `IncomingMessage` 并返回 `Receipt`；返回 `False` 表示该 client 未开启会话功能。 |
| `await send(to, text)` | `Delivered` | 按 handle 或 id 给另一个会话发消息，内容视为读者本人所写；需要先 `join_sessions`。没有人能收到时抛出 `zettcode.sdk.errors.SendError`(`reason` 说明原因)。 |
| `relay(message, *, on_approval, on_question, on_event, timeout, raw, keep_events, defer_answers)` | `RunStream` | 为另一个会话发来的消息跑一轮，模型读到的内容带有发送者信息。 |
| `await usage_ledger()` | `WorkspaceUsage` | 工作区每个已存会话花的用量，按会话、模型和天。 |
| `await session_stats(ids=None)` | `tuple[SessionStatsInfo, ...]` | 若干会话在存储里的统计；不传 id 就是当前会话。 |
| `self_compaction_default` | `bool` | 没做过选择的会话会怎样（`[compaction] self`）。 |
| `use_self_compaction_default(enabled)` | `Path` | 把这个默认值写进配置文件并立即生效；文件不存在或无法编辑时抛 `ConfigurationError`。 |
| `use_self_compaction(choice)` | `bool` | 允许模型自己压缩这个会话（`True`）、停掉（`False`），或跟随默认值（`None`）。 |
| `await check_models(*, timeout=30)` | `tuple[ModelCheck, ...]` | 对每个配置的模型各问一个短问题，和 `zettcode doctor` 一致。 |
| `aclose()` | — | 停止进行中的 run 并释放一切。重复调用是安全的。 |

`use_model`、`use_effort` 和 `use_permission` 在选择不存在时抛出 `ConfigurationError`，消息里列出有效的选项。

### `Sessions`

即 `client.sessions`。

| 方法 | 返回 | 作用 |
| --- | --- | --- |
| `await list(*, limit=20)` | `list[SessionInfo]` | 已保存的会话，最近活跃的在前。 |
| `new()` | `Session` | 开始一段空对话并设为当前。 |
| `await open(session_id)` | `Session` | 继续一段已保存的对话并设为当前。 |
| `await latest()` | `Session \| None` | 继续最近活跃的那段。 |
| `await read(session_id)` | `StoredSession` | 读取一段已保存的对话但不把它设为当前：`open` 里昂贵的那一半，可以在 run 进行时调用。 |
| `read_blocking(session_id)` | `StoredSession` | 同上，在调用线程里执行，给已经在工作线程里的代码用。 |
| `install(stored)` | `Session` | 把 `StoredSession` 设为当前：`open` 里便宜的那一半。run 进行中抛 `SessionBusyError`。 |

`StoredSession(id, title, model, usage, records)`：`records` 是解析后的文件，给自己绘制对话的前端用；它的类型属于 engine，请不要依赖它的结构。

### `PluginReport`

冻结的 dataclass：`loaded: tuple[str, ...]`、`failures: tuple[str, ...]`。

## zettcode.sdk.models

配置文件里的模型,用于在还没有 client 时把一台机器配好。见[还没有 client 时的模型](./client#还没有-client-时的模型)。

```python
def list_models(path=None) -> tuple[ModelInfo, ...]: ...
def add_model(entry, *, path=None) -> tuple[ModelInfo, ...]: ...
def update_model(name, changes, *, path=None) -> tuple[ModelInfo, ...]: ...
def remove_model(name, *, path=None) -> tuple[ModelInfo, ...]: ...
```

`entry` 和 `changes` 用文件里的键(`model`、`token`、`display_model`、`base_url`、`anthropic`、`responses_api`、
`chat`、`multimodal`、`temperature`、`context_window`、`compact_percent`、`reasoning_efforts`)。`path` 默认是 `$ZETTCODE_CONFIG` 或
`~/.zettcode/config.toml`。每次调用返回整个列表,没有模型被标为 active;读不回来的文件会被拒绝;最后一个模型不能删。`changes` 里值为 `None` 的键会从条目里删掉:`{"temperature": None}` 回到提供商自己的默认值,`{"anthropic": None, "chat": True}` 把模型改成 chat completions,而不会留下 `anthropic = false`。

## zettcode.sdk.session

### `Session`

一段已保存对话的句柄。从 `client.session`、`client.sessions` 或 `Session.fork()` 获得。

#### 属性

| 属性 | 类型 | 含义 |
| --- | --- | --- |
| `id` | `str` | 会话的身份。 |
| `title` | `str \| None` | 它的名字，没有时为 `None`。 |
| `usage` | `Usage` | 这个会话累计花的用量。 |
| `locked` | `bool` | 是否有别的进程打开着它。 |
| `retake()` | `bool` | 再次尝试拿下别的进程曾占用的对话的锁；本 client 持有锁时返回 `True`。 |
| `tasks()` | `tuple[TaskInfo, ...]` | 模型为这段会话维护的计划；`TaskInfo(status, content)`，`status` 为 `pending`、`in_progress` 或 `completed`。 |
| `path` | `Path` | 对话保存的文件。 |
| `current` | `bool` | 下一次 run 是否无需切换就用它。 |

#### 运行

| 方法 | 返回 |
| --- | --- |
| `prompt(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, raw, keep_events, defer_answers)` | `RunStream` |
| `stream(...)` | `RunStream`（同一个方法） |
| `await run(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, keep_events)` | `RunResult` |
| `await ask(question, *, on_event=None, timeout=None)` | `str` |
| `ask_stream(question, *, on_event=None, timeout=None)` | `RunStream` |
| `steer(prompt, *, images=(), mentions=False)` | `str \| None` |
| `await resumable()` | `ResumeInfo \| None` |
| `resume_stream(*, on_approval, on_question, on_event, timeout, raw, keep_events, defer_answers)` | `RunStream` |
| `await resume(*, on_approval, on_question, on_event, timeout)` | `RunResult` |

`prompt` 在调用处抛出：`ValueError`（空 prompt、错误的 `timeout`）、`TypeError`（某一部分不是文本或 `Image`）、`ConfigurationError`（给读不了图的模型发图片）、`SessionBusyError`、`ClientClosedError`。await 或迭代 run 时抛出 `RunError`、`RunTimeoutError`、`SessionLockedError`，以及处理函数抛出的任何东西。

#### 操作对话

| 方法 | 返回 | 抛出 |
| --- | --- | --- |
| `await history()` | `list[Message]` | `SessionNotFoundError` |
| `await rename(title)` | `str` | `ValueError`、`SessionLockedError`、`SessionBusyError` |
| `await name_it()` | `str \| None` | — |
| `await fork()` | `Session` | `SessionNotFoundError`、`SessionBusyError` |
| `await export(path=None)` | `Path` | 没有任何已保存内容时抛 `ValueError` |
| `await context()` | `ContextReport \| None` | — |
| `await compact()` | `Compaction \| None` | `NothingToDoError`、`SessionLockedError`、`SessionBusyError` |

见[会话](./sessions)。

### `RunStream`

一次 run。由 `prompt`、`stream` 和 `resume_stream` 返回。

| 成员 | 含义 |
| --- | --- |
| `await run` | 取走其余的事件，并返回 `RunResult`。 |
| `async for event in run` | 事件一发生就产出。 |
| `async with run` | 离开代码块时关闭 run。 |
| `await run.aclose()` | 停止 run 并让 client 恢复空闲。重复调用是安全的。 |
| `run.result` | `RunResult`，run 自行结束之前为 `None`。 |

## zettcode.sdk.events

每个事件都是冻结的 dataclass，派生自 `Event(session_id: str)`。

| 类 | `session_id` 之外的字段 |
| --- | --- |
| `TextDelta` | `text` |
| `ReasoningDelta` | `text` |
| `ReasoningStarted` | — |
| `ReasoningFinished` | — |
| `ToolStarted` | `call_id`、`name`、`arguments` |
| `ToolFinished` | `call_id`、`name`、`output`、`ok`、`skipped=False` |
| `ServerToolStarted` | `call_id`、`name`、`arguments` —— 由端点执行的工具，例如联网搜索 |
| `ServerToolFinished` | `call_id`、`name`、`arguments`、`output`、`ok` —— 查询词、结果页面，以及是否成功 |
| `ApprovalRequested` | `call_id`、`command`、`timeout_seconds=None`、`remember_supported=False` |
| `QuestionAsked` | `call_id`、`question`、`options=()`、`allow_multiple=False` |
| `UsageUpdated` | `usage` |
| `CompactionStarted` | — |
| `CompactionDelta` | `text` |
| `CompactionFinished` | `applied`、`compaction=None` |
| `ModelStopped` | `reason`、`message=None` |
| `Steered` | `text` |
| `SteeringFinished` | — |
| `SteeringInterrupted` | `text` |
| `Notice` | `text`, `level` |
| `Finished` | `text` |
| `RawEvent` | `event` |

`AnyEvent` 是它们全部的联合类型。

### `ApprovalRequested`

| 成员 | 含义 |
| --- | --- |
| `approve(*, remember=False)` | 让命令运行。`remember` 仅在 `remember_supported` 时有效。 |
| `deny()` | 拒绝它。 |
| `answered` | 是否已被处理，无论是你还是 run 的处理函数。 |
| `approved` | `True`、`False`，未作答时为 `None`。 |

### `QuestionAsked`

| 成员 | 含义 |
| --- | --- |
| `answer(text)` | 回答它。空答案抛出 `ValueError`。 |
| `decline()` | 告诉模型它被取消了。 |
| `answered` | 是否已被回答或拒答。 |

第一个答案生效。重复同样的答案无害；相反的答案抛出 `ValueError`。见[审批与提问](./approvals#重复作答)。

## zettcode.sdk.types

都是带 `__slots__` 的冻结 dataclass。

### `Usage`

`input_tokens`、`output_tokens`、`cache_read_tokens`、`cache_write_tokens`、`reasoning_tokens`（都是 `int`，默认 `0`）、`seconds: float`、`requests: int`、`context_tokens: int`。

| 成员 | 含义 |
| --- | --- |
| `total_tokens` | 输入加输出。 |
| `cache_hit_rate` | 输入中来自缓存的比例，或 `None`。 |
| `output_rate` | 每秒模型时间生成的 token 数，或 `None`。 |
| `since(earlier)` | `earlier` 之后花的用量；计数不会低于零。 |

### `RunResult`

| 字段 | 类型 |
| --- | --- |
| `text` | `str` |
| `session_id` | `str` |
| `usage` | `Usage` |
| `tools` | `tuple[ToolRecord, ...]` |
| `stop` | `str \| None` |
| `stop_message` | `str \| None` |
| `questions` | `tuple[str, ...]` |
| `events` | `tuple[Event, ...]` |

属性：`ok`（`stop is None`）和 `failed_tools`。

### `ToolRecord`

`id`、`name`、`arguments: dict`、`output: str`、`ok: bool`、`skipped: bool = False`。

### `Image`

`Image(data: bytes, media_type: str)` 和 `Image.from_path(path)`。媒体类型：`image/png`、`image/jpeg`、`image/gif`、`image/webp`。数据为空或类型不对时抛出 `ValueError`。

### `ModelInfo`

`name`、`model`、`context_window: int`、`multimodal: bool`、`efforts: tuple[str, ...]`、`active: bool = False`。

### `SessionInfo`

`id`、`title: str or None`、`created_at: datetime`、`updated_at: datetime`。

### `Message` 和 `ToolCallInfo`

`Message(role, text, tool_calls=(), tool_call_id=None, tool_name=None, ok=True, images=0)`。
`ToolCallInfo(id, name, arguments)`。

### `MentionInfo`

`token`、`kind`、`name`、`description`。

### `IncomingMessage`

`sender_id`、`sender`、`text`、`via`、`hops`。另一个 ZettCode 会话发来的消息:`join_sessions` 交给回调的就是它,`relay` 回答的也是它。`via` 为 `"user"` 表示对方读者亲手所写,`"agent"` 表示对方 agent 所写,`"external"` 表示发消息的不是 ZettCode 会话。

### `Receipt`、`Delivered`

`Receipt(accepted, reason="", disposition="")` 是 `join_sessions` 的回调返回给发送方的:消息是否被收下、不收的原因、以及它的回合是 `"started"`(已开始)还是 `"queued"`(排队中)。`Delivered(to, disposition)` 是 `send` 的返回值:收下消息的会话的 handle,以及同样的 disposition。

### `Totals`

用量账本里一份计数:`requests`、`input_tokens`、`output_tokens`、`cache_read_tokens`、`reasoning_tokens`（都是 `int`），并提供算好的 `total_tokens` 与 `cache_share`（没有输入时为 `None`）。

### `SessionTotals`、`ModelTotals`、`DayTotals`、`WorkspaceUsage`

`SessionTotals(id, title, started, updated, tokens, models, entries)`;`ModelTotals(model, tokens)`;`DayTotals(day, tokens)`。`WorkspaceUsage(sessions, models, days, total)` 就是 `usage_ledger()` 的返回值:会话最近活动的在前,模型用得最多的在前,天从早到晚。

### `SessionStatsInfo`

`id`、`entries`、`requests`、`input_tokens`、`output_tokens`、`cache_read_tokens`、`reasoning_tokens`,并提供算好的 `total_tokens` 与 `cache_share`。终端 `/resume` 面板的一行。

### `ModelCheck`

`model`、`model_id`、`ok`、`seconds`、`detail`、`input_tokens: int | None`、`output_tokens: int | None`。一个模型对 `check_models()` 的回答。

### `ContextReport` 和 `ContextShare`

`ContextReport(window, used, measured_by, shares=(), partial=False, from_provider=False)`，带属性 `free` 和 `fraction`，以及 `measured`（分词器数出的 token 数，`shares` 加起来就是它；`used` 可能是供应商自己的计数）、`estimated`（`shares` 是按每 token 几个字符估的）和方法 `percent(tokens)`（占窗口的百分比）、`share(tokens)`（占 `measured` 的百分比，也就是上下文花在了哪里）。`ContextShare(name, tokens, items=0)`。

### `Compaction` 和 `ResumeInfo`

`Compaction(summary, compressed, kept)`。`ResumeInfo(kind, description)`。

## zettcode.sdk.handlers

| 名字 | 含义 |
| --- | --- |
| `approve_all(request)` | 批准一切。 |
| `deny_all(request)` | 拒绝一切。 |
| `approve_commands(*commands)` | 返回一个处理函数，批准列出的命令，拒绝其余。规则为空白或含 shell 字符时抛出 `ValueError`。 |
| `ApprovalHandler` | `Callable[[ApprovalRequested], bool \| None \| Awaitable[bool \| None]]` |
| `QuestionHandler` | `Callable[[QuestionAsked], str \| None \| Awaitable[str \| None]]` |
| `SHELL_META` | 会让命令无法匹配前缀规则的字符。 |

## zettcode.sdk.errors

继承层次以及各自何时抛出，见[错误与超时](./errors)。

| 类 | 基类 | 额外属性 |
| --- | --- | --- |
| `ZettCodeError` | `Exception` | — |
| `ConfigurationError` | `ZettCodeError`、`ValueError` | — |
| `ClientClosedError` | `ZettCodeError` | — |
| `SessionBusyError` | `ZettCodeError` | — |
| `SessionLockedError` | `ZettCodeError` | — |
| `SessionNotFoundError` | `ZettCodeError`、`LookupError` | — |
| `NothingToDoError` | `ZettCodeError` | — |
| `WorkspaceConflictError` | `ZettCodeError` | — |
| `SendError` | `ZettCodeError` | `reason` |
| `RunError` | `ZettCodeError` | `retryable`、`partial_text` |
| `RunTimeoutError` | `RunError`、`TimeoutError` | `seconds` |

## 类型标注里可能用到的类型

```python
from zettcode.sdk import Client, Session, RunStream, RunResult
from zettcode.sdk.events import AnyEvent
from zettcode.sdk.handlers import ApprovalHandler, QuestionHandler
from zettcode.sdk.types import ModelInfo, SessionInfo, Message, ContextReport
```

包带有 `py.typed` 标记，所以类型检查器会读取这些标注。
