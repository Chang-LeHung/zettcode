# 后台 agent

daemon 是一个没人守在键盘前的会话。它在你关掉终端后仍在自己的工作目录里工作，你用发消息的方式联系它。
适合那些该在你旁边发生、而不是挡在你前面的活：一个读 diff 的评审者，一个在你继续写代码时跑失败测试的探索者。

## 起一个

```bash
zettcode daemon spawn --name builder --title "tool builder" --permission safe
```

它会打印 session id。`spawn` 一返回，daemon 就能收到消息。

| 选项 | 作用 |
| --- | --- |
| `-w DIR` | 在哪个目录工作（默认当前目录）。 |
| `--model NAME` | 用 `zettcode daemon model` 列出的模型（默认配置里的第一个）。 |
| `--effort LEVEL` | 推理级别（默认取模型接受范围的中点）。 |
| `-n`、`--name LABEL` | 给 `daemon list` 看的标签。 |
| `--title TEXT` | 会话的名字；不给就由它第一次回答后自己起。 |
| `--permission LEVEL` | `safe`、`deny` 或 `full`（默认）。没有 `ask`。 |
| `--resume SESSION` | 接着一个已存会话，而不是从空会话开始。 |
| `--json` | 把同样的信息打成 JSON。 |

没有人批准 daemon 的命令，所以它的 shell 级别很要紧：

- `full`（默认）：每条命令都以你的权限运行，没有沙箱，网络可用。只在你愿意把 shell 交给它的工作区里用。
- `safe`：每条命令都在沙箱里跑，只能写工作区和临时目录；网络跟 `[shell] network` 走（默认关闭）。
  `pip install --user`、SSH 推代码和 `gh` 都会失败。
- `deny`：完全不给 shell，它只读文件、改文件、说话。

daemon 的对话就是一个普通的已存会话。`daemon kill` 之后可以用 `zettcode resume <id>` 接着手动聊。

## 和它说话

在提示里用 `@` 点它的名字，或者由另一个会话的模型用 `send_message(to="<id>", message="...")` 发送。
在 shell 里，`zettcode daemon prompt <id> "..."` 不打开会话就发一条消息；daemon 不会回复 shell 发送者，
但这一轮会存在会话里。

daemon 一次处理一条消息。它忙的时候最多排 64 条，之后合成一轮跑，每条上面有一行说明是谁发的；超过 64 条时由 broker
保管，有空位再投递。它用 `send_message` 回答，所以问它的会话会把回答当成一条独立的消息收到。因超时、连接断开、
限流这类可能过去的原因为失败的一轮，会从断点重试，最多三次。

## 管理

| 命令 | 作用 |
| --- | --- |
| `zettcode daemon list` | 这台机器上的每个 daemon：状态、工作区、模型、上下文、shell。 |
| `zettcode daemon log <id>` | 它自己记的最后几行；`-n N` 指定行数。 |
| `zettcode daemon stop <id>` | 停掉它并保留记录（显示为 `dead`）；`spawn --resume` 可以再起。 |
| `zettcode daemon kill <id>` | 停掉它并删掉记录。会话留着。 |
| `zettcode daemon delete <id>` | 删掉记录**和**对话。无法撤销。 |
| `zettcode daemon update <id>` | 改 `--model`、`--effort`、`--name`、`--title` 或 `--permission`。 |
| `zettcode daemon model` | 列出 `spawn --model` 接受的模型；`--json` 给脚本用。 |

daemon 以其他方式退出（比如重启电脑、Ctrl-C）时，记录也会保留：它在 `daemon list`、`/hub` 的 Daemons 页和网关的聊天
列表里都显示为 `dead`，在任何一处都能再启动。只有 `kill` 和 `delete` 会删掉记录。在 `/hub` 里，`s` 停止、`t` 重启、
`d` 删除（要按两次）。

`stop` 和 `kill` 会拒绝正在跑一轮的 daemon；加 `--force` 才能照样停。换模型或级别从下一轮生效。
换权限会重启进程，所以那一轮会丢。运行中的 daemon 拒绝 `--title`，因为跑着的进程持有会话的名字。

## 下一步

- [会话之间互发消息](/zh/guide/messaging)：消息、群和 broker。
- [网页网关](/zh/guide/gateway)：在页面里起、看、停 daemon。
- [Codex 与 Claude Code](/zh/guide/code-agents)：其他厂商的 agent。
