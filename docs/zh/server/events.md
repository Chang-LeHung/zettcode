---
title: 事件流
---

# 事件流

`POST /prompts` 和 `POST /runs/resume` 返回 `text/event-stream`:运行的事件按发生顺序送到,最后是一帧终结帧。
每一帧有一个名字和一行 JSON:

```text
event: event
data: {"type":"text_delta","text":"已经给 "}

event: event
data: {"type":"tool_started","call_id":"call-1","name":"replace_in_file","arguments":{"path":"src/users.py"}}

event: result
data: {"text":"已经加上分页 …","session_id":"01a15…","usage":{…},"tools":[…],"stop":null}
```

空行结束一帧,流在终结帧之后关闭。名字只有三种:

| 事件名 | 内容 | 含义 |
| --- | --- | --- |
| `event` | 下面列出的某一种 | 运行中发生了某件事。 |
| `result` | 运行结果 | 模型结束;这就是非流式客户端会拿到的返回值。 |
| `error` | `{"error","message"}` | 流打开之后运行失败。 |
| `cancelled` | `{"type":"cancelled"}` | 运行被停止(`/runs/cancel`,或连接断开)。 |

## 事件类型

| `type` | 字段 | 含义 |
| --- | --- | --- |
| `text_delta` | `text` | 答案的一段,追加即可。 |
| `reasoning_delta` | `text` | 模型推理的一段,前提是 provider 提供。 |
| `reasoning_started` | — | 一段推理开始。 |
| `reasoning_finished` | — | 这段推理结束,无论模型接着回答还是调用工具。 |
| `tool_started` | `call_id`, `name`, `arguments` | 工具调用开始。 |
| `tool_finished` | `call_id`, `name`, `output`, `ok`, `skipped` | 工具结束,成功或失败;`skipped` 表示被 steer 取代。 |
| `approval_requested` | `call_id`, `command`, `work_dir`, `approved` | 模型想运行一条 shell 命令。见下文。 |
| `question_asked` | `call_id`, `question`, `options`, `allow_multiple`, `answered` | 模型问了问题。 |
| `usage_updated` | `usage` | 一次模型调用后会话的累计用量。 |
| `compaction_started` | — | 正在总结对话。 |
| `compaction_delta` | `text` | 正在写的总结的一段,追加即可。 |
| `compaction_finished` | `applied`, `summary` | 总结结束。 |
| `model_stopped` | `reason`, `message` | 某一步不是因为正常结束而停止:`refusal`、`max_output`、`context_full`、`paused`、`interrupted`、`other`。 |
| `steered` | `text` | 通过 `/runs/steer` 发的消息到达了正在运行的请求。 |
| `steering_finished` | — | 接收了 steer 消息的请求已经回答了它。 |
| `steering_interrupted` | `text` | 一条 steer 消息在请求处理它之前被更新的一条取代。 |
| `notice` | `text`, `level` | 不属于答案的消息,比如某个 MCP 服务正在启动或连不上,或者等待回答超时。`level` 为 `"info"` 表示进度,`"warn"` 表示你可能需要处理的事;没带 `level` 的帧按进度处理。 |
| `finished` | `text` | 结果之前运行的最后一个事件。 |
| `event` | `name` | 服务器不认识的事件;保留而不是丢弃,这样新版本 SDK 不会看起来像什么都没发生。 |

## 回答一个运行 {#answering-a-run}

需要回答的运行会**挂起**,而不是猜一个答案。`approvals.mode: "ask"` 时,shell 命令以 `approval_requested` 帧到达,
运行等待;`questions: "ask"` 时,问题以 `question_asked` 帧到达,运行等待。回答是第二个请求,这就是一个只有单向连接
的客户端也能双向驱动的原因:

```bash
# 终端 A:流停在这一帧之后
event: event
data: {"type":"approval_requested","call_id":"call-1","command":"pytest -q","work_dir":"clients/web","approved":null}

# 终端 B:回答
curl -X POST http://127.0.0.1:3290/runs/approvals \
  -H 'content-type: application/json' \
  -d '{"call_id": "call-1", "approve": true, "remember": true}'
```

```json
{"resolved": true}
```

- `work_dir` 是命令实际运行的目录(调用没有指定时是 `null`),要告诉用户「在哪运行」的客户端读这个字段。
  「总是允许」记住的仍然只是命令文本本身,所以记住过的命令在别的目录里再出现时依然免问。
- 用 `POST /runs/questions` `{"call_id": "...", "answer": "sqlite"}` 回答问题;`null` 表示拒绝回答。
- 运行没有在等这个调用时(已经回答过,或者运行已经结束),`resolved` 为 `false`。
- 审批最多等 `answer_timeout` 秒(默认 300),之后取安全默认值:拒绝命令,并用一个 `notice` 帧说明。
  问题没有超时:它一直等你回答,直到运行被取消或停止。
- `GET /runs/current` 说明在等什么,重连的客户端可以据此重新展示:

```json
{"running": true, "pending": {"kind": "approval", "call_id": "call-1", "command": "pytest -q", "work_dir": "clients/web", "remember_supported": true}}
```

帧里的 `approved` 是 `null`,因为帧本身是在提问,答案在 POST 里。用 `deny`、`auto` 或 `commands` 时,规则在帧发出前
就回答了,`approved` 是 `true` 或 `false`。

## Steer、停止、继续

| 调用 | 作用 |
| --- | --- |
| `POST /runs/steer` `{"text": "顺便把文档也更新了"}` | 运行放下手头的事，把这条消息考虑进去。没有运行在跑时返回 `{"steered": false}`；否则 `text` 是 `steered` 事件将携带的文字。`images` 和 `mentions` 的用法和提示词一样。 |
| `POST /runs/cancel` | 停止运行;它的流以 `cancelled` 结束。断开连接效果相同。 |
| `GET /runs/resumable` | 请求被中断时返回 `{"resumable": true, "kind": "error", "description": "The provider dropped the connection"}`。 |
| `POST /runs/resume` | 继续它,流的形式和 `/prompts` 完全一样。没有可继续的内容时返回 `409 nothing_to_do`。 |

## 一个客户端循环

```ts
const response = await fetch(`${base}/prompts`, {
  method: "POST",
  headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
  body: JSON.stringify({ text, approvals: { mode: "ask" }, questions: "ask" }),
});
for await (const frame of frames(response.body!)) {
  switch (frame.event) {
    case "event":
      handleEvent(frame.data);
      if (frame.data.type === "approval_requested") {
        const approve = await askTheUser(frame.data.command);   // 编辑器里的对话框
        await fetch(`${base}/runs/approvals`, {
          method: "POST",
          headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
          body: JSON.stringify({ call_id: frame.data.call_id, approve }),
        });
      }
      break;
    case "result":
      return frame.data;
    case "error":
      throw new Error(frame.data.message);
  }
}
```

`frames` 就是 SSE 解析:按空行切块,取 `event:` 名字,把 `data:` 行拼起来。这里不需要浏览器,Node 扩展把
`response.body` 当成异步可迭代对象读同样的流即可。
