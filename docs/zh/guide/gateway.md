# 网页网关

`zettcode gateway` 为这台机器上的 daemon、会话和群提供一个网页。它是一个页面，不是 agent：终端留在代码所在的地方，
页面跟着你走，手机上也行。

## 运行

```sh
zettcode gateway                 # 在前台运行，Ctrl-C 结束
zettcode gateway start           # 转入后台，打印地址
zettcode gateway stop            # 停掉正在运行的那个
zettcode gateway restart         # 先停，再启动
```

默认监听 `127.0.0.1:8765`；`--port` 和 `--host` 可以改。`start` 把输出写进 `~/.zettcode/gateway`（或 `--directory`）
下的 `gateway.log`，等页面能访问才返回。`restart` 沿用正在运行那个网关的设置，除非你带上参数。

## 登录与权限

| 设置 | 作用 |
| --- | --- |
| 不给 `--token` | 没有登录，页面只监听本机。 |
| `--token`、`$ZETTCODE_GATEWAY_TOKEN` | 要你输入一次这个 token，之后保留 cookie。 |
| `--host 0.0.0.0` | 必须有 token。页面是明文 HTTP：请放在 TLS 后面。 |
| `--read-token` | 第二个 token：什么都能看，什么都改不了。 |
| `-r`、`--root` | 限定 daemon 可以在哪些目录里启动。 |
| `--no-full` | 不允许以 `full` shell 级别启动 daemon。 |

只读 token 交给只需要看、不需要操控的人。桌面端和安卓端在网关自己的 origin 上加载这个页面，不需要额外设置。

## 页面能做什么

- **Chats** 列出 daemon 和会话，在线的在前，群聊在上面。打开一个就能读、看谁在线、跟着写。页面发出的消息等对方当前
  请求结束再处理，不会转向。
- **New** 起一个 daemon；装了 `zettcode[code-agents]` 时也能起 Codex 或 Claude Code。停掉的 daemon 可以用原来的目录、
  模型、级别和标签在同一段对话上重新启动，也可以改过再起。
- 和 daemon 的聊天可以带图片：每条最多四张，每张 4 MiB、合计 8 MiB，前提是 daemon 的模型能读图片。broker 不保存
  图片，历史里只记这条消息带过图。
- **Config → Models** 增加、编辑、删除 `~/.zettcode/config.toml` 里的模型，和 `/config` 一样。API 密钥只写不读：
  页面从不显示已保存的密钥。
- **Logs** 把 daemon 的日志按回合和工具列出来，可以只看工具或只看问题。
- **Graph** 把会话画成节点、群画成区域，每条消息画成飞向收件人的光点。见[关系图](#the-graph)。

## 关系图 {#the-graph}

![关系图页面：上面是一个三个会话的群组，下面是一个两个会话的群组，四个会话在群外，消息在它们之间飞](/demo/graph.gif)

群的成员落在群的轮廓里，`#名字` 的标签贴在轮廓外侧；不属于任何群的会话单独站在环上。

鼠标停在节点上看标题、工作区、收发数和所属的群，停在连线上看这两个会话之间的消息，停在光点上看它送的那条消息。用 Tab 停在节点上，
节点卡片一样会弹出来。群的卡片里列出成员。

旁边的 **Live messages** 是同一批消息的列表，点一条可以重播它。

**Replay** 按存下来的历史重画你选的一段时间，不会重新发送任何东西。空闲的时段默认跳过，**Back to live** 回到实时。
一个时间段超过 20,000 条消息时，保留最新的部分并给出提示。

## 监控

`GET /metrics` 以 Prometheus 的文本格式返回指标，可以接仪表盘或告警；只读 token 就够用。
网关还会在自己的目录里往 `audit.jsonl` 追加一行 JSON，记录每次登录、每次被拒的尝试和每次修改：时间、token 种类、
地址、路由和结果，从不记录 token 或消息正文。文件到 5 MB 就轮转。

## 下一步

- [会话之间互发消息](/zh/guide/messaging)：消息、群和 broker。
- [后台 agent](/zh/guide/daemons)：daemon 是什么。
- [桌面端与手机端](/zh/guide/app)：把网关放进一个窗口或一台手机。
