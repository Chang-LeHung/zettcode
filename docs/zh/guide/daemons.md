# 后台 agent

daemon 是一个没人守在键盘前的会话。它在自己的工作目录里运行，终端关掉也继续活着；找到它的方式和找到别的会话一样：另一个 agent 用 `send_message` 给它发消息，它做完之后回复。

它适合那种应该在你旁边发生、而不是挡在你前面的工作。比如你刚写完代码，让一个评审 agent 去读 diff；或者你继续改代码，让另一个 agent 去跑一遍失败的测试。每个 daemon 都是一个可以起、可以列、可以停的会话：

```bash
zettcode daemon model                    # 能跑在哪些模型上
zettcode daemon spawn --model gpt-5 --effort high
zettcode daemon list
zettcode daemon kill 01a1726a-3109-75a7-9285-390d9e381111
```

`daemon model` 列出配置里的每个模型，名字就是 `spawn --model` 接受的那个，同时列出 id、API、是否收图片、窗口大小和推理级别；第一个标 `(default)`，也就是不起 daemon 时默认用的那个。`--json` 打同样的字段，给脚本读。

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
| `--model NAME` | 用哪个模型，名字由 `daemon model` 列出（默认配置里的第一个） |
| `--effort LEVEL` | 推理级别（默认模型自己的） |
| `-n LABEL`、`--name LABEL` | 给这个 daemon 一个身份，记在会话旁边，由 `daemon list` 显示（默认没有） |
| `--title TEXT` | 给它的会话起什么名字（默认由它第一次回答后自己起） |
| `--permission LEVEL` | 它的 shell 级别：`safe`（每条命令都在沙箱里）、`deny`（完全不给 shell）、`full`（默认）。没有 `ask`：没人能答 |
| `--resume SESSION` | 接着一个已存会话，而不是从空会话开始 |
| `--json` | 把同样的信息打成 JSON，给脚本或 agent 读 |

`spawn` 在 daemon 能被找到之后才返回，所以打印出来的 id 立刻就能发消息。起不来的话什么都不会留下，原因会打印出来（子进程最早写的那几行留在 `~/.zettcode/daemon/<workspace>/.spawn/` 里，读之前不删）。

::: warning daemon 不向任何人提问，它的 shell 级别是起它时选的
没有人在旁边点“允许”或回答问题，所以 daemon 从不提问：`ask` 不是它能拿到的级别，`ask_user` 工具也不会给它。你选的级别意味着：

- **`full`（默认）** —— 每条命令都以**启动它的那个账号的权限**运行：没有沙箱、没有审批、没有网络限制。只在你愿意把 shell 交给它的工作区里起它。
- **`safe`** —— 每条命令都在沙箱里跑：只能写工作区和临时目录，`~` 下的凭据对它不可读，环境变量被过滤成 `PATH`、`HOME`、`SHELL`、`LANG`、`TERM`、`TMPDIR` 这类。**网络是允许的**，所以沙箱里的 daemon 仍然能拉依赖；`pip install --user`、SSH 推代码、`gh` 会失败。
- **`deny`** —— 完全不给 shell。daemon 只读文件、改文件、说话，不跑任何命令。

配置里的 `permission` 对它不生效：daemon 的级别就是 `spawn` 时给的那个。

它的会话仍然是普通会话：daemon 用那份权限做了什么，都在会话里；`daemon list` 能看到正在跑什么。
:::

它的会话是全新、空的 —— 需要什么由发送方告诉它。`--resume` 则接着一个已存会话，可以在被 kill 掉的 daemon 留下的工作上继续，也可以在你们已有的对话里做评审。这个会话就是普通会话，存储方式一模一样，所以 `daemon kill` 之后还能 `zettcode resume <id>` 接着手动聊。

## 列出和停止

`zettcode daemon list` 列出这台机器上所有 daemon，不管它在哪个目录，每个 daemon 一段：

```
01a1726a-3109-75a7-9285-390d9e381111  idle  8m
  name       reviewer
  title      Reviewer
  workspace  ~/projects/api
  model      gpt-5 · effort high
  context    34k of 200k · 17%
  input      12.3k
  output     678
  shell      safe
```

第一行是 session id、它正在做什么、已经多久：`starting`（还没连上 broker）、`idle`、`working`、`stopping`，或者 `dead` —— dead 表示进程已经不在了（机器重启过，或者它崩了），用 `kill` 把条目清掉。`name` 是 `spawn --name` 记下的标签，`title` 是会话自己的名字。`context` 是最近一次调用时上下文有多满、拿多大的窗口去量、占了多少；`input` 和 `output` 是这个会话发出去和生成的总量；它们在 daemon 状态变化时写，turn 跑着的时候只要数字变了也会写（每几秒看一次）。数字截至最近一次完成的模型调用，所以一条回答还在流式输出时不会跳动。出现 `next` 行说明有一个换模型或换级别的请求还没生效；出现 `error` 行说明上一次请求为什么没成。出现 `broker` 行说明这个 daemon 现在连不上会话 broker —— 它会一直重试，这段时间没人能给它发消息。`--json` 打同样的字段，方便程序读。

`zettcode daemon kill <session-id>...` 停掉每个 daemon 并删掉它的记录。会话本身留着，做过的事都在里面，之后可以在终端里打开。

`zettcode daemon log <session-id>` 打印 daemon 自己记的最后几行 —— 它跑过的工具、失败的 turn、生效的设置；`-n N` 指定行数。觉得它卡住了，先看这里。

## 给它起名

daemon 会给自己起名：第一次回答之后，模型从这段对话里写一个短标题，`daemon list`、`/resume` 和 `zettcode resume` 显示的都是它。已经有标题的会话会保留标题，所以这是每个会话一次模型调用，不是每条消息一次。

`spawn --title` 可以在开始时就命名，`daemon update` 之后也能改：

```
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --title "Auth refactor review"
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --name reviewer
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --name ""        # 清掉标签
```

`--name` 是 daemon 自己的标签，任何时候都能改，包括它运行的时候：daemon 会保留读者写进去的那份。`--title` 是**会话的**名字，而会话只有持有它锁的进程能写 —— 所以运行中的 daemon 会拒绝 `--title`（先停掉它；它自己已经在命名了）。两个一起给时，标题被拒也会先把标签写进去，并说明这一点。`--json` 打改动后的记录。

## 改变它跑在什么上

运行中的 daemon 可以换到另一个已配置的模型、或者另一个推理级别，会话不丢；改动从下一轮生效（空闲时几秒内生效）：

```
zettcode daemon update 01a1726a-3109-75a7-9285-390d9e381111 --model gpt-5 --effort high
```

模型可以用 `daemon model` 列出的名字，也可以用 id。这台机器没有的模型会被拒绝，模型不接受的级别也会被拒绝。没在运行的 daemon 不能换：下一次起的时候用 `spawn --model/--effort`。请求还没生效时，`daemon list` 会用 `next` 行显示它；如果 daemon 没法接（比如它启动时的配置和你这边不一样），会用 `error` 行说明，而且不会再重试这个请求。

## 和它说话

daemon 不接受输入，它的输入就是 `send_message` —— 来自另一个会话的 agent，包括你在终端里用 `@` 点名 daemon 时由你的模型发出的那条：

```
send_message(to="01a1726a-3109-75a7-9285-390d9e381111", message="看一下 src/api.py 的 diff，说你打算改什么。")
```

daemon 一次处理一条消息。忙的时候最多再排四条，再多就告诉发送方“忙”。它也用同样的方式回答 —— `send_message(to=<你的 session id>, ...)` —— 所以问它的 agent 会把回答当成一条消息收到。

命令行也可以当发送方，用来给一条不想打开会话就能给的提示：

```
zettcode daemon prompt 01a1726a-3109-75a7-9285-390d9e381111 "看一下 src/api.py 的 diff，说你打算改什么。"
```

它和别的消息一样走会话 broker。发送方是一个名字而不是会话，所以 daemon 不会回信：这一轮存在它自己的会话里，用 `zettcode resume <id>` 打开看，`daemon log` 说明它做了什么。

daemon 不会自己退出，闲置几个小时也不会：不用了就用 `daemon kill` 停掉，否则它会一直在那里，被列出来，有人写就回答。

## 一轮失败时

可能恢复的失败 —— 超时、连接断开、限流、服务端错误 —— 会自动再试，最多三次，两次之间短暂等待（总共约七秒，所以持续时间更长的限流仍然会以失败告终）。重试是**接着中断的请求继续**，不是把提示词重发一遍：库会告诉模型哪些工具被截断，由模型决定；daemon 不会自己重跑工具。再试也不会成功的失败（密钥错、模型不存在）不会重试。

如果最后还是失败，能收到消息的发送方会被告知：聊天窗口看到失败那一行，发消息的会话会收到一条说明失败原因的回复。`daemon prompt` 是以名字而不是会话身份发的，收不到回复 —— 原因在日志里。daemon 本身继续跑，接着处理下一条消息；`daemon list` 里它回到 `idle`，做过的尝试和最后的原因都在 `daemon log <id>` 里。

## 存在哪

```
~/.zettcode/sessions/<workspace>/<session-id>/    会话本身，和别的会话一样
~/.zettcode/daemon/<workspace>/<session-id>/
    state.json                                    pid、状态、模型、effort、开始时间，以及计数
    heartbeat                                     每几秒写一次，证明还活着
    log                                           出错的地方，以及它跑过的工具
```

`~/.zettcode/daemon/<workspace>/workspace.txt` 记录这个目录对应哪个路径，和会话存储的做法一样。`kill` 除了停进程，只做一件事：删掉 `daemon/` 里这个会话的目录。

## 从一次评审开始

大多数人用 daemon 的第一件事是找个“第二双眼睛”，`/code-review` 做的就是这件事：它写一段提示 —— 收集 diff、让另一个 reviewer 读、点名具体问题 —— 然后当成一轮对话跑起来，等同于你亲手打的。

```
/code-review
/code-review src/api.py 里的错误处理
```

接下来是模型的事：它先看 `<daemon> list`，这个工作区里已经有这个命令起过的 reviewer（名字是 `code-review`）就直接用那一个，没有才 `<daemon> spawn --name code-review` 起新的；然后用 `send_message` 告诉那个会话读什么，等回答作为一条消息回来再汇报。用过几轮的 reviewer 已经熟悉这批改动，所以比新建一个更合适；`list` 上能看到的是名字和工作区，所以同一个工作区里另一个终端起的 reviewer 也会被复用。

修的时候 reviewer 一直留着：主 agent 把它指出的地方改掉，再把改动的新状态发给它看，这样一轮一轮走到它没什么可说的为止。发给它的每条消息都要说明它**必须回答** —— 有问题就报，没问题也要说一句 —— 因为一个不出声的 reviewer，和一次什么都没看出来的评审没办法区分。某一轮没有回答就再发一次；还是没有回音，就去读它自己的会话 —— `~/.zettcode/sessions/*/<session id>/data.jsonl`，里面最后一条 assistant 消息就是它的评审 —— 把它贴回来，然后停掉（`<daemon> kill <session id>`），不要让它一直跑着；`<daemon> list` 能看到还在跑什么。

`<daemon>` 是终端自己运行所在的那套安装的命令 —— 同一个解释器下的 `python -m zettcode.daemon` —— 而不是去 PATH 上找一个 `zettcode`，所以为一份代码检出、或一个外人看不到的虚拟环境起的终端，也能起 daemon。

reviewer 跑在**你自己那个 shell 级别**上，不会更高：`full` 给它 `full`，`safe` 给它 `safe`，而 `ask`（意思是“问读者”）在后台进程里没法问，所以给它 `safe`。`deny` 下既没有 shell 收集 diff，也就不会起 reviewer，模型改为读文件评审。提示里会告诉 reviewer 它只读不改 —— 改动由主 agent 拿到意见后自己做 —— 但那只是一句指令，不是沙箱：`full` 下的 reviewer 如果真去改，是有权限的。
