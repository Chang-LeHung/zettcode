---
title: TypeScript 客户端
---

# TypeScript 客户端

`zettcode-client` 是服务器的 TypeScript 客户端。没有运行时依赖,需要 Node 20+(或任何带 `fetch` 的环境),覆盖整个
API:运行中的 prompt 流、会话、模型、审批、提问、steer、取消与继续。

```bash
npm install zettcode-client
```

## 一次运行

```ts
import { ZettCodeClient } from "zettcode-client";

const client = new ZettCodeClient({ baseUrl: "http://127.0.0.1:3290", token: process.env.ZETTCODE_TOKEN });

const run = client.prompt("修复失败的测试", {
  approvals: { mode: "ask" },
  onApproval: async (request) => confirm(`运行 ${request.command}?`),
});

for await (const frame of run) {
  if (frame.event === "event" && frame.data.type === "text_delta") {
    append(frame.data.text);
  }
}
const result = await run.result;
```

`run` 是可异步迭代的帧序列,同时带一个 `result` promise。两者可以分开使用:帧到达时会排队,所以只 `await
run.result` 就是非流式用法;结果已知之后再迭代,会把已到达的帧按顺序读出来。

## 回答

需要回答的运行在服务器上挂起。客户端可以用 handler 回答,答案会在流继续之前发出去:

```ts
client.prompt("让测试通过", {
  approvals: { mode: "ask" },
  questions: "ask",
  onApproval: (request) => request.command.startsWith("pytest"),
  onQuestion: (request) => request.options[0] ?? null,   // null 表示拒绝回答
});
```

也可以按 `call_id` 手动回答:

```ts
await run.approve("call-1", true);       // 或 run.approve(callId, false)
await run.answer("q-1", "sqlite");
await run.steer("顺便把文档也更新了");
await run.cancel();
```

`client.runState()` 说明是否有运行在跑、它在等什么 —— 重新加载的编辑器可以据此重新展示问题。

## 其余 API

| 客户端方法 | 端点 |
| --- | --- |
| `health()` | `GET /health` |
| `models()`、`settings()`、`updateSettings(change)`、`plugins()` | `/models`、`/settings`、`/plugins` |
| `listSessions(limit)`、`createSession(title?)`、`currentSession()` | `/sessions`、`/sessions/current` |
| `openSession(id)`、`renameSession(title)`、`nameSession()`、`forkSession()` | `/sessions/...` |
| `compactSession()`、`context()`、`history()`、`exportSession()`、`ask(question)` | `/sessions/current/...` |
| `usage()`、`usageLedger()`、`sessionStats(ids?)` | `/usage`、`/usage/ledger`、`/sessions/.../stats` |
| `selfCompaction()`、`setSelfCompaction(choice)`、`mentions(query)`、`doctor(timeout)` | `/sessions/current/self-compaction`、`/mentions`、`/doctor` |
| `prompt(text, options)`、`resume(options)` | `POST /prompts`、`POST /runs/resume` |
| `runState()`、`resumable()`、`approve()`、`answer()`、`steer()`、`cancelRun()` | `/runs/...` |

## 错误

- `ZettCodeError` —— HTTP 失败:`code`(`busy`、`not_found`、`invalid` 等)、`status`,以及服务器给的消息。
- `RunFailedError` —— 流打开之后运行失败。
- `RunCancelledError` —— 运行被 `cancel()`、`abort()` 或服务器停止。

## 代码位置

客户端在同一个仓库的
[`clients/typescript`](https://github.com/Chang-LeHung/zettcode/tree/main/clients/typescript),紧挨着它调用的服务器。
用 `make client` 跑测试:先编译源码,再对着真实的本地 HTTP 服务器说话,包括被拆开的 SSE 块。
