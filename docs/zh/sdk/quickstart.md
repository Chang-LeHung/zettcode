---
title: 快速上手
---

# 快速上手

三个例子，看看 SDK 做什么、怎么用。

## 一次 prompt

发出 prompt，拿到结果。调用 agent 最简单的方式。

```python
import zettcode.sdk as zc

result = await zc.prompt("summarize the README", workspace=".", permission="deny")
print(result.text)
print(f"Used {result.usage.total_tokens} tokens")
```

`permission="deny"` 表示不运行任何 shell 命令，适合无人值守的脚本；agent 会改用文件工具。

### 在同步代码里

```python
result = zc.prompt_sync("check the parser", workspace=".", permission="safe", timeout=120)
```

`prompt_sync()` 会阻塞到完成。它拒绝在事件循环内运行，因为那样会卡住循环。

## 一段对话

`Client` 在多次 prompt 之间保留 agent，所以对话会延续。

```python
async with zc.Client(".", permission="safe") as client:
    result = await client.prompt("make the tests pass")
    print(result.text)

    if not result.ok:
        print(f"Stopped: {result.stop}")

    followup = await client.prompt("explain what you changed")
    print(followup.text)
```

第二个 prompt 能看到第一个做了什么。`client.session.usage` 是整个会话的累计用量；`result.usage` 是这一次 run 的用量。

## 流式进度

迭代 run，按事件看到进度。

```python
async with zc.Client(".", permission="safe") as client:
    async with client.prompt("fix the bug") as run:
        async for event in run:
            match event:
                case zc.TextDelta(text=text):
                    print(text, end="", flush=True)
                case zc.ToolStarted(name=name):
                    print(f"\n[{name}]")
                case zc.ToolFinished(ok=False, output=output):
                    print(f"  Failed: {output}")

    print(f"\n{run.result.usage.total_tokens} tokens")
```

run 既可以 await（得到结果），也可以 async 迭代（得到事件）。`run.result` 在 run 结束前是 `None`，结束后是 `RunResult`。

## 审批规则

除非权限级别另有规定，shell 命令需要审批。可以传处理函数、在事件上就地作答，或者两者都不做——那样命令会被拒绝。

```python
def only_read_commands(request):
    return request.command.startswith(("git status", "git diff", "cat ", "ls "))

result = await client.prompt("check the diff", on_approval=only_read_commands)
```

或者

```python
async with client.prompt("run the tests") as run:
    async for event in run:
        match event:
            case zc.ApprovalRequested() as ask:
                if "pytest" in ask.command:
                    ask.approve()
                else:
                    ask.deny()
            case zc.TextDelta(text=text):
                print(text, end="")
```

内置处理函数：

- `zc.approve_all`：信任工作区和模型
- `zc.deny_all`：不运行任何 shell 命令
- `zc.approve_commands("pytest", "git status")`：按前缀匹配，不允许 shell 语法

## 会话

创建、切换、继续对话。

```python
async with zc.Client(".") as client:
    # Start two conversations
    first = client.session
    await first.prompt("analyze the code")

    second = client.sessions.new()
    await second.prompt("write a test")

    # Back to the first
    await first.prompt("one more thing")

    # Continue a stored session
    stored = await client.sessions.open("abc123def")
    await stored.prompt("keep going")
```

`Client(resume="abc123def")` 直接在某个已保存的会话上启动。`client.sessions.list()` 列出工作区里有什么。

## 接下来

- [**核心概念**](./concepts)：client、session、run 如何配合
- [**运行 Prompt**](./running)：`prompt()`、`run()`、`stream()` 及其参数
- [**事件流**](./events)：run 会产生的每种事件
- [**会话**](./sessions)：创建、分叉、历史、导出
- [**示例集**](./cookbook)：完整示例
