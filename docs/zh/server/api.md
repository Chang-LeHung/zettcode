---
title: HTTP API 参考
---

# HTTP API 参考

除非另有说明,每个端点都返回 JSON,失败时都用同一种形状:

```json
{"error": "busy", "message": "A run is already in progress; wait for it or cancel it"}
```

| `error` | 状态码 | 何时 |
| --- | --- | --- |
| `invalid` | 400 / 422 | 设置里的名字不存在;请求体校验失败;命令含有 shell 特殊字符。 |
| `unauthorized` | 401 | token 缺失或不对。 |
| `not_found` | 404 | 没有这个会话。 |
| `busy` | 409 | 有一轮运行正在进行,而这个操作需要这个会话。 |
| `locked` | 409 | 另一个进程占着这个会话。 |
| `nothing_to_do` | 409 | 没有可继续的中断请求。 |
| `timeout` | 504 | 运行的截止时间到了。 |
| `run` | 502 | provider 或这次运行失败。 |
| `internal` | 500 | 其他情况;消息来自 SDK。 |

除 `/health` 外,如果启动时给了 token,每个端点都要求 `Authorization: Bearer <token>`。

## 健康检查

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| `GET` | `/health` | `{"status","version","workspace","session","busy"}`;唯一不需要 token 的端点。 |
| `GET` | `/` | 名称、版本以及文档和健康检查的路径。 |

## 模型与设置

| 方法 | 路径 | 请求体 | 返回 |
| --- | --- | --- | --- |
| `GET` | `/models` | — | `{"models": [{"name","model","context_window","multimodal","efforts","active"}], "current"}` |
| `GET` | `/settings` | — | `{"model","effort","efforts","permission","permissions"}` |
| `PATCH` | `/settings` | `{"model"?, "effort"?, "permission"?}` | 更改后与 `GET /settings` 相同;至少给一个字段。 |
| `GET` | `/plugins` | — | `{"loaded": [...], "failures": [...]}` |

```bash
curl -X PATCH http://127.0.0.1:3290/settings \
  -H 'content-type: application/json' \
  -d '{"model": "fast", "effort": "low", "permission": "safe"}'
```

模型用 `/models` 列出的名字指定(有条目设了显示名就用显示名)。模型的 token 永远不会返回。

## 会话

*当前*会话就是下一次 prompt 继续的对话。服务器启动时是一个新会话。

| 方法 | 路径 | 请求体 | 返回 |
| --- | --- | --- | --- |
| `GET` | `/sessions?limit=20` | — | `{"sessions": [{"id","title","created_at","updated_at","current"}]}`,最近活动的在前。 |
| `POST` | `/sessions` | `{"title"?}` | 201,新会话,并成为当前会话。 |
| `GET` | `/sessions/current` | — | `{"id","title","locked","usage"}` |
| `POST` | `/sessions/{id}/open` | — | 打开的会话,成为当前会话;不存在时 404。 |
| `POST` | `/sessions/current/rename` | `{"title"}` | 重命名后的会话。 |
| `POST` | `/sessions/current/name` | — | 让模型给对话命名,返回新名字。 |
| `POST` | `/sessions/current/fork` | — | 新会话,延续这个对话的上下文。 |
| `POST` | `/sessions/current/compact` | — | `{"applied","summary","compressed","kept"}`;没有可折叠内容时 `applied:false`。 |
| `GET` | `/sessions/current/context` | — | `{"window","used","measured_by","shares","partial","from_provider"}`,测量前为 `null`。 |
| `GET` | `/sessions/current/history` | — | `{"messages": [{"role","text","tool_calls","ok","images"}]}` |
| `GET` | `/sessions/current/export` | — | 对话导出成独立的 HTML 页面(`text/html`,按下载处理)。 |
| `POST` | `/sessions/current/ask` | `{"question","timeout"?}` | `{"answer"}`;在旁边回答,不进入对话。运行进行中返回 409。 |

`usage` 是会话的累计值:

```json
{"input_tokens": 1200, "output_tokens": 340, "cache_read_tokens": 800, "cache_write_tokens": 0,
 "reasoning_tokens": 0, "seconds": 4.2, "requests": 3, "context_tokens": 1540}
```

## 运行

| 方法 | 路径 | 请求体 | 返回 |
| --- | --- | --- | --- |
| `POST` | `/prompts` | `PromptRequest` | `text/event-stream`:运行的事件,最后是 `result`、`error` 或 `cancelled`。 |
| `POST` | `/runs/resume` | `RunOptions` | 同样的流,继续被中断的请求。 |
| `GET` | `/runs/current` | — | `{"running", "pending"}`:是否有运行在跑、它在等什么。 |
| `GET` | `/runs/resumable` | — | `{"resumable","kind","description"}` |
| `POST` | `/runs/approvals` | `{"call_id","approve","remember"?}` | `{"resolved"}`,运行是否正在等这个调用。 |
| `POST` | `/runs/questions` | `{"call_id","answer"}` | `{"resolved"}`;`"answer": null` 表示拒绝回答。 |
| `POST` | `/runs/steer` | `{"text"}` | `{"steered"}`,没有运行接收时为 false。 |
| `POST` | `/runs/cancel` | — | `{"cancelled"}`,是否有运行被停止。 |

`RunOptions`:

```json
{
  "approvals": {"mode": "deny", "commands": []},
  "questions": "decline",
  "timeout": null,
  "answer_timeout": 300,
  "keep_events": false
}
```

| 字段 | 含义 |
| --- | --- |
| `approvals.mode` | `deny`(默认)拒绝所有 shell 命令,`auto` 全部批准,`commands` 只批准 `commands` 里的,`ask` 把每条命令交给客户端。 |
| `approvals.commands` | 例如 `"git status"`、`"pytest"`。命令等于其一或者在其后接参数才算匹配;含有 `;`、`|`、`&`、`$`、换行等 shell 字符的一律不匹配,所以 `git status; rm -rf ~` 不等于 `git status`。 |
| `questions` | `decline`(默认)告诉模型没人在;`ask` 把问题发到流里并等待回答。 |
| `timeout` | 整轮运行最多多少秒,或 `null`。 |
| `answer_timeout` | `ask` 的审批或问题等待客户端多少秒,超时后取安全默认值(拒绝、拒答)。 |
| `keep_events` | 最终 `result` 里也保留所有事件。 |

`PromptRequest` 额外有:

| 字段 | 含义 |
| --- | --- |
| `text` | prompt;必填且不能为空。 |
| `images` | `[{"data": "<base64>", "media_type": "image/png"}]`,给接受图片的模型。 |
| `mentions` | 解析文本里的 `@path` 引用,和终端一致;默认 true。 |

::: tip 无法运行的 prompt 是状态码
无法运行的请求体 —— 规则拒绝匹配的命令、不是 base64 的图片 —— 在流打开之前就返回 400。事件开始之后才失败的,
是一个 `error` 帧:那时状态行已经发出去了。
:::
