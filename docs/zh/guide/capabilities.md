# 它能做什么

这份指南的大部分内容讲的是一个终端里的一个会话。ZettCode 还有几件单会话终端智能体做不到的事。这一页逐项说明：它是什么、
和单会话有什么不同、用哪条命令。细节在每一节链接的页面里。

| 能力 | 一句话 | 需要 |
| --- | --- | --- |
| [JIT harness](#jit-harness) | 模型当场写一个小的 Python 工具，加载并在同一轮里调用 | `zettcode`（默认关闭，需要你打开） |
| [代码评审](#代码评审) | `/code-review` 让另一个智能体读你未提交的改动 | `zettcode`，以及一个 git 仓库 |
| [后台 agent](#后台-agent) | 没人坐在键盘前的会话，用 `zettcode daemon spawn` 启动 | `zettcode` |
| [会话互发消息与 `@`](#会话之间互发消息) | 同一台机器上的会话互相发消息，`@名字` 让模型找到对方 | `zettcode` |
| [群](#群) | 一组有名字的会话，发给群的消息送达每个在线成员 | `zettcode` |
| [Graph 页面](#graph-页面) | 会话是节点，群是区域，消息沿线飞过，可以回放 | `zettcode gateway start` |
| [网页网关](#网页网关) | 管理 daemon、会话和群的网页，手机和桌面窗口也能用 | `zettcode gateway start` |
| [Codex 与 Claude Code](#codex-与-claude-code) | 两者都作为可发消息、可入群的成员运行 | `zettcode[code-agents]`，以及 Codex 或 Claude Code 命令行 |

除最后一行外，其余都在普通的 `zettcode` 里；`[all]` 另外带来 `/monitor`、`/recap`、各厂商模型和最后一行。见[快速开始](/zh/guide/getting-started#安装)。

## JIT harness

**它是什么。** 开启 harness 后，模型可以新建一个小的 Python 仓库，写入一个工具，用 `repo_load` 加载，并在同一轮里调用。
工具就是普通 Python，放在 `~/.zettcode/harness/<工作区>/<会话 id>/` 下，每一步都是可以展开查看的行。

**不同在哪。** 固定的工具集只能做作者想到的事；这里模型可以为当前任务写一个一次性的工具，比如"从 `git blame` 里列出每个 `TODO` 的负责人"。
代码在子进程中运行，崩溃或卡死不会影响你的会话。低于 `full` 的 shell 级别时，它跑在 `safe` 使用的边界里；在 `full` 时它拥有你自己的权限。
它默认关闭。`/harness gen` 会告诉模型把写入限制在 harness 目录、不要改你项目里的文件，这是对模型的指示，不是沙箱。

**怎么用。**

```text
/harness gen 找出这个仓库里的 TODO 注释，按文件分组
/harness reset
```

`/harness gen` 在本次运行中打开 harness，并让模型为这个工作区造一个工具；`/harness reset` 在本次运行中关闭它，不会删除任何东西。
想让每次运行都默认开启：

```toml
# ~/.zettcode/config.toml
[harness]
jit = true
```

**详情。** [JIT harness](/zh/guide/harness)。

## 代码评审

**它是什么。** `/code-review` 让模型评审工作区里未提交的改动。模型会启动一个名为 `code-review` 的后台会话（这个工作区已有一个在运行就复用它），
把评审请求发给它；每修完一轮，再请它重新看一遍，直到它没有要改的为止。

**不同在哪。** 评审发生在另一个会话里，你的对话不会被 diff 撑满；见过前几轮的评审者也能判断某个修复是否有效。
评审者被告知只读不改，但这只是指示，不是沙箱：它运行在你自己的 shell 级别上（你的级别是 `ask` 时用 `safe`），所以在 `full` 下它如果想改，是改得了的。

**怎么用。**

```text
/code-review
/code-review src/api.py 里的错误处理
```

在 `deny` 级别下不会启动评审者，模型自己读文件来评审。

**详情。** [代码评审](/zh/guide/code-review)。

## 后台 agent

**它是什么。** daemon 是没人坐在键盘前的会话。它在自己的工作区里工作，关掉终端后继续运行，通过消息联系。
你可以用命令行或网页网关来启动、查看、停止和删除它。

**不同在哪。** 终端会话活在它的终端里：关掉窗口它就结束了。daemon 在你关掉终端后继续工作，所以一个耗时的任务（翻查失败的测试、评审 diff）
不会占住你自己的会话。daemon 就是一个普通的已保存会话，
停止之后可以用 `zettcode resume <id>` 打开；`daemon stop` 保留记录，`spawn --resume` 可以在同一段对话上重新启动。

::: warning daemon 不会问任何人
没有人能批准命令，所以 daemon 从不询问。它的 shell 级别默认是 `full`：每条命令都以启动它的账户的权限运行，没有沙箱。
除非这个工作区是你愿意给一个 shell 的，否则请加 `--permission safe`（命令在沙箱里运行）或 `--permission deny`（没有 shell）。
:::

**怎么用。**

```bash
zettcode daemon spawn --name builder --title "tool builder" --permission safe
zettcode daemon list
zettcode daemon prompt <session-id> "Run the tests and tell me what fails."
zettcode daemon stop <session-id>
```

`spawn` 会打印 session id；`daemon list` 显示每个 daemon 的状态、模型、上下文占用和 shell 级别。

**详情。** [后台 agent](/zh/guide/daemons)。

## 会话之间互发消息

**它是什么。** 每个会话启动时都会向一个本机的小型 broker 注册（它只监听 `127.0.0.1`，需要 `~/.zettcode/broker/` 里的 token 文件）。
每个会话都有名字，显示在标题栏里。在输入框里敲 `@` 选择另一个会话，模型随后用它的 `send_message` 工具把消息发出去。

**不同在哪。** 会话之间可以把任务交给彼此，不用你在终端之间复制粘贴。收到的消息会标明发送者，并告诉模型这是同事的请求，不是你的指令。
对方正在忙时，消息要么引导正在运行的请求，要么作为后续消息排队。只限同一台机器、同一用户：没有任何东西经过网络。

**怎么用。** 有 daemon 在运行时，在终端会话里：

```text
❯ @tool-builder write a helper that lists TODO comments, then tell me its name
```

`@` 后面的名字先取自会话标题，再取自文件夹；以补全菜单里显示的为准。发送在对话里是单独的一行（`Delivered to …`、`queued`，或者没发出去的原因）。

**详情。** [会话之间互发消息](/zh/guide/messaging)。

## 群

**它是什么。** 群是一组有名字的会话，写作 `#名字`。发给群的消息会送达其他每个在线成员，每个成员都会被告知它来自哪个群。

**不同在哪。** 一条消息可以同时送到规划者、评审者和测试者，各自可以回复整个群，也可以只回复发送者。群由 broker 保存，重启后仍在；
不在线的成员会错过这条消息，但它仍留在历史里。群里每条消息都会让每个成员消耗一轮，所以请告诉智能体只在需要时才回复。

**怎么用。** 让某个会话的模型创建一个（它用 `manage_group` 工具），或者在网关的 Chats 页面点 **New group**（新建群组）。
限制：一个群最多 64 个会话，一个会话最多在 20 个群里，一台机器最多 200 个群。

**详情。** [会话之间互发消息：群聊](/zh/guide/messaging#群聊)。

## Graph 页面

**它是什么。** 网页网关的一个页面。每个会话是一个节点，每个群是一块阴影区域，每条消息发出时沿着线从发送者飞向接收者。
**Replay** 会按存下来的历史重放过去的一段时间，最多 20,000 条消息。

**它的用途。** 它不改变智能体能做什么，只展示它们做了什么。多个智能体在交谈时，它能看出谁在跟谁说话、对话在哪里停住了。回放只是重画发生过的事，不会重新发送任何消息。

**怎么用。** 启动网关，在导航里打开 **Graph**：

```bash
zettcode gateway start
```

**详情。** [会话之间互发消息：图](/zh/guide/messaging#关系图)。

## 网页网关

**它是什么。** `zettcode gateway` 为本机上的 daemon 和会话提供一个网页：聊天、可以启动/停止/重启的 daemon 列表、群、Graph、daemon 日志和模型配置。
页面默认监听 `127.0.0.1:8765`。

**不同在哪。** 终端留在代码所在的地方，网页跟着你走，包括手机上。你可以在浏览器里启动 daemon，不必开 shell。
它用 token 登录（`--token`），可以再发一个只读 token，还提供 `/metrics` 和审计日志。

**怎么用。**

```bash
zettcode gateway start        # 转入后台，打印地址
zettcode gateway stop
```

要从手机访问，监听本机以外的地址必须设 token，见[网页网关](/zh/guide/gateway#登录与权限)。
页面是明文 HTTP，离开可信网络时请放在 TLS 后面。桌面端（Electron）和 Android 外壳只是同一个页面的窗口；
macOS 那个只做了 ad-hoc 签名，Windows 和 Linux 的则完全没有签名。
见[桌面端与手机端](/zh/guide/app)。

**详情。** [网页网关](/zh/guide/gateway)、[桌面端与手机端](/zh/guide/app)。

## Codex 与 Claude Code

**它是什么。** `code-agents` 插件把 **Codex** 和 **Claude Code** 作为群的成员运行。每个都是持久的命令行会话，
会话 id 保存在 `~/.zettcode/code-agents/`，所以每条消息都延续同一段对话。

**不同在哪。** 你可以把它们和自己的 daemon、会话放进同一个群，并用 `@` 呼叫。插件只负责启动你已有的命令行工具：
需要在运行网关的用户下安装并登录 Codex 或 Claude Code 的 CLI。

::: warning 权限默认是 `full`
插件的默认值是 `full`：智能体可以做你能做的任何事，因为没有人来回答提示。用 `--no-full` 启动网关并不会限制这些智能体。
在 `~/.zettcode/code-agents/config.json` 里把 `"permission"` 设为 `workspace` 或 `read` 才能收窄。
:::

**怎么用。**

```bash
pip install "zettcode[code-agents]"     # 或 zettcode[all]
zettcode gateway restart
```

在网关里打开 **New**，选 **External agent**（外部智能体）标签，选 Codex 或 Claude Code，可选填要加入的群，点 **Start external agent**（启动外部智能体）。

**详情。** [Codex 与 Claude Code](/zh/guide/code-agents)。
