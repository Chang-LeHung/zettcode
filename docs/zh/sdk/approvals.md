---
title: 审批与提问
---

# 审批与提问

能运行 shell 命令、能提问的 agent 必须能等待回答。本页讲它会等什么、三种作答方式、内置规则，以及如何安全地写自己的规则。

## agent 在等什么

| 事件 | agent 在等…… | 没人回答时 |
| --- | --- | --- |
| `ApprovalRequested` | ……对一条 shell 命令的决定。 | 命令被**拒绝**；模型会被告知并继续。 |
| `QuestionAsked` | ……对 `ask_user` 工具所提问题的回答。 | 问题被**拒答**；模型会被告知你取消了。 |

agent 被挂起在*工具调用内部*，直到其中之一被处理。正因如此，没有任何规则的 run 也不会卡死：到向流要下一个事件时仍未处理的，一律被拒绝或拒答。

审批只会出现在 `ask` 和 `safe` [权限级别](./client#权限级别)下。`deny` 时什么都不运行也不询问；`auto` 时全部运行也不询问。

## 三种作答方式

### 1. 处理函数

给 run 传一个函数或协程函数。它在事件到达你的循环之前被调用，返回值就是答案。

```python
import zettcode.sdk as zc

def only_tests(request: zc.ApprovalRequested) -> bool:
    return request.command.startswith("pytest")

result = await client.prompt("make the tests pass", on_approval=only_tests)
```

审批处理函数的返回值：

| 返回 | 含义 |
| --- | --- |
| `True` | 批准。 |
| `False` | 拒绝。 |
| `None` | 我不做决定；不动这个请求（仍可在循环里作答，不作答则被拒绝）。 |

问题处理函数返回作答的文本，或者返回 `None` 表示不动它。

```python
async def ask_a_person(question: zc.QuestionAsked) -> str | None:
    return await my_ui.prompt(question.question, choices=question.options)

result = await client.prompt("set up the project", on_question=ask_a_person)
```

处理函数可以是异步的。空白字符串会让问题保持未作答，`None` 也一样。

### 2. 在循环里作答

反正你在迭代，就直接在事件上作答：

```python
async with client.prompt("deploy to staging") as run:
    async for event in run:
        match event:
            case zc.ApprovalRequested(command=command) as ask:
                if input(f"run {command!r}? [y/N] ").lower() == "y":
                    ask.approve()
                else:
                    ask.deny()
            case zc.QuestionAsked(question=question, options=options) as ask:
                ask.answer(input(f"{question} {options or ''} "))
            case zc.TextDelta(text=text):
                print(text, end="")
```

审批：`approve()`、`approve(remember=True)`、`deny()`。提问：`answer("text")` 和 `decline()`。请在向流要下一个事件之前作答。

这里的 `input()` 会阻塞事件循环。对脚本无所谓，对服务器就不行；在那里请用 `await asyncio.to_thread(input, ...)` 或你的 UI 的异步提示。

### 3. 都不做

不作答就是拒绝和拒答。无人值守的任务可以依赖这一点。

```python
result = await client.prompt("clean up the build directory")        # shell requests are denied
```

也可以组合使用：处理函数回答它认识的命令，其余返回 `None`，剩下的由循环处理。

## 内置规则

| 处理函数 | 行为 |
| --- | --- |
| `zc.approve_all` | 批准所有命令。只用于你信任其 shell 的工作区和模型。 |
| `zc.deny_all` | 拒绝所有命令。模型会被告知并继续。 |
| `zc.approve_commands(*commands)` | 批准列出的命令，或在列出的命令后面带参数的命令。其余全部拒绝。 |

```python
rule = zc.approve_commands("pytest", "git status", "git diff", "ruff check")

result = await client.prompt("fix the lint errors and run the tests", on_approval=rule)
```

### `approve_commands` 如何匹配

命令**等于**某个列出的命令，或者**在它后面加空格再继续**，就算匹配：

| 规则 | 命令 | 匹配 |
| --- | --- | --- |
| `git status` | `git status` | ✓ |
| `git status` | `git status -s` | ✓ |
| `git status` | `git statusx` | ✗ |
| `pytest` | `pytest tests/ -k parser` | ✓ |
| `pytest` | `python -m pytest` | ✗ |

规则和命令两端的空白都会被忽略。

### 为什么 shell 语法永远不匹配

单看前缀的规则会批准 `git status; rm -rf ~`，因为它以 `git status` 开头。所以只要命令里含有下列任何字符，不管它怎么开头，都**永远**不匹配：

```text
;  &  |  <  >  $  `  (  )  {  }  \  以及换行
```

这就排除了管道、串联、重定向、替换和子 shell。如果你需要 `pytest | tail`，要么批准朴素的 `pytest` 让模型自己读完整输出，要么自己写一个解析命令的处理函数。

同样的检查也适用于你写的规则。含 shell 字符的规则或空白规则，会在你创建处理函数时抛出 `ValueError`，而不是等到命令到来时：

```python
zc.approve_commands("git status; ls")      # ValueError: 'git status; ls' holds a shell character; ...
zc.approve_commands("   ")                 # ValueError: A command to allow cannot be blank
```

## 写自己的规则

处理函数拿到的 `ApprovalRequested` 带有：

| 字段 | 含义 |
| --- | --- |
| `command` | 模型想运行的命令。 |
| `timeout_seconds` | 命令会在多少秒的限制下运行（工具给出时）。 |
| `remember_supported` | 批准后是否能在本次 run 的其余部分记住。 |
| `call_id`、`session_id` | 工具调用与会话。 |

### 带日志的白名单

```python
import logging

log = logging.getLogger("agent.shell")
ALLOWED = zc.approve_commands("pytest", "ruff check", "git diff")

def audited(request: zc.ApprovalRequested) -> bool:
    allowed = ALLOWED(request)
    log.info("%s %s", "ALLOW" if allowed else "DENY", request.command)
    return allowed
```

### 遇到不认识的命令就问人

```python
async def human_in_the_loop(request: zc.ApprovalRequested) -> bool | None:
    if ALLOWED(request):
        return True
    return await chat.confirm(f"The agent wants to run:\n\n{request.command}")
```

### 记住一次决定

`approve(remember=True)` 在 `remember_supported` 为真时，让同类命令在本次 run 的其余部分不再询问直接运行。请求记住一个无法被记住的东西不算错误，只是批准一次。

```python
async for event in run:
    match event:
        case zc.ApprovalRequested(command=command, remember_supported=True) as ask if command.startswith("npm test"):
            ask.approve(remember=True)
```

### 它拒绝犯的错

处理函数必须恰好返回 `True`、`False` 或 `None`。其他任何值都会抛出 `TypeError`，并且**不会批准**，因为最可能的错误值是像 `"no"` 这样的真值字符串，而无意中批准一条 shell 命令是最糟糕的出错方式。

```python
def careless(request):
    return "no"                        # TypeError: An approval handler returns True, False or None, not str
```

处理函数如果抛出异常，命令被拒绝，run 停止，错误原样到达 `await` 的调用方。规则里的 bug 不会让命令继续运行。

问题处理函数必须返回文本或 `None`；其他值是 `TypeError`。

## 重复作答

第一个答案生效，并且只发送一次。以同样方式再答一次是无害的。以相反方式作答会抛出 `ValueError`，因为 agent 已经按第一个答案行动了。

```python
ask.approve()
ask.approve()          # fine
ask.deny()             # ValueError: Already answered ...
```

`ask.answered` 告诉你它是否已被处理（无论是你还是 run 的处理函数），`ask.approved` 是 `True`、`False`，未作答时为 `None`。

不是 SDK 创建的事件没有可作答的对象：对你手工构造的事件调用 `approve()` 会抛出 `RuntimeError`。这让你很容易为自己的处理函数写测试：用事件调用处理函数，检查返回值。

```python
request = zc.ApprovalRequested("s", "c", "git status")
assert zc.approve_commands("git status")(request) is True
```

## 提问详解

`QuestionAsked` 带有：

| 字段 | 含义 |
| --- | --- |
| `question` | 问了什么。 |
| `options` | 它给出的选项，可能为空。答案仍可以是自由文本。 |
| `allow_multiple` | 是否可以选多个选项。 |

答案会原样交给模型。多选时请自己把选项拼起来：

```python
def choose(question: zc.QuestionAsked) -> str | None:
    if question.options and question.allow_multiple:
        return ", ".join(question.options[:2])
    if question.options:
        return question.options[0]
    return None
```

空答案会让 `answer()` 抛出 `ValueError`；要拒答请调用 `decline()`。run 问过的问题列在 `result.questions` 里。

如果你的程序根本没法回答问题，就关掉这个工具，让模型不再提问：

```python
async with zc.Client(".", ask_user_enabled=False) as client:
    ...
```

## 无人值守清单

对于没人看着的任务：

1. 有意识地选择权限级别：模型只需读和改就用 `deny`，允许它四处看看就用 `safe`。
2. 如果它需要运行什么，用 `approve_commands` 点名，而不是 `approve_all`。
3. 设置 `ask_user_enabled=False`，或给一个根据你的配置作答的 `on_question`。
4. 设置 `timeout`。见[错误与超时](./errors)。
5. 把结果里的 `tools` 和 `failed_tools` 记进日志。
