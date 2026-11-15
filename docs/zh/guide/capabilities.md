# 它能做什么

这份指南大部分讲的是一个终端里的一个会话。这一页列出它在此之外的八件事，每件都附一条能启动它的命令。

| 能力 | 一句话 | 需要 |
| --- | --- | --- |
| [JIT harness](#jit-harness) | 模型在同一轮里写完、加载并调用一个 Python 工具 | `zettcode` |
| [代码评审](#代码评审) | 另一个智能体读你未提交的改动 | `zettcode`，一个 git 仓库 |
| [后台 agent](#后台-agent) | 没人坐在键盘前的会话 | `zettcode` |
| [会话互发消息与 `@`](#会话之间互发消息) | 会话之间互发消息，`@名字` 选中对方 | `zettcode` |
| [群](#群) | 一组有名字的会话，一条消息送达所有在线成员 | `zettcode` |
| [Graph 页面](#graph-页面) | 会话是节点，群是区域，消息可回放 | `zettcode gateway start` |
| [网页网关](#网页网关) | 管理 daemon、会话和群的网页，手机上也能用 | `zettcode gateway start` |
| [Codex 与 Claude Code](#codex-与-claude-code) | 两者都作为可发消息、可入群的成员运行 | `zettcode[code-agents]`，以及对应的命令行 |

除最后一行外，其余都在普通的 `zettcode` 里；`[all]` 另外带来 `/monitor`、`/recap`、各厂商模型和最后一行。
见[快速开始](/zh/guide/getting-started#安装)。

## JIT harness

模型为当前任务写一个小 Python 工具，用 `repo_load` 加载，并在同一轮里调用。任务需要一个自己的工具时用它，
比如从 `git blame` 里列出每个 `TODO` 的负责人。

```text
/harness gen 找出这个仓库里的 TODO 注释，按文件分组
/harness reset
```

**详情。** [JIT harness](/zh/guide/harness)。

## 代码评审

`/code-review` 让第二个智能体在单独的会话里读你未提交的改动，每修一轮再看一遍。提交前用它。

```text
/code-review
/code-review src/api.py 里的错误处理
```

在 `deny` shell 级别下不启动评审者，模型自己读文件。

**详情。** [代码评审](/zh/guide/code-review)。

## 后台 agent

daemon 是没人坐在键盘前的会话：关掉终端它还在跑，你用消息联系它。适合你不想一直守着的长任务。

```bash
zettcode daemon spawn --name builder --title "tool builder" --permission safe
zettcode daemon list
zettcode daemon prompt <session-id> "Run the tests and tell me what fails."
zettcode daemon stop <session-id>
```

`spawn` 会打印 session id。没有人批准 daemon 的命令，所以除非这个工作区是你愿意给一个 shell 的，
否则加 `--permission safe` 或 `deny`。

**详情。** [后台 agent](/zh/guide/daemons)。

## 会话之间互发消息

每个会话都向本机的 broker 注册，所以一个会话能给另一个发消息。在输入框敲 `@` 选一个会话，模型随后把请求发出去。

```text
❯ @tool-builder write a helper that lists TODO comments, then tell me its name
```

收到的消息会标明发送者。只限同一台机器。

**详情。** [会话之间互发消息](/zh/guide/messaging)。

## 群

群是一组有名字的会话，写作 `#名字`，发给群的消息送达每个在线成员。规划者、评审者和测试者需要听到同一件事时用它。
让某个会话的模型创建一个（它用 `manage_group`），或者在网关的 Chats 页面点 **New group**（新建群组）。

**详情。** [会话之间互发消息：群聊](/zh/guide/messaging#群聊)。

## Graph 页面

网页网关的一个页面：会话是节点，群是区域，每条消息是一条指向接收者的线。多个智能体在交谈、你想知道谁在跟谁说话时用它。
**Replay** 重放过去的一段时间，最多 20,000 条消息，不会重新发送任何东西。

```bash
zettcode gateway start
```

在导航里打开 **Graph**。

**详情。** [会话之间互发消息：图](/zh/guide/messaging#关系图)。

## 网页网关

`zettcode gateway` 为本机的 daemon、会话和群提供一个网页，默认在 `127.0.0.1:8765`。想在浏览器里启动 daemon、
或在手机上跟进工作，用它。

```bash
zettcode gateway start        # 转入后台，打印地址
zettcode gateway stop
```

设了 `--token` 时页面会要一次 token 并记住 cookie；没有 token 时只监听本机。页面是明文 HTTP，
离开可信网络时请放在 TLS 后面。

**详情。** [网页网关](/zh/guide/gateway)、[桌面端与手机端](/zh/guide/app)。

## Codex 与 Claude Code

`code-agents` 插件把 **Codex** 和 **Claude Code** 作为群的成员运行，可以用 `@` 呼叫，每个都保持一段持久的命令行会话。
适合把别家的智能体放在自己身边。

```bash
pip install "zettcode[code-agents]"     # 或 zettcode[all]
zettcode gateway restart
```

然后在网关里打开 **New**，选 **External agent**（外部智能体），点 **Start external agent**（启动外部智能体）。
这些智能体默认是 `full`；在 `~/.zettcode/code-agents/config.json` 里把 `"permission"` 设为 `workspace` 或 `read`
才能收窄。

**详情。** [Codex 与 Claude Code](/zh/guide/code-agents)。
