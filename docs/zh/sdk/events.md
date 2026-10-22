---
title: 事件流
---

# 事件流

迭代一个 run 时，事件会在发生的同时被产出。本页列出每种事件，演示如何匹配它们，并给出程序处理事件流时常见的模式：打印进度、收集输出、显示加载指示、记录日志。

## 事件的形状

每个事件都是带 `session_id` 的冻结 dataclass。你按类匹配，读取的字段始终存在。没有需要比较的 `type` 字符串，也没有时有时无的字段。

```python
import zettcode.sdk as zc

async with client.prompt("fix the failing test") as run:
    async for event in run:
        match event:
            case zc.TextDelta(text=text):
                print(text, end="", flush=True)
            case zc.ToolStarted(name=name, arguments=arguments):
                print(f"\n→ {name} {arguments}")
            case zc.ToolFinished(name=name, ok=False, output=output):
                print(f"✗ {name}: {output[:200]}")
            case zc.Finished():
                print()
```

`match` 需要 Python 3.10，这也是项目支持的最低版本。喜欢的话，用 `isinstance` 效果一样。

## 事件列表

前七个从 `zettcode.sdk` 导出，其余在 `zettcode.sdk.events` 中。

| 事件 | 字段 | 何时产生 |
| --- | --- | --- |
| `TextDelta` | `text` | 回答的一小段。拼起来就是回答。 |
| `ReasoningDelta` | `text` | 模型推理的一小段，仅限会报告推理的供应商。 |
| `ToolStarted` | `call_id`、`name`、`arguments` | 模型调用了一个工具，它正在开始。 |
| `ToolFinished` | `call_id`、`name`、`output`、`ok`、`skipped` | 工具结束了：成功、失败，或根本没有运行。 |
| `ApprovalRequested` | `call_id`、`command`、`timeout_seconds`、`remember_supported` | 一条 shell 命令在等你决定。 |
| `QuestionAsked` | `call_id`、`question`、`options`、`allow_multiple` | 模型问了你一个问题。 |
| `Finished` | `text` | 最终回答完整了。 |
| `UsageUpdated` | `usage` | 一次模型调用之后，会话的 token 累计。 |
| `CompactionStarted` | — | 对话正在被总结。 |
| `CompactionFinished` | `applied`、`compaction` | 一次压缩结束。 |
| `ModelStopped` | `reason`、`message` | 某一步因为非正常结束的原因停止。 |
| `Steered` | `text` | 用 `steer` 发出的消息到达了请求。 |
| `Notice` | `text`, `level` | 不属于回答的消息，比如某个 MCP 服务器正在启动，或连不上。`level` 为 `"info"` 表示进度，`"warn"` 表示你可能需要处理的事。 |
| `RawEvent` | `event` | 底层的 `zett-agent` 事件。仅在 `raw=True` 时产生。 |

`AnyEvent` 是它们的联合类型，用于类型标注：

```python
from zettcode.sdk.events import AnyEvent


def log(event: AnyEvent) -> None:
    print(type(event).__name__)
```

### 文本与推理

```python
answer = []
async for event in run:
    if isinstance(event, zc.TextDelta):
        answer.append(event.text)
print("".join(answer))
```

`result.text` 已经有这份内容，所以只有在要实时显示时才需要自己拼接。空的增量从不会被产出。

### 工具

`ToolStarted` 和 `ToolFinished` 通过 `call_id` 配对。模型在一步里发起多个调用时，你会先收到每个 `ToolStarted`，再收到每个 `ToolFinished`，所以按 id 匹配，不要假定顺序。

```python
running: dict[str, str] = {}

async for event in run:
    if isinstance(event, zc.ToolStarted):
        running[event.call_id] = event.name
        print(f"⠋ {event.name}")
    elif isinstance(event, zc.ToolFinished):
        running.pop(event.call_id, None)
        mark = "✓" if event.ok else "–" if event.skipped else "✗"
        print(f"{mark} {event.name}")
```

失败的调用和没有运行的调用，`ok` 都为 false；`skipped` 只在后者为 true，即转向在调用开始前接管了流程。`output` 是工具返回的内容或失败文本。

模型编造出来的工具，会表现为一个带说明性 `output` 的失败调用，而不是异常。

### 审批与提问

这两种事件需要你的程序回应。agent 停在工具调用内部，直到它们被处理。详见[审批与提问](./approvals)；简而言之：

```python
async for event in run:
    match event:
        case zc.ApprovalRequested() as ask:
            ask.approve() if ask.command.startswith("pytest") else ask.deny()
        case zc.QuestionAsked() as ask:
            ask.answer("yes") if ask.options else ask.decline()
```

请在向流要下一个事件之前作答。到那时仍未作答的请求会被拒绝或拒答。

### 用量

`UsageUpdated.usage` 是*会话*的累计，不是这次 run 的。要得到增量，就减去 run 之前取的读数，或者在最后读 `result.usage`。

```python
from zettcode.sdk.events import UsageUpdated

async for event in run:
    if isinstance(event, UsageUpdated):
        print(f"context {event.usage.context_tokens} tokens, {event.usage.requests} requests")
```

### 压缩

上下文变满时，agent 会在 run 中途总结较早的消息。

```python
from zettcode.sdk.events import CompactionFinished, CompactionStarted

async for event in run:
    match event:
        case CompactionStarted():
            print("summarizing…")
        case CompactionFinished(applied=True, compaction=done):
            print(f"folded {done.compressed} messages; kept {done.kept}")
        case CompactionFinished(applied=False):
            print("nothing worth folding")
```

### 停止

`ModelStopped.reason` 是 `refusal`、`max_output`、`context_full`、`paused`、`interrupted`、`other` 之一。同样的值最终出现在 `result.stop`。能继续的地方 run 会继续，所以只有需要立刻采取行动时才在流里响应。

## 常见模式

### 打印进度和摘要

```python
async def show(client, prompt):
    tools = 0
    async with client.prompt(prompt) as run:
        async for event in run:
            match event:
                case zc.TextDelta(text=text):
                    print(text, end="", flush=True)
                case zc.ToolStarted():
                    tools += 1
    print(f"\n\n{tools} tool calls, {run.result.usage.total_tokens} tokens")
    return run.result
```

### 用 `on_event` 分发给多个监听者

如果循环不是观察事件的合适位置，就给 run 一个回调。回调能看到每个事件，包括由处理函数作答的那些。

```python
counts: dict[str, int] = {}


def count(event):
    counts[type(event).__name__] = counts.get(type(event).__name__, 0) + 1


result = await client.prompt("...", on_event=count)
print(counts)  # {'TextDelta': 41, 'ToolStarted': 3, 'ToolFinished': 3, 'Finished': 1, ...}
```

### 保留整个事件流

```python
result = await client.prompt("...", keep_events=True)
tool_events = [e for e in result.events if isinstance(e, zc.ToolStarted)]
```

除非你要求，`result.events` 是空的，因为较长的 run 会产生大量增量。

### 首个 token 的延迟

```python
import time

start = time.perf_counter()
first = None
async with client.prompt("...") as run:
    async for event in run:
        if isinstance(event, zc.TextDelta) and first is None:
            first = time.perf_counter() - start
print(f"first token after {first:.2f}s")
```

### 通过网络发送事件

事件是朴素的冻结 dataclass，可以用 `dataclasses.fields` 读取。可作答的事件还带有一个私有的回复槽（`_reply`），它不是数据；请略去所有以下划线开头的字段。`RawEvent.event` 是 `zett-agent` 的对象，跳过它或自行转换。

```python
import dataclasses, json
from zettcode.sdk.events import RawEvent


def record(event) -> dict:
    fields = {f.name: getattr(event, f.name) for f in dataclasses.fields(event) if not f.name.startswith("_")}
    return {"type": type(event).__name__, **fields}


async for event in run:
    if not isinstance(event, RawEvent):
        await websocket.send(json.dumps(record(event), default=str))
```

`default=str` 会处理嵌套在 `UsageUpdated` 和 `CompactionFinished` 里的 `Usage` 和 `Compaction`；如果想把它们保留为对象，对它们用 `dataclasses.asdict`。

## 保证

- **单次调用内的顺序。** `ToolStarted` 先于对应的 `ToolFinished`。`Finished` 出现在回答的最后一个 `TextDelta` 之后。
- **畸形的东西不会到你这里。** 扩展发出的残缺自定义事件会被丢弃而不是抛出，因为坏事件不应让一个进行中的请求失败。
- **事件流会结束。** 循环正常结束时，`run.result` 已设置。run 失败时，循环会抛出异常（见[错误与超时](./errors)），`run.result` 保持 `None`。
- **每个事件都带会话 id**，所以一个处理函数可以服务多个会话。
