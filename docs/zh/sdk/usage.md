---
title: 用量与体检
---

# 用量与体检

终端用 `/usage` 和 `doctor` 回答的两个问题,SDK 也能回答:花了多少,以及配置的模型是否可用。两者读的都是终端那份存储。

## 这个会话花了多少

`client.usage` 是当前会话的累计值:输入、输出、缓存读取、推理、请求数、模型耗时,以及最近一次调用的上下文大小。

```python
import zettcode.sdk as zc

async with zc.Client(".") as client:
    spent = client.usage
    print(spent.input_tokens, spent.output_tokens, spent.total_tokens)
    print(spent.cache_hit_rate)      # 输入中命中缓存的比例,没有输入时为 None
```

## 这个工作区花了多少

`await client.usage_ledger()` 返回工作区所有已保存对话记下的用量,按会话、按模型和按天排列,并给出总计 —— 和终端
`/usage` 页面一致。

```python
async with zc.Client(".") as client:
    ledger = await client.usage_ledger()
    print(ledger.total.requests, ledger.total.total_tokens, ledger.total.cache_share)
    for session in ledger.sessions[:5]:
        print(session.id, session.title, session.entries, session.tokens.total_tokens)
    for model in ledger.models:
        print(model.model, model.tokens.requests)
```

读取不在事件循环上,而且读取器留在 client 上:第二次查看只重读变过的会话。不会写入任何会话。

## `/resume` 的一行

`await client.session_stats()` 返回当前会话在存储里的统计;传入 id 可以看别的会话。每一行就是终端 `/resume`
面板显示的:条目数、请求数、输入、输出和缓存占比。

```python
async with zc.Client(".") as client:
    for stats in await client.session_stats([client.session.id]):
        print(stats.id, stats.entries, stats.requests, stats.total_tokens, stats.cache_share)
```

没有任何已存回复的会话没有这一行;读不了的会话会被略过,而不是抛错。

## 模型能用吗

`await client.check_models()` 对每个配置的模型同时问一个很短的问题,报告各自的回答 —— 和 `zettcode doctor`
是同一个检查,但不写任何会话。超时的模型会作为“没有回答”报告,而不是抛出异常。

```python
async with zc.Client(".") as client:
    for check in await client.check_models(timeout=15):
        print(check.model, check.ok, check.seconds, check.detail)
```

## 模型可以自己压缩多少

自我压缩是由模型自己决定何时压缩上下文。它有一个配置默认值,以及一个按会话的选择,终端的面板 `/self-compact` 编辑的
就是这两层:

```python
async with zc.Client(".") as client:
    print(client.self_compaction, client.self_compaction_choice)   # 当前是否生效,以及这个会话自己的选择
    client.use_self_compaction(True)                               # 这个会话允许模型自己压缩
    client.use_self_compaction(None)                               # 重新跟随配置默认值
```

选择保存在会话里,重新打开时还在;它从下一次请求开始生效,因为工具是在请求开始时提供的。

## `@` 资源

`client.mentions(query)` 列出 prompt 里 `@` 能指向的东西 —— 工作区的文件、搜索路径上的 skills,以及插件提供的内容
—— 用于补全菜单:

```python
async with zc.Client(".") as client:
    for mention in client.mentions("cli", limit=5):
        print(mention.token, mention.kind, mention.description)
```

Prompt 用 `mentions=True` 自己解析 `@`;这里只是读者输入时菜单展示的列表。
