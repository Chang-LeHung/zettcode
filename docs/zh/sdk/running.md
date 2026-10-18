---
title: 运行 Prompt
---

# 运行 Prompt

本页讲发出 prompt 并拿到结果：三种调用方式、每个参数、结果里有什么，以及各种变体——图片、`@` 引用、旁路提问、转向（steer）和一次性调用。

## 三种调用方式

它们都在 client 的当前会话上发送 prompt，区别在于你拿回来的是什么。

```python
import zettcode.sdk as zc

async with zc.Client(".", permission="safe") as client:
    # 1. Wait for the end and get the result.
    result = await client.prompt("explain this module")

    # 2. Watch it happen.
    async with client.prompt("explain this module") as run:
        async for event in run:
            ...
    result = run.result

    # 3. The same as 1, spelled as a call.
    result = await client.run("explain this module")
```

`client.prompt(...)` 立即返回一个 `RunStream`，此时什么都还没发送。请求在你第一次 await 或迭代它时才开始。这就是同一个调用既能当结果用、又能当事件流用的原因。

`client.stream(...)` 与 `prompt` 是同一个方法，只是名字直接说明你的用意。哪个读起来顺就用哪个，它们不会有差别。

`Session` 上也有同样三个（`session.prompt`、`session.stream`、`session.run`），模块级的 `zc.prompt()` 则为一次请求走完整个生命周期。

## 参数

`Client.prompt`、`Session.prompt` 和 `Session.run` 接受相同的参数。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `prompt` | 必填 | 文本，或按阅读顺序排列的文本与 `Image` 的列表。 |
| `images` | `()` | 放在 prompt 之后的图片。 |
| `mentions` | `False` | 像终端一样解析 `@skill` 和 `@path` 引用。 |
| `on_approval` | `None` | 决定每条需要审批的 shell 命令。见[审批与提问](./approvals)。 |
| `on_question` | `None` | 回答模型提出的每个问题。 |
| `on_event` | `None` | 每个事件发生时被调用。可以是函数或协程函数。 |
| `timeout` | `None` | 整个 run 允许的秒数。 |
| `raw` | `False` | 额外产出底层 `zett-agent` 事件，作为 `RawEvent`。（仅 `prompt` 和 `stream`。） |
| `keep_events` | `False` | 把所有事件保存在 `result.events` 里。 |

空 prompt、不是正数的 `timeout`，或列表里混入了文本和图片之外的东西，会**在调用处**抛出 `ValueError` 或 `TypeError`，什么都不会发出去。

```python
try:
    client.prompt("   ")
except ValueError as error:
    print(error)       # The prompt is empty
```

## 结果

```python
result = await client.prompt("run the tests and fix what fails", on_approval=zc.approve_commands("pytest"))
```

| 属性 | 含义 |
| --- | --- |
| `result.text` | 模型的最终回答。如果没有最终回答，则是流式收到的文本。 |
| `result.session_id` | run 所属的会话。之后可作为 `resume=` 传入。 |
| `result.usage` | 仅这一次 run 的 `Usage`。 |
| `result.tools` | 一组 `ToolRecord`：每次调用，按顺序。 |
| `result.failed_tools` | 没有成功的那些记录。 |
| `result.stop` | 模型正常结束时为 `None`，否则是没结束的原因。 |
| `result.stop_message` | 供应商对停止原因的说明（如果给了）。 |
| `result.ok` | 恰好在 `stop` 为 `None` 时为 `True`。 |
| `result.questions` | 模型提出的问题，按顺序。 |
| `result.events` | `keep_events=True` 时是所有事件，否则为空。 |

### 读取工具调用

```python
for tool in result.tools:
    status = "ok" if tool.ok else "skipped" if tool.skipped else "failed"
    print(f"{tool.name:<12} {status:<8} {tool.arguments}")

if result.failed_tools:
    print("Some tools failed:", [tool.name for tool in result.failed_tools])
```

`ToolRecord` 带有 `id`、`name`、`arguments`、`output`（工具返回的内容或失败文本）、`ok` 和 `skipped`。

### 没有顺利结束的 run

拒绝或被截断是一个带 `stop` 的*结果*，不是异常。模型回答了，只是没有按你希望的方式结束。

```python
result = await client.prompt("...")
if not result.ok:
    match result.stop:
        case "refusal":
            print("The model declined:", result.stop_message)
        case "max_output":
            result = await client.prompt("continue")
        case "context_full":
            await client.session.compact()
```

取值有 `refusal`、`max_output`、`context_full`、`paused`、`interrupted` 和 `other`。来自供应商或网络的错误不同：它们会抛出 `RunError`。见[错误与超时](./errors)。

### 用量

`result.usage` 是*这一次 run* 花的。`client.usage` 和 `session.usage` 是整个会话的累计。

```python
before = client.usage
result = await client.prompt("...")

print(result.usage.total_tokens)         # this run
print(client.usage.total_tokens)         # the session so far
print(f"{result.usage.cache_hit_rate:.0%} of the input came from cache")
print(f"{result.usage.output_rate:.0f} tokens/s")
```

| `Usage` 字段 | 含义 |
| --- | --- |
| `input_tokens` | 发给模型的全部内容，**含**缓存读写。 |
| `output_tokens` | 生成的全部内容，**含**推理。 |
| `cache_read_tokens`、`cache_write_tokens` | 输入中属于缓存的部分。 |
| `reasoning_tokens` | 输出中属于推理的部分。 |
| `seconds` | 模型调用内部花的墙钟时间。 |
| `requests` | 发起了多少次模型调用。 |
| `context_tokens` | 最近一次调用时上下文有多满。 |
| `total_tokens` | `input_tokens + output_tokens`；没有重复计算。 |
| `cache_hit_rate` | 输入中来自缓存的比例，没有输入时为 `None`。 |
| `output_rate` | 每秒模型时间生成的 token 数，或 `None`。 |

`usage.since(earlier)` 把两次读数相减，结果不会低于零。

## 图片

prompt 可以按阅读顺序混合文本和图片。模型必须是 `multimodal`。

```python
png = zc.Image.from_path("screenshot.png")

result = await client.prompt(["What is wrong with this layout? ", png])
result = await client.prompt("Compare these", images=[zc.Image.from_path("a.png"), zc.Image.from_path("b.webp")])
```

`Image(data, media_type)` 接收编码后的字节，类型必须是 `image/png`、`image/jpeg`、`image/gif` 或 `image/webp`。`Image.from_path` 根据扩展名确定类型。图片有问题时，构造时就抛出 `ValueError`。把图片发给不能读图的模型，会在发出任何东西之前抛出 `ConfigurationError`，消息里指明是哪个模型。

图片在已保存的对话里只记录数量（`Message.images`），字节不保留在历史中。

## 引用（mentions）

终端的输入框会解析 `@skill` 和 `@path` 引用。SDK 里默认把它们当普通文本，因为 `@` 也出现在邮箱地址和装饰器里。想要终端的行为时打开：

```python
result = await client.prompt("Use @code-review on @src/parser.py", mentions=True)
```

引用按终端的方式解析，所指内容的说明会加在 prompt 之后。保存的历史里仍是你输入的原文（用户消息的 `Message.text` 是你发的文本，而不是那些附加的说明）。

## 旁路提问

`session.ask()` 让模型在看到整段对话的前提下回答一个问题，但不往对话里添加任何东西——问题和回答都不会进入下一次 run 构造的历史。它是只读的。

```python
await client.prompt("refactor the parser")
answer = await client.session.ask("which functions did you touch?")
print(answer)

await client.prompt("now add tests")        # the model never saw the side question
```

它返回回答文本，问题为空时抛出 `ValueError`。和任何 run 一样，它要求 client 此刻空闲。

## 对运行中的 run 转向

向进行中的请求发一条消息。agent 会放下手头的事，在下一个边界把这条消息考虑进去。

```python
async with client.prompt("investigate the failing test") as run:
    steered = False
    async for event in run:
        if isinstance(event, zc.ToolStarted) and event.name == "bash" and not steered:
            steered = client.session.steer("don't run commands; read the code instead")
```

`steer` 在有运行中的请求接受了消息时返回 `True`；没有任何东西在运行、client 已关闭或消息为空白时返回 `False`。不会为以后排队。流里的 `Steered` 事件确认请求收下了它。

`steer` 是普通方法，不是协程，所以可以在上面的事件循环里、回调里，或者持有 client 的另一个任务里调用。

## 提前停止

离开循环，run 就被关闭，前提是你用了 `async with`。

```python
async with client.prompt("write a long essay") as run:
    async for event in run:
        if isinstance(event, zc.TextDelta):
            print(event.text, end="")
            if "TODO" in event.text:
                break                    # the run is closed on leaving the block
```

`break` 之后，client 可以接着发下一个 prompt。run 已经加入对话的内容会保留。

::: warning
被你中途停掉的那个 run 的 prompt 会留在对话里，不管有没有回答完。模型在下一个请求里会再次看到它，可能顺带把它也回答了：取消“写四十条建议”之后再发“说 alive”，第二个回复可能会接着写那些建议。如果不想要这样，就为下一个 prompt 开一个[新会话](./sessions#找到会话)，或者明确告诉模型之前那个请求作废。
:::

不用 `async with` 的话，调用 `await run.aclose()`。既没结束也没关闭的 run 会让 client 一直处于忙碌，直到它被垃圾回收。

## 迭代与 await 结合

可以先迭代 run 的一部分，再 await 剩下的：

```python
async with client.prompt("explain the design") as run:
    async for event in run:
        if isinstance(event, zc.ToolStarted):
            break                         # I have seen enough to know it is working
    result = await run                    # take the remainder
```

对一个已经结束并读完的 run 再 await 是错误，而不是卡住。迭代一个已结束的 run 会立即结束。

## 用回调代替循环

`on_event` 用于不占用循环的观察，比如记日志或更新进度显示。它能看到每个事件，包括由处理函数作答的那些。

```python
events = []

async def record(event):
    events.append(event)
    await send_to_dashboard(event)

result = await client.prompt("...", on_event=record)
```

回调如果抛出异常，run 会停止，错误原样到达你的 `await`。

## 一次性调用

`zc.prompt()` 创建 client、运行一次请求，然后关闭一切：

```python
result = await zc.prompt(
    "list the public functions in src/parser.py",
    workspace=".",
    permission="deny",
    timeout=60,
)
```

它接受 `Client` 和 `run` 的参数。要发不止一个 prompt，请保持一个 `Client` 打开，这样对话得以延续，初始化成本也只付一次。

### 在同步代码里

```python
result = zc.prompt_sync("check the parser", workspace=".", permission="safe")
print(result.text)
```

`prompt_sync` 自己运行事件循环。它拒绝在已运行的循环里执行（notebook、异步框架），会抛出 `RuntimeError`；那里请用 `await zc.prompt(...)`。

## 原始事件

想要 SDK 没有建模的内容，用 `raw=True` 启动 run，就会在每组类型化事件之前额外收到底层 `zett-agent` 事件，类型为 `RawEvent`。

```python
from zettcode.sdk.events import RawEvent

async with client.prompt("...", raw=True) as run:
    async for event in run:
        if isinstance(event, RawEvent):
            print(event.event.type)
```

`RawEvent` 和 `AnyEvent` 在 `zettcode.sdk.events` 中。
