---
title: 会话
---

# 会话

会话就是一段已保存的对话。本页讲怎么找到它们、在它们之间切换、读取其中的内容，以及对一段对话的各种操作：重命名、分叉、导出、压缩、度量和恢复。

## 模型

`client.session` 是当前对话。新建的 client 从一段空对话开始。`client.sessions` 是工作区里已保存内容的集合。`Session` 是个轻量句柄：它只持有一个 id，具体工作交给 client 去做。

```python
import zettcode.sdk as zc

async with zc.Client(".") as client:
    session = client.session
    print(session.id, session.title, session.current)
    print(session.path)  # the file the conversation is stored in
```

会话以终端自己的格式写在同一个存储里。在代码里开始的对话可以在终端里用 `/resume` 继续，在终端里开始的也可以在这里继续。

会话在它的第一个请求发出时才写入磁盘。在那之前它只存在于内存里，所以对一个全新的会话调用 `history()` 会抛出 `SessionNotFoundError`。

## 找到会话

```python
async with zc.Client(".") as client:
    for info in await client.sessions.list(limit=10):
        print(info.id[:8], f"{info.updated_at:%Y-%m-%d %H:%M}", info.title or "(untitled)")
```

`list()` 返回 `SessionInfo(id, title, created_at, updated_at)`，最近活跃的在前。`limit` 默认 20，必须是正整数。

| 调用 | 作用 |
| --- | --- |
| `await client.sessions.list(limit=20)` | 列出这个工作区已保存的会话。 |
| `client.sessions.new()` | 开始一段空对话并设为当前。 |
| `await client.sessions.open(id)` | 继续一段已保存的对话并设为当前。 |
| `await client.sessions.latest()` | 继续最近活跃的那段，没有则返回 `None`。 |
| `await client.sessions.history_of(id, *, workspace=None, full=True)` | 按 id 读取任意已存储会话的消息，不会把它设为当前会话，也不会取它的锁。 |
| `client.sessions.stamp(id, *, workspace=None)` | 一个值，已存储会话的文件一变它就变(只需一次 `stat`)，没有文件时为 `None`；轮询它，只在它变了之后才读对话。 |
| `client.sessions.open_elsewhere(id, *, workspace=None)` | 是否有某个进程正打开着这个已存储会话(也就是持有它的锁)；只是一个快照。 |
| `Client(resume=id)` | 让 client 从一段已保存的对话开始。 |

id 不存在、读不出来或会指向存储之外时，`open()` 会抛出 `SessionNotFoundError`。如果配置里仍有该会话上次用的模型，它就在那个模型上继续。

```python
async with zc.Client(".") as client:
    session = await client.sessions.latest()
    if session is None:
        session = client.session  # nothing stored; start fresh
    result = await session.prompt("where did we leave off?")
```

## 在对话之间切换

client 转去别的对话时，句柄依然有效。下一次需要某个会话的调用会让它重新成为当前，带着它自己的历史和用量。

```python
async with zc.Client(".") as client:
    review = client.session
    await review.prompt("review the parser")

    feature = client.sessions.new()
    await feature.prompt("sketch a design for caching")

    await review.prompt("one more point on the parser")  # back to the first
    print(review.usage.total_tokens, feature.usage.total_tokens)
```

run 进行期间切换会被拒绝，抛出 `SessionBusyError`：一个 client 同一时刻只做一件事。

## 读取历史

```python
messages = await client.session.history()
for message in messages:
    print(f"{message.role:>9}: {message.text[:80]!r}")
```

`history()` 返回模型正在使用的消息:如果有压缩摘要则摘要在最前,然后是它之后的内容。`history(full=True)` 则返回当前分支上按写入原样的整段对话:被压缩折叠掉的消息都在,每个摘要作为一条 `summary` 消息出现在压缩发生的位置;客户端重新打开会话时显示的是这一份。它不含系统消息和旁路提问;用户消息显示的是人输入的原文,而不是 `@` 引用附加在后面的说明。读取不需要锁,所以对另一个进程打开着的会话也能用。

| `Message` 字段 | 含义 |
| --- | --- |
| `role` | `user`、`assistant` 或 `tool`;压缩后代替较早消息的那段文字为 `summary`,不是任何人输入的。 |
| `text` | 说了什么。 |
| `tool_calls` | 对 assistant 消息，是一组 `ToolCallInfo(id, name, arguments)`。 |
| `tool_call_id`、`tool_name`、`ok` | 对 tool 消息，是它回应的调用、工具名，以及是否成功。 |
| `images` | 消息带了多少张图片。 |

### 还原 agent 做过什么

```python
for message in await session.history():
    for call in message.tool_calls:
        print("called", call.name, call.arguments)
    if message.role == "tool" and not message.ok:
        print("failed:", message.tool_name, message.text[:120])
```

## 标题

```python
await session.rename("Parser refactor")  # returns the title as stored (trimmed)
title = await session.name_it()  # asks the model, unless it already has one
print(session.title)
```

`rename` 对空白或过长的标题抛出 `ValueError`。`name_it` 不动已有的标题，没有对话可命名时返回 `None`。

## 分叉

`fork()` 把对话的上下文复制到一个新会话并返回它。原会话保持原样，两者互不影响。

```python
base = client.session
await base.prompt("read the project and tell me its structure")

attempt_a = await base.fork()
await attempt_a.prompt("refactor with dataclasses")

attempt_b = await base.fork()
await attempt_b.prompt("refactor with attrs")
```

这是从同一份理解出发尝试两种做法的方式。分叉得到的上下文就是模型手上的那一份，所以已压缩的对话分叉出来也是已压缩的。对空会话分叉会抛出 `SessionNotFoundError`。

## 导出

```python
path = await session.export("reports/refactor.html")
print(path)  # absolute path that was written
```

对话被写成单个 HTML 页面，渲染得和终端里显示的一样，旁边还附上下一轮会发出的请求。不给路径时，文件是工作区里的 `zettcode-<id8>.html`。相对路径从工作目录算起，而 client 打开期间工作目录就是工作区。没有任何已保存内容的会话会抛出 `ValueError`。

## 度量上下文

```python
report = await session.context()
if report is not None:
    print(f"{report.used:,} / {report.window:,} tokens ({report.fraction:.0%}), {report.free:,} free")
    for share in report.shares:
        print(f"  {share.name:<20} {share.tokens:>8,}  ({share.items} items)")
```

`context()` 在第一次回复之前返回 `None`。来源依次是 `System prompt`、`Environment notes`、`Tool schemas`、`User messages`、`Assistant messages`、`Tool output` 和 `Compaction summary`；只显示非空的。

| `ContextReport` 字段 | 含义 |
| --- | --- |
| `window` | 模型能承载的 token 数。 |
| `used` | 下一个请求带的 token 数：供应商给了就用它的计数，否则用分词器的。 |
| `from_provider` | `used` 是否为供应商的计数。 |
| `measured_by` | `shares` 背后的计数器。 |
| `partial` | 为 `True` 表示有一部分尚无法度量，所以 `used` 偏低。 |
| `free`、`fraction` | 派生值：剩余 token 数，以及占用比例。 |

### 窗口满之前压缩

```python
report = await session.context()
if report and report.fraction > 0.7:
    done = await session.compact()
    if done is not None:
        print(f"folded {done.compressed} messages into a summary, kept {done.kept}")
```

`compact()` 立即总结对话较早的部分，不增加一轮。它返回 `Compaction(summary, compressed, kept)`；没有值得折叠的内容时返回 `None`；对话已经压缩到最新消息时抛出 `NothingToDoError`。agent 也会在模型的 `compact_percent` 处自动压缩；手动调用用于想更早压缩的时候。

每个来源的含义，见[上下文窗口](/zh/guide/context)。

## 恢复被中断的请求

请求可能被半路打断：超时、崩溃、断线，或终端里按了 Ctrl-C。对话保留了那之前的一切，SDK 可以从停下的地方接着做。

```python
info = await session.resumable()
if info is not None:
    print(info.kind, "-", info.description)
    result = await session.resume()
```

`resumable()` 只读取，不写入，也不调用模型。对话没有被中断时返回 `None`。`ResumeInfo.kind` 是下列之一：

| 类型 | 含义 |
| --- | --- |
| `call_model` | 历史已就绪，可以做下一次模型调用；不会添加任何东西。 |
| `recover_tools` | 停下时工具正在运行。每个缺失的结果都会补上，写明该工具被中断，可能运行过也可能没有。**工具绝不会自动重跑**，因为没有任何信息说明它的效果是否已经发生。 |
| `retry_response` | 一次回复被故障截断；会要求模型重新开始它。 |
| `continue_response` | 一次回复达到输出上限；会要求模型从停下的地方继续。 |

`resume()` 等待结果；`resume_stream()` 返回一个可迭代的 run，参数 `on_approval`、`on_question`、`on_event`、`timeout`、`keep_events` 与 `prompt` 相同。没有可接续的内容时两者都抛出 `NothingToDoError`，并说明原因。

### 重试超时的 run

```python
from zettcode.sdk.errors import RunTimeoutError

try:
    result = await session.prompt("migrate the schema", timeout=300)
except RunTimeoutError:
    result = await session.resume(timeout=300)
```

## 锁

会话被打开它的进程锁定。别的进程可以读取，但不能修改。

```python
if session.locked:
    print("open in another process; reading only")
    messages = await session.history()  # fine
else:
    await session.prompt("...")
```

在被锁定的会话上运行、重命名、压缩和恢复，会抛出 `SessionLockedError`。如果终端正开着某段对话，SDK 可以读它但不能往里加东西，反过来也是如此。

## 自我压缩

自我压缩是由模型自己决定何时压缩上下文:请求开始时提供这个工具,模型认为细节不再需要时就会请求。它有一个配置默认值
(`[compaction] self`),以及每个会话自己的选择。终端在 `/self-compact` 里编辑两者;在代码里,会话的选择是一个属性和一个方法:

```python
async with zc.Client(".") as client:
    print(client.self_compaction)  # 这个会话当前是否生效
    print(client.self_compaction_choice)  # True、False,或 None 表示跟随默认值
    client.use_self_compaction(True)  # 这个会话允许模型自己压缩
    client.use_self_compaction(None)  # 重新跟随配置
```

选择会写进会话,重启后仍在;它从下一次请求开始生效,因为工具是在请求开始时提供的。`OSError` 表示选择没能写入,当前生效的
选择不变。

## 会话里存了什么

`await client.session_stats()` 是对话在存储里的一面:文件里有多少条目、被计费了多少次回复,以及这些回复花掉的 token 和
缓存占比。这就是终端 `/resume` 的列,只在文件变过时重读。见[用量与体检](./usage)。

```python
async with zc.Client(".") as client:
    for stats in await client.session_stats([client.session.id]):
        print(stats.entries, stats.input_tokens, stats.cache_share)
```

## `Session` API 汇总

| 成员 | 类别 | 作用 |
| --- | --- | --- |
| `id`、`title`、`usage`、`path`、`current`、`locked` | 属性 | 身份与状态。 |
| `prompt`、`stream`、`run` | 方法 | [运行 prompt](./running)。 |
| `ask(question)` | 异步 | 不往对话里添加内容的旁路提问。 |
| `ask_stream(question)` | 同步 | 同样的旁路提问,以流的形式返回,答案可以边写边显示。 |
| `steer(message)` | 同步 | 向进行中的请求发一条消息。 |
| `history(full=False)` | 异步 | 模型使用的消息;`full=True` 时为整段对话。 |
| `rename(title)`、`name_it()` | 异步 | 给它起名字。 |
| `fork()` | 异步 | 把上下文复制到新会话。 |
| `export(path)` | 异步 | 写出 HTML 页面。 |
| `context()`、`compact()` | 异步 | 度量，以及立即总结。 |
| `resumable()`、`resume()`、`resume_stream()` | 异步 / 同步 | 接续被中断的请求。 |
