---
title: 核心概念
---

# 核心概念

整个 SDK 由五个对象构成。弄清每个对象是做什么的、不是做什么的，其余文档就会变得简短。

```text
Client ──────────────► 一个工作区、一份配置、一个 agent
  │
  ├── client.sessions ► Sessions：list / new / open / latest
  │
  └── client.session ─► Session：一段已保存的对话
                          │
                          └── session.prompt(...) ─► RunStream
                                                      │  await ─► RunResult
                                                      └─ 迭代 ─► 事件
```

## Client

`Client` 是某个工作区的 agent。它持有配置、模型连接、插件和 MCP 的装配、会话存储以及会话锁。创建、使用、关闭。

```python
import zettcode.sdk as zc

async with zc.Client(".", permission="safe") as client:
    print(client.workspace)      # the resolved directory
    print(client.model.name)     # the active model
    print(client.permission)     # "safe"
```

长期持有一个 client 很便宜，创建却不便宜：创建时要加载 agent、读取配置、连接各种扩展。所以一个程序或一个工作区只建一个，不要每个 prompt 建一个。只发一个 prompt 的话，`zc.prompt()` 会替你走完整个生命周期。

## Session

`Session` 是一段已保存对话的句柄。client 总有一个当前会话 `client.session`，新建时为空。client 去处理别的对话时，句柄依然有效；下一次需要它的调用会自动切回来。

```python
async with zc.Client(".") as client:
    session = client.session
    print(session.id)        # the identity you can resume later
    print(session.title)     # None until it has a name
    print(session.current)   # True: the next run would use this one
```

会话以终端相同的格式保存在磁盘上，所以在这里开始的对话可以在终端里用 `/resume` 继续，反之亦然。

## Run

一次 run 就是对 agent 的一次请求：你发出 prompt，模型工作、调用工具，最终给出回答。`session.prompt(...)` 返回一个 `RunStream`，它同时满足你对 run 的两种需求：

- **await** 它，得到完整的 `RunResult`；
- **迭代** 它，实时得到事件。

```python
async with zc.Client(".") as client:
    result = await client.prompt("explain this module")      # wait for the end

    async with client.prompt("explain this module") as run:  # or watch it happen
        async for event in run:
            ...
```

也可以两者结合：先迭代一部分，再 `await` 剩下的。

## Event

事件是 run 过程中发生的一件事：一段文本、一个工具开始执行、一条 shell 命令在等待审批。事件是冻结的 dataclass，所以你按类匹配，读取的字段始终存在。

```python
async for event in run:
    match event:
        case zc.TextDelta(text=text):
            print(text, end="")
        case zc.ToolStarted(name=name, arguments=args):
            print(f"[{name}] {args}")
```

有两种事件需要你的程序回应：`ApprovalRequested` 和 `QuestionAsked`。agent 会停在工具调用内部等待回答，所以这两个事件自带作答的方法。见[审批与提问](./approvals)。

## Result

`RunResult` 是一次完成的 run 的纯数据摘要：回答、花费、运行了哪些工具及各自如何结束，以及模型没有正常结束时的原因。

```python
result = await client.prompt("run the tests")
result.text            # the answer
result.usage           # what this run spent (not the session's total)
result.tools           # every tool call, in order
result.failed_tools    # the ones that did not succeed
result.stop            # None, or "refusal", "max_output", ...
result.ok              # True exactly when stop is None
```

## 由此得出的规则

**一个 client 同一时刻只做一件事。** 终端一次处理一个请求，client 也是。在一个 run 进行时启动第二个，会抛出 `SessionBusyError`，而不是把两个请求交错进同一段对话。要并行工作，请用多个进程；见[错误与超时](./errors#并行工作)。

**一个进程只有一个工作区。** 编码工具按进程的工作目录解析相对路径，而工作目录是全局的。创建 client 会切换到工作区，关闭最后一个会恢复原目录。第二个、不同工作区的 client 会抛出 `WorkspaceConflictError`。

**打开的要关。** `async with` 会关闭 client，释放模型连接和会话锁。凡是可能提前离开循环的地方，都用 `async with client.prompt(...) as run:`，这样即使提前离开，run 也会被关闭。

**不会卡死。** 没人回答的审批会被拒绝，没人回答的提问会被拒答，所以没有处理函数的 run 也不会永远等下去。

**值都是朴素数据。** SDK 返回的一切都是 SDK 自己拥有的冻结 dataclass，可以在测试里手工构造、比较、保存和打印。

## SDK 与终端共享什么

| 共享的部分 | 含义 |
| --- | --- |
| Agent、工具、压缩 | 同一个模型循环，没有重新实现。 |
| 插件、MCP 服务器、skills | 从同样的位置加载，受同样的设置约束。 |
| `AGENTS.md` 项目指令 | `agents_md_enabled` 开启时读取，默认开启。 |
| 会话存储 | 同样的文件与格式；会话可以在代码和终端之间流转。 |
| 权限级别 | `deny`、`ask`、`safe`、`auto`，含义相同。 |
| 配置文件 | `~/.zettcode/config.toml`，除非你自己传入 models 或 config。 |

## 它默认关掉了什么

嵌入 agent 的程序不应该在背后做别的事，所以 client 默认 `sessions_enabled=False`（不连 broker，终端会话无法给它发消息）和 `update_enabled=False`（不检查新版本）。传 `sessions_enabled=True` 可以重新开启。

## 导入

`import zettcode.sdk` 只加载这个包本身。`Client`、`TextDelta` 等名字在第一次使用时才加载它们所在的模块，agent 则在创建 `Client` 时加载。包里导出的是程序每天都会用到的名字，不常用的在子模块里，多写一个 import 即可。

| 模块 | 内容 |
| --- | --- |
| `zettcode.sdk` | `Client`、`Session`、`RunStream`、`prompt`、`prompt_sync`、`RunResult`、`Usage`、`Image`、常用事件、审批处理函数、`ZettCodeError`、`ConfigurationError`、`RunError` |
| `zettcode.sdk.events` | 所有事件类，以及用于类型标注的 `AnyEvent` |
| `zettcode.sdk.types` | `ModelInfo`、`SessionInfo`、`Message`、`ToolRecord`、`ContextReport`、`Compaction`、`ResumeInfo` 等方法返回的值 |
| `zettcode.sdk.errors` | 所有错误类 |
| `zettcode.sdk.handlers` | 用于类型标注的 `ApprovalHandler` 和 `QuestionHandler` |

```python
from zettcode.sdk.events import AnyEvent, Notice, Steered
from zettcode.sdk.types import ContextReport, ModelInfo
from zettcode.sdk.errors import NothingToDoError, SessionBusyError
```
