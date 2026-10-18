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
| [`zettcode.sdk.errors`](#zettcode-sdk-errors) | 所有错误 |

## zettcode.sdk

可以直接从包里导入的名字：

```python
from zettcode.sdk import (
    Client, Session, RunStream, prompt, prompt_sync,
    RunResult, Usage, Image,
    TextDelta, ReasoningDelta, ToolStarted, ToolFinished, ApprovalRequested, QuestionAsked, Finished,
    approve_all, approve_commands, deny_all,
    ZettCodeError, ConfigurationError, RunError,
)
```

它们在第一次使用时才加载，所以导入这个包几乎没有开销。`dir(zettcode.sdk)` 能在不加载任何东西的情况下列出它们。

## zettcode.sdk.client

### `prompt`

```python
async def prompt(
    text, /, *,
    workspace=None, config=None, config_path=None, models=None,
    model=None, effort=None, permission=None, resume=None,
    images=(), mentions=False, on_approval=None, on_question=None, on_event=None, timeout=None,
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
        workspace=None, *,
        config=None, config_path=None, models=None,
        model=None, effort=None, permission=None, resume=None,
        **settings,
    ) -> None: ...
```

某个工作区的 agent。是一个异步上下文管理器。见 [Client 与配置](./client)。

| 抛出 | 何时 |
| --- | --- |
| `ConfigurationError` | 配置，或从中选出的模型、推理强度、权限不可用。 |
| `WorkspaceConflictError` | 另一个已打开的 client 在不同的目录里工作。 |
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
| `permissions` | `tuple[str, ...]` | `("deny", "ask", "safe", "auto")`。 |
| `usage` | `Usage` | 当前会话已花的用量。 |
| `plugins` | `PluginReport` | 已加载的插件，以及失败的。 |

#### 方法

| 方法 | 返回 | 作用 |
| --- | --- | --- |
| `prompt(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, raw, keep_events)` | `RunStream` | 在当前会话上发送 prompt。await 它得到 `RunResult`；迭代它得到事件。 |
| `stream(...)` | `RunStream` | 与 `prompt` 是同一个方法。 |
| `run(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, keep_events)` | `RunResult`（可 await） | 把 `await client.prompt(...)` 写成调用。没有 `raw`。 |
| `use_model(name)` | `ModelInfo` | 选择模型；接受名字或 `ModelInfo`。 |
| `use_effort(name)` | `str` | 选择推理级别。 |
| `use_permission(name)` | `str` | 选择权限级别；从下一条 shell 命令起生效。 |
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

### `PluginReport`

冻结的 dataclass：`loaded: tuple[str, ...]`、`failures: tuple[str, ...]`。

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
| `path` | `Path` | 对话保存的文件。 |
| `current` | `bool` | 下一次 run 是否无需切换就用它。 |

#### 运行

| 方法 | 返回 |
| --- | --- |
| `prompt(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, raw, keep_events)` | `RunStream` |
| `stream(...)` | `RunStream`（同一个方法） |
| `await run(prompt, *, images, mentions, on_approval, on_question, on_event, timeout, keep_events)` | `RunResult` |
| `await ask(question, *, on_event=None, timeout=None)` | `str` |
| `steer(message)` | `bool` |
| `await resumable()` | `ResumeInfo \| None` |
| `resume_stream(*, on_approval, on_question, on_event, timeout, raw, keep_events)` | `RunStream` |
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
| `ToolStarted` | `call_id`、`name`、`arguments` |
| `ToolFinished` | `call_id`、`name`、`output`、`ok`、`skipped=False` |
| `ApprovalRequested` | `call_id`、`command`、`timeout_seconds=None`、`remember_supported=False` |
| `QuestionAsked` | `call_id`、`question`、`options=()`、`allow_multiple=False` |
| `UsageUpdated` | `usage` |
| `CompactionStarted` | — |
| `CompactionFinished` | `applied`、`compaction=None` |
| `ModelStopped` | `reason`、`message=None` |
| `Steered` | `text` |
| `Notice` | `text` |
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

### `ContextReport` 和 `ContextShare`

`ContextReport(window, used, measured_by, shares=(), partial=False, from_provider=False)`，带属性 `free` 和 `fraction`。`ContextShare(name, tokens, items=0)`。

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
