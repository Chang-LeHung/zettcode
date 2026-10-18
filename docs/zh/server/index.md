---
title: ZettCode server
---

# ZettCode server

`zettcode-server` 把 ZettCode 编程代理放到 HTTP 后面。它跑的是和终端、SDK 同一个代理 —— 同样的工具、插件、MCP 服务、
skills、项目指令和会话存储 —— 所以从 HTTP 开始的对话可以在终端里接着开,反过来也一样。

它只是一层薄壳:每个端点都驱动 [`zettcode.sdk`](/zh/sdk/),再由 SDK 驱动已发布的 `zett-agent` 运行时。服务器自己没有
模型循环、工具和会话格式。

## 安装与运行

```bash
uv tool install zettcode-server
zettcode-server --workspace ~/projects/api --port 3290
```

```text
zettcode-server 0.1.0 (zettcode 0.1.8) · http://127.0.0.1:3290 · workspace /home/you/projects/api · permission deny · token off
```

默认只绑定 **127.0.0.1**。在 `--host` 指定之前,别的机器访问不到;一旦对外开放,就应该同时给出 token。

| 选项 | 含义 |
| --- | --- |
| `-w`, `--workspace DIR` | 代理工作的目录。一个进程服务一个工作区,因为 SDK 使用进程的工作目录。 |
| `--host`, `--port` | 监听地址;默认 `127.0.0.1:3290`。 |
| `--token` | 除 `/health` 外每个端点要求的 Bearer token;默认取 `$ZETTCODE_SERVER_TOKEN`。 |
| `--permission {deny,ask,safe,auto}` | 运行开始时的 shell 权限,默认 `deny`;客户端可以按请求更改。 |
| `--model`, `--effort` | 第一次运行使用的模型和推理强度。 |
| `--config FILE` | 使用指定的配置文件代替 `~/.zettcode/config.toml`。 |
| `--log-level` | uvicorn 的日志级别。 |

::: warning 一个工作区,一个进程
服务器只服务启动时所在的工作区。一个进程里跑两个工作区是冲突而不是特性:代理的工具按进程工作目录解析路径。
第二个项目就再起一个服务器。
:::

## 第一个请求

```bash
curl http://127.0.0.1:3290/health
```

```json
{"status": "ok", "version": "0.1.0", "workspace": "/home/you/projects/api", "session": "01a15…", "busy": false}
```

发一个 prompt 并观察它:

```bash
curl -N -X POST http://127.0.0.1:3290/prompts \
  -H 'content-type: application/json' \
  -d '{"text": "总结一下 README", "approvals": {"mode": "deny"}}'
```

```text
event: event
data: {"type":"text_delta","text":"README 说明了"}

event: event
data: {"type":"tool_started","call_id":"call-1","name":"read_file","arguments":{"path":"README.md"}}

event: result
data: {"text":"README 说明了 …","session_id":"01a15…","usage":{…},"tools":[…],"stop":null}
```

每一帧的含义见[事件流](/zh/server/events),端点清单见 [API 参考](/zh/server/api),
[TypeScript 客户端](/zh/server/typescript)把这一切包好,供编辑器或 Node 程序使用。

## 客户端能做什么

- **运行 prompt** 并流式读取事件;从中断的地方继续一个请求。
- **在运行中回答代理**:批准或拒绝 shell 命令、回答模型提出的问题,或者用新指令 steer 这次请求。
- **管理会话**:列出、打开、新建、重命名、fork、压缩、导出成网页、读取历史。
- **在运行之间切换**模型、推理强度和权限级别。
- **测量**:token 用量、上下文报告、已加载的插件。

可交互这一点才让它和终端对等:需要回答的运行处于挂起状态,而不是被猜一个答案。见
[回答一个运行](/zh/server/events#answering-a-run)。

## 让别的工具连上来

API 就是普通的 HTTP 和 JSON,编辑器扩展、CI 任务或脚本都可以直接使用。不只在 loopback 上时给它一个 token,并按
`text/event-stream` 读取:

```ts
const response = await fetch("http://127.0.0.1:3290/prompts", {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ text: "修复失败的测试", approvals: { mode: "ask" } }),
});
const reader = response.body!.getReader();
// 每个 SSE 块以空行结束;从中解析 `event:` 和 `data:`。
```

## 安全

- **默认只监听 loopback**,启动服务器不会把 shell 暴露到网络上。
- **shell 命令默认 `deny`**:prompt 不说明怎么回答命令之前,什么都跑不了。
- **token 只有一行**:`--token` 或 `$ZETTCODE_SERVER_TOKEN`,常量时间比较,除 `/health` 外都要它。它是明文 HTTP 上的
  Bearer token,客户端不在同一台机器时请走隧道或终止 TLS 的反向代理。
- **同时只有一个客户端**:一轮运行进行中再发 prompt 会得到 `409 busy`,而不是把两条请求交错进同一个会话。
