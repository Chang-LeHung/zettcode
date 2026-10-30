---
title: TypeScript 客户端
---

# TypeScript 客户端

`zettcode-client` 是 [`zettcode-server`](/zh/server/) 的 TypeScript 客户端：用 HTTP 驱动编码 agent，可以在 Node、
VS Code 扩展，或任何有 `fetch` 的宿主里用。它没有任何运行时依赖，需要 Node 20+，覆盖整套 API——边跑边流的
prompt、会话、模型、审批、提问、插话、取消、用量和事件流。

```bash
npm install zettcode-client
```

这个包在同一个仓库的
[`clients/typescript`](https://github.com/Chang-LeHung/zettcode/tree/main/clients/typescript) 里，就在它调用的服务器
旁边。[VS Code 扩展](/zh/vscode/)直接打包它的源码，所以编辑器里的聊天和你的程序用的是同一个 wire client。

## 跑一个 prompt

```ts
import { ZettCodeClient } from "zettcode-client";

const client = new ZettCodeClient({ baseUrl: "http://127.0.0.1:3290", token: process.env.ZETTCODE_TOKEN });

const run = client.prompt("fix the failing test", {
  approvals: { mode: "ask" },
  onApproval: async (request) => confirm(`Run ${request.command}?`),
});

for await (const frame of run) {
  if (frame.event === "event" && frame.data.type === "text_delta") {
    append(frame.data.text);
  }
}
const result = await run.result;
```

`run` 既可以异步迭代出 frame，也带着一个 `result` promise。两者可以只用其一：frame 到达时排队，所以只
`await run.result` 就是不流式的用法；结果已知之后再迭代也不会重放。

## 回答一个 run

需要回答时服务器会挂起这个 run。客户端可以在 handler 里回答，答案会在流继续之前送回去：

```ts
client.prompt("make the tests pass", {
  approvals: { mode: "ask" },
  questions: "ask",
  onApproval: (request) => request.command.startsWith("pytest"),
  onQuestion: (request) => request.options[0] ?? null,   // null 表示拒绝
});
```

也可以按 `call_id` 手动回答：

```ts
await run.approve("call-1", true);       // 或 run.approve(callId, false)
await run.answer("q-1", "sqlite");
await run.steer("also update the docs");   // 返回运行用来报告它的文字，没人收下则为 null
await run.steer("look at this", { images: [{ data: base64, mediaType: "image/png" }], mentions: true });
await run.cancel();
```

`client.runState()` 说明现在在跑什么、在等什么，重新打开的编辑器靠它把问题再显示出来。

## 图片与历史

prompt 可以带上模型能看的图片，历史也会把这些图还回来，所以重新打开会话的客户端能显示当初附了什么：

```ts
await client.prompt("what is wrong here?", {
  images: [{ data: base64Png, mediaType: "image/png" }],
});

const messages = await client.session.history({ full: true });
for (const message of messages) {
  for (const picture of message.pictures ?? []) {
    show(`data:${picture.media_type};base64,${picture.data}`);
  }
  if (message.images > (message.pictures?.length ?? 0)) {
    show(`${message.images} more images, not stored`);
  }
}
```

`history()` 是模型当前工作的那批消息；`history({ full: true })` 是当时写下的整段对话，每次压缩的摘要都以
`summary` 消息留在它发生的位置。

## 配置一个模型

没有配置模型的服务器照样能回答，这样编辑器才能建一个：

```ts
const health = await client.health();      // { ready: false, models: 0, session: null, … }
if (!health.ready) {
  await client.addModel({ model: "gpt-5-mini", token: apiKey, display_model: "Fast" });
}
await client.updateModel("Fast", { context_window: 200_000 });   // token 会保留
await client.updateSettings({ model: "Fast" });                  // 下一个 prompt 用它
await client.updateSettings({ compact_percent: 70 });            // 窗口用到 70% 时压缩
```

`addModel` 写的就是 `/config add` 写的那条 `[[models]]` 条目；`removeModel` 不允许删掉最后一个。写不进文件的设置会
在 `unsaved` 里说明，并且只在本次运行里生效。

## 其余的 API

方法名就是 Python SDK 的名字、改成 camelCase，分组也一样（`client.sessions`、`client.session`）。两者不同的地方是因为 TypeScript 是在和服务器通信：
`session.info()` 读的是 Python 里作为属性的那些值，`sessions.open(id)` 返回会话的数据而不是句柄。

| 客户端方法 | 端点 |
| --- | --- |
| `health()` | `GET /health` |
| `models()`、`addModel(entry)`、`updateModel(name, changes)`、`removeModel(name)` | `/models`、`/models/{name}` |
| `settings()`、`updateSettings(change)`、`useModel(name)`、`useEffort(name)`、`usePermission(name)`、`useHarness(on)`、`plugins()`、`setPluginEnabled(name, enabled)`、`commands()`、`runCommand(name, argument?)` | `/settings`、`/plugins`、`/plugins/{name}`、`/commands`、`/commands/{name}` |
| `sessions.list({limit})`、`sessions.new(title?)`、`sessions.open(id)`、`sessions.latest()`、`session.info()` | `/sessions`、`/sessions/current` |
| `session.rename(title)`、`session.nameIt()`、`session.fork()` | `/sessions/current/...` |
| `session.compact()`、`session.context()`、`session.history({full})`、`session.export()`、`session.ask(question)`、`session.askStream(question)` | `/sessions/current/...` |
| `usage()`、`usageLedger()`、`sessionStats(ids?)` | `/usage`、`/usage/ledger`、`/sessions/.../stats` |
| `selfCompaction()`、`useSelfCompaction(choice)`、`mentions(query, {limit})`、`checkModels({timeout})` | `/sessions/current/self-compaction`、`/mentions`、`/doctor` |
| `prompt(text, options)` 或 `session.prompt(...)`、`session.resume(options)` | `POST /prompts`、`POST /runs/resume` |
| `messages()`、`relay(id)`、`send(to, text)` | `/messages`、`/sessions/current/send` |
| `runState()`、`session.resumable()`、`approve()`、`answer()`、`session.steer()`、`cancelRun()` | `/runs/...` |

## 错误

- `ZettCodeError` —— HTTP 失败：`code`（`busy`、`not_found`、`invalid` 等）、`status`，以及服务器给的消息。
- `RunFailedError` —— 流打开之后 run 失败了。
- `RunCancelledError` —— run 被 `cancel()`、`abort()` 或服务器停掉了。

## 测试

`make client` 会编译源码，并对着真实的本地 HTTP 服务器跑测试，包括被切开的 SSE 分片。
