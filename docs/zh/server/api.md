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
| `no_model` | 409 | 还没有配置模型,没有可用来运行 prompt 的代理。用 `POST /models` 加一个。 |
| `timeout` | 504 | 运行的截止时间到了。 |
| `run` | 502 | provider 或这次运行失败。 |
| `internal` | 500 | 其他情况;消息来自 SDK。 |

除 `/health` 外,如果启动时给了 token,每个端点都要求 `Authorization: Bearer <token>`。

## 健康检查

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| `GET` | `/health` | `{"status","version","workspace","ready","session","models","busy"}`;唯一不需要 token 的端点。配置模型之前 `ready` 为 false,`session` 为 null。 |
| `GET` | `/` | 名称、版本以及文档和健康检查的路径。 |

## 模型与设置

| 方法 | 路径 | 请求体 | 返回 |
| --- | --- | --- | --- |
| `GET` | `/models` | — | `{"models": [{"name","model","context_window","multimodal","efforts","active","compact_percent","web_search","web_search_name","display_model","base_url","api","temperature","can_search","search_name"}], "current"}`;配置模型之前也能用,此时 `current` 为 null。 |
| `POST` | `/models` | `{"model", "token"?, "display_model"?, "base_url"?, "anthropic"?, "responses_api"?, "chat"?, "multimodal"?, "temperature"?, "web_search"?, "web_search_name"?, "context_window"?, "compact_percent"?, "reasoning_efforts"?}` | 201,返回新的列表。第一个模型会让服务器变得可用;后续模型供 `PATCH /settings` 选择。写入配置文件,键名与终端 `/config add` 一致。`web_search` 让供应商替模型联网搜索;DeepSeek 模型没有 `anthropic` 时会被拒绝,拼错的键返回 `422`。 |
| `PATCH` | `/models/{name}` | `POST /models` 接受的任意字段 | 新的列表。未给出的键保持不变;没给新 token 就保留旧的。值为 `null` 的键会从条目里删掉(`model` 和 `token` 除外):`"temperature": null` 回到提供商自己的默认值,`"anthropic": null` 把这个标记从文件里删掉,而不是留下 `anthropic = false`。 |
| `DELETE` | `/models/{name}` | — | 剩下的模型。最后一个不能删(`400 invalid`):client 至少需要一个。 |
| `GET` | `/settings` | — | `{"model","effort","efforts","permission","permissions","harness"}`;改动过压缩点的 `PATCH` 之后还会带 `"unsaved"`(见下)。 |
| `PATCH` | `/settings` | `{"model"?, "effort"?, "permission"?, "harness"?, "compact_percent"?}` | 更改后与 `GET /settings` 相同;至少给一个字段。`permission` 是 `deny`、`ask`、`safe` 或 `full`(`auto` 是 `full` 的旧名,会按 `full` 返回);`harness` 从下一次 prompt 起开启或关闭 just-in-time 工具 harness。`compact_percent` 大于 0、至多 100,从下一次请求起生效并写入配置文件;文件写不进去时,返回里带 `"unsaved": "<原因>"`,改动只在本次运行有效。有 run 在进行时,移动 `compact_percent` 会返回 `409`,其他字段不会。 |
| `GET` | `/plugins` | — | `{"loaded": [...], "failures": [...], "entries": [{"name","origin","builtin","enabled","failure","setting","switchable","why"}]}`：名字、失败原因，以及面板会展示的每一条——其中也包括开关动不了的行（编译进程序却加载失败的、配置文件攥着的、整组关掉的），`switchable` 和 `why` 说的就是这些。`origin` 是发行包的名字，开关就用它写；`enabled` 说的是**下次启动**是否做它的活；`setting` 是决定内置插件的配置键（`"skills.enabled"`），装进来的为空。没有这种键的内置插件根本不会列出来。 |
| `PUT` | `/plugins/{name}` | `{"enabled": true\|false}` | 这个插件，按列表现在显示的样子。运行中的服务器不会加载或卸载任何东西：开关在进程启动时读一次，想立刻生效就重启服务器。装进来的插件记在插件开关文件里，编译进程序的写进服务器的配置文件；本机没有的名字会被拒绝（`400 invalid`）。 |
| `GET` | `/commands` | — | `{"commands": [{"name", "summary", "when_busy", "subcommands"}]}` |
| `POST` | `/commands/{name}` | `{"argument"}` | `{"message", "notification", "prompt", "shown"}` —— 如果有 `prompt`，客户端用它发下一个 `POST /prompts`，`shown` 作为对话里显示的那一行 |
| `GET` | `/mentions?query=&limit=50` | — | `{"mentions": [{"token","kind","name","description"}]}`:`@` 能指向的文件、skills 和插件资源。 |
| `POST` | `/doctor` | `{"timeout"?: 30}` | `{"checks": [{"model","model_id","ok","seconds","detail","input_tokens","output_tokens"}]}`:对每个配置的模型各问一个短问题。 |

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
| `GET` | `/sessions?limit=20` | — | `{"sessions": [{"id","title","created_at","updated_at","current","running"}]}`,最近活动的在前。`running` 为 true 表示该会话里正有运行在跑(当前会话,或被放到一边的会话)。 |
| `POST` | `/sessions` | `{"title"?}` | 201,新会话,并成为当前会话。 |
| `GET` | `/sessions/current` | — | `{"id","title","locked","usage"}` |
| `POST` | `/sessions/{id}/open` | — | 打开的会话,成为当前会话;不存在时 404。 |
| `POST` | `/sessions/current/rename` | `{"title"}` | 重命名后的会话。 |
| `POST` | `/sessions/current/name` | — | 让模型给对话命名,返回新名字。 |
| `POST` | `/sessions/current/fork` | — | 新会话,延续这个对话的上下文。 |
| `POST` | `/sessions/current/compact` | — | `{"applied","summary","compressed","kept"}`;没有可折叠内容时 `applied:false`。 |
| `GET` | `/sessions/current/context` | — | `{"window","used","measured_by","shares","partial","from_provider"}`,测量前为 `null`。 |
| `GET` | `/sessions/current/history` | `?full=true`(可选) | `{"messages": [{"role","text","tool_calls","ok","images"}]}`:模型正在使用的消息;带 `full=true` 时返回整段对话,每次压缩的摘要(角色 `summary`)出现在压缩发生的位置。 |
| `GET` | `/sessions/current/export` | — | 对话导出成独立的 HTML 页面(`text/html`,按下载处理)。 |
| `POST` | `/sessions/current/ask` | `{"question","timeout"?}` | `{"answer"}`;在旁边回答,不进入对话。运行进行中返回 409。 |
| `POST` | `/sessions/current/ask/stream` | `{"question","timeout"?}` | 同样的旁路提问,答案以流的形式返回,帧的格式与 `/prompts` 相同:先是 `text_delta` 事件,再是 `result`(出错是 `error`,被 `/runs/cancel` 停止是 `cancelled`)。回答期间这个提问占用运行位。运行进行中返回 409。 |
| `GET` | `/sessions/current/stats` | — | `{"id","entries","requests","input_tokens","output_tokens","cache_read_tokens","reasoning_tokens","total_tokens","cache_share"}`,还没存任何东西时为 `null`:即 `/resume` 的一行。 |
| `GET` | `/sessions/stats?ids=a,b` | — | 指定会话的 `{"stats": [...]}`,形状相同;最多 200 个 id。 |
| `GET` | `/sessions/current/self-compaction` | — | `{"choice": true\|false\|null, "effective": bool}` |
| `PUT` | `/sessions/current/self-compaction` | `{"choice": true\|false\|null}` | 保存到会话后的同样结构;从下一次请求起生效。 |
| `GET` | `/usage` | — | 当前会话的累计用量。 |
| `GET` | `/usage/ledger` | — | `{"sessions", "models", "days", "total"}`:工作区花了多少,和终端 `/usage` 页面一致。 |

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
| `GET` | `/runs/current` | — | `{"running", "pending"}`:当前会话里是否有运行在跑、它在等什么。 |
| `GET` | `/messages` | — | `{"messages": [{"id","sender_id","sender","text","via","hops"}]}`:其他会话发给当前会话、还没回答的消息,最早的在前。 |
| `POST` | `/messages/{id}` | — | `text/event-stream`,帧与 `/prompts` 相同:把这条消息当一轮来回答。它不在等待时返回 404。 |
| `POST` | `/sessions/current/send` | `{"to","text"}` | `{"to","disposition"}`:给另一个 ZettCode 会话(handle 或 id)发消息,内容视为读者本人所写;`disposition` 为 `started` 或 `queued`。没有人能收到时返回 404 `unreachable`。 |
| `GET` | `/runs/resumable` | — | `{"resumable","kind","description"}` |
| `POST` | `/runs/approvals` | `{"call_id","approve","remember"?}` | `{"resolved"}`,运行是否正在等这个调用。 |
| `POST` | `/runs/questions` | `{"call_id","answer"}` | `{"resolved"}`;`"answer": null` 表示拒绝回答。 |
| `POST` | `/runs/steer` | `{"text", "images"?, "mentions"?}` | `{"steered", "text"}`：没有运行接收时 `steered` 为 false；`text` 是随后 `steered` 事件带的文字（带图片或 `@` 引用的消息，按构造后的文字报告），没有收下时为 null。 |
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
| `questions` | `decline`(默认)告诉模型没人在;`ask` 把问题发到流里并一直等待回答。 |
| `timeout` | 整轮运行最多多少秒,或 `null`。 |
| `answer_timeout` | `ask` 的审批等待客户端多少秒,超时后取安全默认值(拒绝)。问题没有超时,会一直等回答。 |
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
