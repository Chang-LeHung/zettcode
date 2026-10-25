# 后台 agent

daemon 是一个没人守在键盘前的会话。它在自己的工作目录里运行，终端关掉也继续活着；找到它的方式和找到别的会话一样：另一个 agent 用 `send_message` 给它发消息，它做完之后回复。

它适合那种应该在你旁边发生、而不是挡在你前面的工作。比如你刚写完代码，让一个评审 agent 去读 diff；或者你继续改代码，让另一个 agent 去跑一遍失败的测试。每个 daemon 都是一个可以起、可以列、可以停的会话：

```bash
zettcode daemon spawn --model gpt-5 --effort high
zettcode daemon list
zettcode daemon kill 01a1726a-3109-75a7-9285-390d9e381111
```

## 起一个

`zettcode daemon spawn` 在当前目录起一个后台 agent，并打印它的 session id：

```
session  01a1726a-3109-75a7-9285-390d9e381111
workspace /Users/me/projects/api
model    gpt-5 · effort high

send_message(to="01a1726a-3109-75a7-9285-390d9e381111", message="...")
```

| 选项 | 作用 |
| --- | --- |
| `-w DIR` | 在哪个目录工作（默认当前目录） |
| `--model NAME` | 用哪个模型（默认配置里的第一个） |
| `--effort LEVEL` | 推理级别（默认模型自己的） |
| `--resume SESSION` | 接着一个已存会话，而不是从空会话开始 |
| `--json` | 把同样的信息打成 JSON，给脚本或 agent 读 |

`spawn` 在 daemon 能被找到之后才返回，所以打印出来的 id 立刻就能发消息。起不来的话什么都不会留下，原因会打印出来（子进程最早写的那几行留在 `~/.zettcode/daemon/<workspace>/.spawn/` 里，读之前不删）。

::: warning daemon 以 full shell 权限运行
没有人在旁边点“允许”或回答问题，所以 daemon 从不提问：shell 命令用你自己的权限跑，模型提出的问题一律被拒绝。只在你愿意自己用 `--full` 的地方起它。
:::

它的会话是全新、空的 —— 需要什么由发送方告诉它。`--resume` 则接着一个已存会话，可以在被 kill 掉的 daemon 留下的工作上继续，也可以在你们已有的对话里做评审。这个会话就是普通会话，存储方式一模一样，所以 `daemon kill` 之后还能 `zettcode resume <id>` 接着手动聊。

## 列出和停止

`zettcode daemon list` 列出这台机器上所有 daemon，不管它在哪个目录：

```
SESSION                               WORKSPACE        MODEL  EFFORT  STATUS   FOR  TITLE
01a1726a-3109-75a7-9285-390d9e381111  ~/projects/api   gpt-5  high    idle     8m   Reviewer
01a1726b-2f41-75a7-9285-390d9e381112  ~/projects/web   gpt-5  low     working  2m   -
```

`STATUS` 是 `starting`（还没连上 broker）、`idle`、`working`、`stopping`，或者 `dead` —— dead 表示进程已经不在了（机器重启过，或者它崩了），用 `kill` 把条目清掉。`--json` 打同样的字段，方便程序读。

`zettcode daemon kill <session-id>...` 停掉每个 daemon 并删掉它的记录。会话本身留着，做过的事都在里面，之后可以在终端里打开。

## 和它说话

daemon 不接受输入，它的输入就是 `send_message` —— 来自另一个会话的 agent，或者来自终端里读者打的 `@`：

```
send_message(to="01a1726a-3109-75a7-9285-390d9e381111", message="看一下 src/api.py 的 diff，说你打算改什么。")
```

daemon 一次处理一条消息。忙的时候最多再排四条，再多就告诉发送方“忙”。它也用同样的方式回答 —— `send_message(to=<你的 session id>, ...)` —— 所以问它的 agent 会把回答当成一条消息收到。

daemon 不会自己退出，闲置几个小时也不会：不用了就用 `daemon kill` 停掉，否则它会一直在那里，被列出来，有人写就回答。

## 存在哪

```
~/.zettcode/sessions/<workspace>/<session-id>/    会话本身，和别的会话一样
~/.zettcode/daemon/<workspace>/<session-id>/
    state.json                                    pid、状态、模型、effort、开始时间
    heartbeat                                     每几秒写一次，证明还活着
    log                                           出错的地方，以及它跑过的工具
```

`~/.zettcode/daemon/<workspace>/workspace.txt` 记录这个目录对应哪个路径，和会话存储的做法一样。`kill` 除了停进程，只做一件事：删掉 `daemon/` 里这个会话的目录。
