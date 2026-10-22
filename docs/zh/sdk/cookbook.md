---
title: 示例集
---

# 示例集

常见任务的完整程序。每个只用到本文档其余部分描述过的东西，改一下工作区和模型就能复制运行。

除非某个示例另有说明，它们都假定配置文件里已有一个模型。不想用配置文件时，在 `Client(...)` 里加上 `models=[{"model": "...", "token": os.environ["..."]}]`；见 [Client 与配置](./client#不用配置文件指定模型)。

## 在 CI 里修测试

无人值守的任务：只能运行测试套件和读取 git 状态，不能做别的，而且必须结束。

```python
import asyncio
import sys

import zettcode.sdk as zc
from zettcode.sdk.errors import RunError, ZettCodeError

RULE = zc.approve_commands("pytest", "git status", "git diff")


async def main() -> int:
    try:
        async with zc.Client(".", permission="safe", ask_user_enabled=False) as client:
            result = await client.prompt(
                "The tests fail. Find out why and fix the source, not the tests. Run pytest to check.",
                on_approval=RULE,
                timeout=900,
            )
    except RunError as error:
        print(f"agent failed (retryable={error.retryable}): {error}", file=sys.stderr)
        return 2
    except ZettCodeError as error:
        print(f"could not start: {error}", file=sys.stderr)
        return 3

    print(result.text)
    print(f"\n{result.usage.total_tokens:,} tokens, {len(result.tools)} tool calls", file=sys.stderr)
    return 0 if result.ok else 1


sys.exit(asyncio.run(main()))
```

退出码告诉流水线：agent 运行失败（2）、无法启动（3），还是没有完成就停下了（1）。`safe` 级别本来就放行无害的命令，规则之外的命令会被直接拒绝，而不是等着。

## 交互式终端助手

实时输出、对 shell 命令的确认提示，以及延续的对话。

```python
import asyncio

import zettcode.sdk as zc


async def confirm(request: zc.ApprovalRequested) -> bool:
    answer = await asyncio.to_thread(input, f"\n  run `{request.command}`? [y/N] ")
    return answer.strip().lower() == "y"


async def answer(question: zc.QuestionAsked) -> str | None:
    options = f" ({' / '.join(question.options)})" if question.options else ""
    text = await asyncio.to_thread(input, f"\n  ? {question.question}{options}: ")
    return text or None


async def main() -> None:
    async with zc.Client(".", permission="ask") as client:
        while True:
            text = (await asyncio.to_thread(input, "\n> ")).strip()
            if text in {"", "exit", "quit"}:
                break
            async with client.prompt(text, on_approval=confirm, on_question=answer) as run:
                async for event in run:
                    match event:
                        case zc.TextDelta(text=chunk):
                            print(chunk, end="", flush=True)
                        case zc.ToolStarted(name=name):
                            print(f"\n  [{name}]", end="")
            print(f"\n  ({run.result.usage.total_tokens:,} tokens; session {client.usage.total_tokens:,})")


asyncio.run(main())
```

`input()` 放在线程里运行，事件循环保持空闲。对问题给出空答案会返回 `None`，于是被拒答，模型继续往下走。

## Token 预算

当一个 run 花得比你预期的多时，把它停掉。`UsageUpdated` 带的是会话的累计值，所以要减去 run 之前的读数。

```python
import zettcode.sdk as zc
from zettcode.sdk.events import UsageUpdated


class BudgetExceeded(Exception):
    pass


async def prompt_within(client: zc.Client, text: str, *, budget: int) -> zc.RunResult:
    start = client.usage.total_tokens
    async with client.prompt(text) as run:
        async for event in run:
            if isinstance(event, UsageUpdated) and event.usage.total_tokens - start > budget:
                raise BudgetExceeded(f"more than {budget:,} tokens")
    assert run.result is not None
    return run.result
```

离开 `async with` 会关闭 run，client 随之重新空闲。run 已经加入对话的内容会保留；如果你决定让它跑完，可以用 `resume()`。

## 用一个模型分诊，用另一个模型修复

用便宜又快的模型判断一个任务值不值得动用昂贵的模型。

```python
import zettcode.sdk as zc

MODELS = [
    {"model": "small-fast-model", "token": "...", "display_model": "fast"},
    {"model": "large-strong-model", "token": "...", "display_model": "strong", "context_window": 400_000},
]


async def handle(issue: str) -> str:
    async with zc.Client(".", models=MODELS, permission="deny") as client:
        client.use_model("fast")
        client.use_effort("low")
        triage = await client.prompt(
            f"Reply with exactly one word, SIMPLE or HARD: how hard is this change?\n\n{issue}"
        )
        if "HARD" in triage.text.upper():
            client.use_model("strong")
            client.use_effort("high")
        fix = await client.prompt(f"Implement this change:\n\n{issue}")
        return fix.text
```

对话会跨越模型切换延续，所以更强的模型能看到分诊的内容。两个条目的模型 id 相同时，用 `display_model` 给每个起一个 `use_model` 能接受的名字。模型不接受的级别会抛出 `ConfigurationError`，并列出它接受的那些。

## 用分叉比较两种做法

先建立对项目的一份理解，再从它出发尝试两种设计。

```python
import zettcode.sdk as zc


async def compare(client: zc.Client, task: str, approaches: list[str]) -> dict[str, str]:
    base = client.session
    await base.prompt("Read the project and summarize how it is organized. Do not change anything.")

    results: dict[str, str] = {}
    for approach in approaches:
        attempt = await base.fork()
        result = await attempt.prompt(
            f"{task}\n\nApproach: {approach}. Describe the diff you would make, but make no edits."
        )
        results[approach] = result.text
    return results
```

各个分叉从同一份上下文出发，互不影响。它们在同一个 client 上依次进行；要真正并行，请用[单独的进程](./errors#并行工作)。

## 评审每个改动的文件

批处理任务：每个文件一段新对话，这样一个文件的上下文不会挤占下一个，最后汇总花费。

```python
import subprocess
from pathlib import Path

import zettcode.sdk as zc


async def review_changes() -> None:
    changed = subprocess.run(
        ["git", "diff", "--name-only", "origin/main"], capture_output=True, text=True, check=True
    ).stdout.split()

    total = zc.Usage()
    async with zc.Client(".", permission="deny", ask_user_enabled=False) as client:
        for name in changed:
            if not name.endswith(".py"):
                continue
            session = client.sessions.new()
            result = await session.prompt(
                f"Review {name} for bugs and unclear code. List only real problems, one line each.",
                timeout=180,
            )
            print(f"## {name}\n{result.text}\n")
            total = zc.Usage(
                input_tokens=total.input_tokens + result.usage.input_tokens,
                output_tokens=total.output_tokens + result.usage.output_tokens,
            )
    print(f"{total.total_tokens:,} tokens for {len(changed)} files")
```

`permission="deny"` 意味着模型可以读和推理，但从不运行命令。模型用自己的文件工具读取每个文件。

## 针对截图提问

```python
import zettcode.sdk as zc


async def explain_screenshot(path: str) -> str:
    async with zc.Client(".", permission="deny", model="vision") as client:
        if not client.model.multimodal:
            raise SystemExit(f"{client.model.name} cannot read images")
        result = await client.prompt(
            ["This is the page as a user sees it. What is wrong with the layout? ", zc.Image.from_path(path)]
        )
        return result.text
```

先检查 `client.model.multimodal` 能得到清晰的提示；读不了图的模型会在发出任何东西之前抛出 `ConfigurationError`。

## 取回结构化数据

模型返回的是文本。让它输出 JSON，然后自己校验。

```python
import json

import zettcode.sdk as zc


async def list_todos(client: zc.Client) -> list[dict]:
    result = await client.prompt(
        "Find every TODO comment in the source tree. Reply with only a JSON array of "
        '{"file": str, "line": int, "text": str} objects, no prose, no code fence.'
    )
    text = result.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    items = json.loads(text)
    if not isinstance(items, list):
        raise ValueError("expected a JSON array")
    return [item for item in items if isinstance(item, dict) and {"file", "line", "text"} <= item.keys()]
```

回复解析失败时，再发一个 prompt，引用错误并让它重来；对话里已经有第一次的尝试。

## 通过 WebSocket 提供 run

每个事件一发生就发给浏览器。这里用的是 Starlette；任何有异步处理函数的框架都是同样的形状。

```python
import dataclasses
import json

from starlette.websockets import WebSocket

import zettcode.sdk as zc
from zettcode.sdk.events import RawEvent


def encode(event) -> str:
    fields = {f.name: getattr(event, f.name) for f in dataclasses.fields(event) if not f.name.startswith("_")}
    return json.dumps({"type": type(event).__name__, **fields}, default=str)


async def chat(websocket: WebSocket, client: zc.Client) -> None:
    await websocket.accept()
    async for message in websocket.iter_text():
        async with client.prompt(message) as run:
            async for event in run:
                if isinstance(event, zc.ApprovalRequested):
                    await websocket.send_text(encode(event))
                    reply = json.loads(await websocket.receive_text())
                    event.approve() if reply.get("approve") is True else event.deny()
                elif not isinstance(event, RawEvent):
                    await websocket.send_text(encode(event))
```

一个 client 同一时刻服务一个浏览器。有多个用户的服务器需要为每个用户配一个 client，并且每个工作区一个进程。

## 测试使用 SDK 的代码

让测试远离网络和你真实的会话：临时存储、不读取工作区之外内容的扩展，以及一个假模型。

使用 `pytest-asyncio` 时，请在 pytest 配置里设置 `asyncio_mode = "auto"`，这样 `async` fixture 才会由插件运行；在它默认的 strict 模式下，下面的 fixture 不会被 await，测试会失败。

```python
import pytest

import zettcode.sdk as zc


@pytest.fixture
async def client(tmp_path):
    async with zc.Client(
        tmp_path,
        models=[{"model": "test-model", "token": "unused"}],
        store=tmp_path / "sessions",
        mcp_enabled=False,
        skills_enabled=False,
        agents_md_enabled=False,
        plugins_enabled=False,
    ) as client:
        yield client
```

至于模型，把运行时为供应商构建的东西换成一个按剧本回答的模型。SDK 自己的测试就是这么做的；仓库里的 `tests/sdk_helpers.py` 有一个小型 `ScriptedModel` 和一个 `wire` 辅助函数，可以直接拿去用。

要测试你的审批处理函数，手工构造一个事件并调用处理函数：

```python
def test_only_pytest_is_allowed():
    rule = zc.approve_commands("pytest")
    assert rule(zc.ApprovalRequested("s", "c", "pytest -q")) is True
    assert rule(zc.ApprovalRequested("s", "c", "pytest; rm -rf ~")) is False
```

## 明天接着做

```python
import zettcode.sdk as zc


async def today(client: zc.Client) -> str:
    result = await client.prompt("Start migrating the settings module to dataclasses.")
    return result.session_id  # save it


async def tomorrow(session_id: str) -> None:
    async with zc.Client(".", resume=session_id) as client:
        info = await client.session.resumable()
        if info:
            await client.session.resume()
        else:
            await client.prompt("Carry on with the migration.")
```

同一个 id 在终端里也能用：`/resume` 然后选它，或者从会话列表里启动。

## 提交前评审

```python
import subprocess
import sys

import zettcode.sdk as zc


def main() -> int:
    diff = subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True, check=True).stdout
    if not diff.strip():
        return 0
    result = zc.prompt_sync(
        f"Review this staged diff. If you see a real bug, start your reply with BLOCK, otherwise OK.\n\n{diff}",
        workspace=".",
        permission="deny",
        timeout=120,
        ask_user_enabled=False,
    )
    print(result.text)
    return 1 if result.text.lstrip().upper().startswith("BLOCK") else 0


sys.exit(main())
```

`prompt_sync` 正是非异步脚本想要的：它自己运行事件循环，而 `permission="deny"` 让它没有任何东西需要审批。
