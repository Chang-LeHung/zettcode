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
| `--system TEXT` | 设定角色的 system prompt，会加在它每次请求的 system prompt 里（默认没有）。 |
| `--permission LEVEL` | `safe`、`deny` 或 `full`（默认）。没有 `ask`。 |
| `--resume SESSION` | 接着一个已存会话，而不是从空会话开始。 |
| `--json` | 把同样的信息打成 JSON。 |

没有人批准 daemon 的命令，所以它的 shell 级别很要紧：

- `full`（默认）：每条命令都以你的权限运行，没有沙箱，网络可用。只在你愿意把 shell 交给它的工作区里用。
- `safe`：每条命令都在沙箱里跑，只能写工作区和临时目录；网络跟 `[shell] network` 走（默认关闭）。
  `pip install --user`、SSH 推代码和 `gh` 都会失败。
- `deny`：完全不给 shell，它只读文件、改文件、说话。

daemon 的对话就是一个普通的已存会话。`daemon kill` 之后可以用 `zettcode resume <id>` 接着手动聊。

## 给它一个角色

```bash
zettcode daemon spawn --name reviewer --permission safe \
  --system "你评审改动。你从不改文件：你按文件、按行号说出要改什么。"
```

`--system` 把这段文字加在 daemon 每轮回答的 system prompt 里（它派出的子 agent 用的是子 agent 自己的 prompt），于是
一个后台 agent 是评审者、另一个是构建者，不用在每条消息里再提醒一次。它属于这个 daemon，而不属于会话：`daemon list`
把它显示为 `role`，在同一个会话上的每次重启都会保留它——`daemon update --permission`、broker 重启、`/hub`、网关的
Restart——而 `zettcode resume <id>` 打开同一段对话时用的是平常的 prompt，没有这个角色。要换角色，停掉它再用它的会话重新起：

```bash
zettcode daemon stop <id>
zettcode daemon spawn --resume <id> --system "你负责构建。改完先跑测试，再宣布完成。"
```

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
列表里都显示为 `dead`，在任何一处都能再启动。只有 `kill` 和 `delete` 会删掉记录。

![`/hub` 的 Daemons 页：三个 daemon 的状态、多久之前、标题、模型和工作区，下面是作用于标记那一行的按键](/screens/hub.svg)

`/hub` 就是同一份列表，不用离开对话：`Tab` 在 Graph、Sessions、Daemons、History 之间走，标记那一行认四个键。

| 按键 | 在 Daemons 页上 |
| --- | --- |
| `Enter` | 启动；离线的会恢复它原来的会话。 |
| `t` | 重启——正在跑的会先停掉。 |
| `s` | 停掉但**保留**记录，显示为 `idle`。 |
| `d` | 删掉记录**连同对话**。要按两次：第一次只是问，中间按别的键就作废。 |

### Graph 页

它画的是最近发生的事情：一个会话一个方框，互相发过消息的两个之间有一条线，线上的数字是最近这一段消息里它们说了
多少句——先数最新的 64 条，不够填满这张图就扩到 128、192，依此类推，最多到 1024 条。两个人在更长的时间里说过
更多的话时，总数会用灰色写在数字旁边（版面不够时这一行会省略）。

所以这一段里一句话都没说过的会话不会画出来：一周都没人写过消息的 daemon 还留在其他页的记录里，这里没有方框；
而此刻正在干活的会话会排在聊得多的人前面拿到方框——最多占半张图，这样即使同时有很多个在干活，对话本身仍在图上。
第二行说明 broker 一共记过多少会话、这里显示了几个（`9 of 208 nodes`）。方向键走到最近的方框并让其余变暗，
`Esc` 取消选中，`r` 重新读一遍机器。

`/` 在本页搜索，`r` 重新读一次机器，`Esc` 先清空搜索再关页面。

`d` 删除（要按两次）。

`stop` 和 `kill` 会拒绝正在跑一轮的 daemon；加 `--force` 才能照样停。换模型或级别从下一轮生效。
换权限会重启进程，所以那一轮会丢。运行中的 daemon 拒绝 `--title`，因为跑着的进程持有会话的名字。

## 下一步

- [会话之间互发消息](/zh/guide/messaging)：消息、群和 broker。
- [网页网关](/zh/guide/gateway)：在页面里起、看、停 daemon。
- [Codex 与 Claude Code](/zh/guide/code-agents)：其他厂商的 agent。
