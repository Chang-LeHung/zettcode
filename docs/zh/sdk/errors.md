---
title: 错误与超时
---

# 错误与超时

SDK 有意抛出的一切都派生自 `ZettCodeError`，所以一个 `except` 就能表达“ZettCode 拒绝了或失败了”。本页列出什么会抛什么、何时抛、如何重试、超时怎么工作，以及怎样并行。

## 继承层次

```text
Exception
└── ZettCodeError
    ├── ConfigurationError        （同时是 ValueError）
    ├── ClientClosedError
    ├── SessionBusyError
    ├── SessionLockedError
    ├── SessionNotFoundError      （同时是 LookupError）
    ├── NothingToDoError
    ├── WorkspaceConflictError
    └── RunError
        └── RunTimeoutError       （同时是 TimeoutError）
```

`ZettCodeError`、`ConfigurationError` 和 `RunError` 从 `zettcode.sdk` 导出。其余在 `zettcode.sdk.errors` 里。

```python
from zettcode.sdk.errors import SessionBusyError, SessionNotFoundError
```

其中三个还继承了调用方本来就会捕获的内置异常，所以现有的处理代码照常工作：`except ValueError` 能捕获 `ConfigurationError`，`except LookupError` 能捕获 `SessionNotFoundError`，`except TimeoutError` 能捕获 `RunTimeoutError`。

有底层错误时，它保存在 `__cause__`。

## 参考

| 错误 | 何时抛出 | 通常的处理 |
| --- | --- | --- |
| `ConfigurationError` | 未知的设置（附带建议）、不存在的模型/推理强度/权限、格式错误的模型条目、缺少 token、不是目录的工作区，或把图片发给读不了图的模型。 | 修正代码或配置。不可重试。 |
| `ClientClosedError` | `aclose()` 之后再使用 client。 | 新建一个 client。 |
| `SessionBusyError` | run 进行期间尝试 run、切换、分叉或重命名。 | 等 run 结束、关闭它，或使用另一个进程。 |
| `SessionLockedError` | 别的进程打开着该会话，而你试图运行、重命名、压缩或恢复。 | 只读访问可用；等待或分叉。 |
| `SessionNotFoundError` | 会话 id 不存在或读不出来；对还没有消息的会话调用 `history()` 或 `fork()`。 | 用 `sessions.list()` 核对 id。 |
| `NothingToDoError` | 对没有被中断的对话调用 `resume()`，或对已压缩的对话调用 `compact()`。消息会说明原因。 | 不是失败；跳过即可。 |
| `WorkspaceConflictError` | 本进程里已打开了另一个目录的 client。 | 关掉第一个，或使用单独的进程。 |
| `RunError` | run 期间模型、供应商或网络出了问题。 | 看 `retryable`。 |
| `RunTimeoutError` | run 超过了它的 `timeout`。 | `resume()`，或重试。 |

无效的*参数*用的是内置错误：空 prompt、非正数的 `timeout` 或 `limit`、坏图片、空白标题抛 `ValueError`；prompt 不是文本和图片、处理函数返回了错误类型的东西抛 `TypeError`。

## 错误在哪里出现

**返回 run 的调用**（`prompt`、`stream`、`resume_stream`）会立即检查参数，有问题就在那里抛出。凡是涉及模型的，都在你 **await 或迭代** run 时才抛出：

```python
run = client.prompt("")                    # ValueError raised here
run = client.prompt("explain this")        # nothing has happened yet
result = await run                         # RunError, RunTimeoutError, ... raised here
```

所以要包住 `await` 或 `async for`，而不是创建 run 的那个调用：

```python
from zettcode.sdk.errors import RunError

try:
    result = await client.prompt("...")
except RunError as error:
    ...
```

## run 失败

模型、供应商或网络出问题时抛出 `RunError`：

| 属性 | 含义 |
| --- | --- |
| `str(error)` | 对出了什么问题的可读描述。 |
| `error.retryable` | 再试一次是否可能成功：超时、断线、限流、服务器错误。密钥被拒绝或请求格式错误**不是**。 |
| `error.partial_text` | 出错时模型已经说出的内容。往往仍值得保留。 |
| `error.__cause__` | 供应商库抛出的原始异常。 |

```python
try:
    result = await client.prompt("summarize the changelog")
except RunError as error:
    print("failed:", error)
    if error.partial_text:
        print("partial answer:", error.partial_text)
```

拒绝或被截断**不是**错误。模型已经回答，所以它是一个 `stop` 说明原因的 `RunResult`。见[运行 Prompt](./running#没有顺利结束的-run)。

### 失败之后

client 重新空闲，对话保留了该次 run 已加入的一切。失败的 run 没有结果：`run.result` 保持 `None`。可以发新的 prompt，或者 `resume()` 被中断的那个。

## 重试

只在 `retryable` 为真时重试，延迟逐步增长，并且有次数上限。

```python
import asyncio
import random
from zettcode.sdk.errors import RunError


async def prompt_with_retry(client, text, *, attempts=4, **options):
    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            return await client.prompt(text, **options)
        except RunError as error:
            if not error.retryable or attempt == attempts:
                raise
            await asyncio.sleep(delay + random.uniform(0, delay / 4))
            delay *= 2
```

这会把 prompt 作为新的一轮再发一次，所以模型能看到上次尝试留下的部分工作。如果想接续被中断的请求，改用 `resume()`，在工具已经运行过的情况下更好：

```python
async def finish(session, text, *, attempts=3):
    try:
        return await session.prompt(text)
    except RunError:
        for _ in range(attempts):
            try:
                if await session.resumable() is None:
                    break
                return await session.resume()
            except RunError as error:
                if not error.retryable:
                    raise
        raise
```

::: tip
agent 库在你看到错误之前，已经会对临时性的供应商错误重试（默认额外三次，延迟逐步增长）。到达这里的 `RunError` 已经重试过了；不要在它上面再叠一个大的重试循环。
:::

## 超时

`timeout=` 限制**整个 run** 的秒数，而不是每个事件。

```python
from zettcode.sdk.errors import RunTimeoutError

try:
    result = await client.prompt("run the integration suite", timeout=300)
except RunTimeoutError as error:
    print(f"gave up after {error.seconds:g}s")
    print(error.partial_text)
```

期限一到，run 被停止并抛出 `RunTimeoutError`。它是 `RunError`（`retryable=True`），同时也是 `TimeoutError`。对话保留该次 run 已加入的内容，所以可以用 `await session.resume()` 接着做。

`timeout` 必须是正数（布尔值不算）或 `None`（一直等下去）；其他值会在 run 开始之前抛出 `ValueError`。

期限从 run 开始时计时，并在等待每个事件时检查，所以卡在某一步中间的模型会准时被停止，而事件流的消费者再慢也不会延长它。

### 从外部取消

也可以取消正在 await 它的任务来停止 run：

```python
task = asyncio.create_task(client.run("long job"))
await asyncio.sleep(30)
task.cancel()
try:
    await task
except asyncio.CancelledError:
    pass
```

取消从不被包装或吞掉：`CancelledError` 原样传播。run 被关闭，client 重新空闲。

如果要让期限覆盖多个步骤，用 `asyncio.timeout`（Python 3.11+）或 `asyncio.wait_for` 包住整个序列。

## 并行工作

一个 client 同一时刻只做一件事。在一个 run 进行时启动第二个，会抛出 `SessionBusyError`，而不是把两个请求交错进同一段对话。

```python
from zettcode.sdk.errors import SessionBusyError

async with client.prompt("first") as run:
    async for event in run:
        try:
            client.prompt("second")
        except SessionBusyError as error:
            print(error)
        break
```

同时发出两个请求有以下方式：

- **不同的进程**，每个一个 client。这是受支持的并行方式，也是同时处理两个工作区的唯一办法。用 `concurrent.futures.ProcessPoolExecutor`、`multiprocessing` 或任务运行器，并在 worker 里调用 `prompt_sync` 或 `asyncio.run`。
- **轮流使用不同会话**：`sessions.new()` 和 `fork()` 给出相互独立的对话，但它们仍在同一个 client 上轮流进行。

```python
import asyncio
from concurrent.futures import ProcessPoolExecutor
import zettcode.sdk as zc


def review(path: str) -> str:
    return zc.prompt_sync(f"review {path}", workspace=".", permission="deny", timeout=300).text


if __name__ == "__main__":
    with ProcessPoolExecutor(4) as pool:
        for text in pool.map(review, ["src/a.py", "src/b.py", "src/c.py"]):
            print(text)
```

凡是用 spawn 方式启动进程的平台（macOS 和 Windows），`if __name__ == "__main__":` 这层守卫都是必须的：每个 worker 会再次导入这个文件，没有守卫的话它会自己再起一个进程池，进程池随即以 `BrokenProcessPool` 崩溃。

每个 worker 都要加载 agent；这是需要与一次评审耗时相权衡的启动成本。让它们指向同一个 `store`：会话是各自独立的文件。

## 在读取者脚下关闭

另一个任务正在读取某个 run 时关闭 client，会让那个任务的循环干净地结束，而不是抛出异常：它的事件到此为止。

```python
async def reader(run):
    async for event in run:
        ...                                   # ends when the client closes

task = asyncio.create_task(reader(client.prompt("...")))
await asyncio.sleep(5)
await client.aclose()
await task                                    # returns; no error
```

## 不该捕获的错误

- `asyncio.CancelledError` 属于调用方。不重新抛出就不要捕获它。
- 处理函数（`on_approval`、`on_question`、`on_event`）里的 bug 会**原样**到达调用方，而不是变成 `RunError`。它正在决定的命令会先被拒绝。

## 一个防御性的包装

```python
from zettcode.sdk.errors import (
    ConfigurationError,
    RunError,
    SessionLockedError,
    ZettCodeError,
)

async def safe_prompt(client, text, **options):
    try:
        return await client.prompt(text, **options)
    except ConfigurationError:
        raise                                  # a bug in how it is called: let it fail loudly
    except SessionLockedError:
        return None                            # someone else has the session
    except RunError as error:
        log.warning("run failed (retryable=%s): %s", error.retryable, error)
        return None
    except ZettCodeError as error:
        log.error("ZettCode refused: %s", error)
        raise
```
