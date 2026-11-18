# 上下文窗口

每个模型都有限制：一次能读多少——这就是它的**上下文窗口**。一个请求里的一切都在争这块预算：指令、工具
schema、消息、每个工具调用的输出。

`/context` 看的是最新那一次请求：窗口有多满、离压缩还有多远、token 都花在哪儿。状态行里的 `ctx` 是同一个
数字的简写。

```text
/context
```

这一页画的是**模型最近真正收到的那个请求**，不是屏幕上的对话：打了一半还没发出去的话不在里面，工具结果也要等它
发回去才算。`Esc` 关闭，请求进行中打开它也安全。`No request yet` 表示这个会话还没发过请求。

## 怎么读这一页

![`/context` 页面：窗口的仪表、三个数字，以及请求的来源](/screens/context.svg)

标题下面两行说明这张图属于哪个会话。`Workspace` 是这个会话的工作目录：工具解析相对路径时以它为起点，
读写文件的工具和 shell 默认都在这里运行；`Session` 是保存这段对话的文件。在 macOS 和 Linux 上，位于主目录里的
路径以 `~` 开头；不论在哪个系统上，终端放不下的长路径都保留尾部，也就是能看出目录或文件名的那一段。

### 窗口

```text
Window   103,241 / 200,000 tokens   51.6% full
```

第一个数字是这次请求带了多少；第二个是模型配置的窗口（`config.toml` 里的 `context_window`）；第三个是两者
相除。

下面那条按比例画出这个数字，它的**颜色表示危险程度，不表示大小**：远低于压缩点的是绿色，走到四分之三处变琥珀，
到点变红。标记在 80% 时，琥珀从窗口的 60% 开始。

```text
                      compacts at 160,000 tokens (80.0%) ▲
```

`▲` 标出 ZettCode 不再多发、改为压缩的位置：窗口的 `compact_percent`，这里是 80%，也就是 200,000 里的
160,000。到点不等于窗口满了——下一发之前，较早的对话会被总结掉。

同一轮再往后：

![同一页接近触发线的样子：琥珀色的仪表和一条压缩摘要](/screens/context-near.svg)

三行数字分的是同一块预算：

| 行 | 是什么 |
| --- | --- |
| `Used` | 这次请求里的 token，和 `Window` 行第一个数字相同 |
| `Until compaction` | 还能加多少，之后请求会被总结。这才是真正的余量 |
| `Free in window` | 还能加多少，之后模型会直接拒收这个请求 |

### token 花在哪

```text
Where it goes   how the 103,241 tokens divide between sources
████████████████████████████████████████████████████████████████████████
```

一条横条把请求分给各个来源；每一段下面有自己一行，按那一行自己的比例画，所以小到在总条里看不出来的来源也看得见。

| 来源 | 装的是什么 |
| --- | --- |
| `System prompt` | ZettCode 自己的指令：有哪些工具、工作目录、日期。固定不变，provider 才能缓存它 |
| `Environment notes` | `AGENTS.md` 这类项目指令，以及会话开始时加的说明 |
| `Tool schemas` | 请求里提供的每个工具——名字、说明、参数 schema。九个工具就是九份，用没用都一样 |
| `User messages` | 你打的字，包括 `/btw`。一张图片按固定数量算，不按文件大小 |
| `Assistant messages` | 模型的回答、它返回的思考，以及它发起的工具调用 |
| `Tool output` | 文件内容、命令输出、搜索结果。通常是最大的那一行 |
| `Compaction summary` | 上一次压缩留在原地的、代替较早对话的那一份摘要 |

`Items` 是 `Tokens` 加起来的条数：消息、工具定义、摘要。它不是轮数。

`Share` 是每个来源在"被统计的这部分"里的占比，所以各行加起来是 100%。`Tool output 60.1%`、`62,069` 个
token，不是窗口的 60.1%，是这次请求的 60.1%。窗口的百分比只在 `Window` 那一行，别处没有。

### 这个数字是谁的

脚注是读每一行的规则：

```text
Total from the provider, which counts what it bills. Each source gets its share of that total,
worked out from a local count.
```

- **总数**是 provider 对它收到的请求的计数，也就是它计费的那个数。
- **拆分**是 ZettCode 自己算的，用本地计数，因为没有 provider 会报分项。
- 所以每一行都是那个来源在 provider 总数里的**占比**：条里的数字是比例，不是测量值。

本地计数分得清谁比谁大，但说不准绝对大小：它用一套 tokenizer，模型可能用另一套。

![会话刚重开：两行还是 pending](/screens/context-resumed.svg)

`Counted here; the provider has not reported this request yet` 表示这个会话是恢复的，这个进程里还没发过
请求。`Tool schemas` 和 `Environment notes` 是在拼请求时才算出来的，所以这两行显示 `pending`，总数只是下限。
发一条消息再跑一次 `/context` 就齐了。

## 移动压缩点 {#moving-the-mark}

按键上方那行 `Compress at` 是一条带旋钮的滑轨：窗口用到多少时压缩，按比例算。← 和 → 每次挪五个百分点，点滑轨
直接送到那儿。仪表下面的 `▲`、那个数字和 `Until compaction` 都会跟着走，所以先看清效果再决定。开了减少动态时，
旋钮不播动画。

按下 `Enter` 之前什么都不写；按下之后把 `compact_percent` 写进这个模型在 `config.toml` 里的条目，下一次
请求生效。`Esc` 保持原样。文件改不了时，这次的改动只对本次运行有效，那一行会说明。

## 压缩 {#compaction}

下一次请求要越过触发线时，较早的对话变成一份摘要，触发线最新的四分之一原样保留，所以模型留着眼前的上下文。
`/compact` 立刻做，不等触发。

摘要存成自己的一种记录，不是删除：所以对话末尾仍然是 `Conversation checkpoint`，昨天的会话压过之后照样能恢复。

::: tip 压缩的代价
总结是一次模型调用，要几秒，对话里显示 `Compacting`。要压就早压，别等到正需要空间的时候。如果摘要不比它替掉的
文字短，ZettCode 会说明并保留原文。
:::

最新的检查点已经覆盖整段对话时，再手工压缩会被拒绝。摘要可能丢细节；确切的文字要紧时，让模型重新读那个文件。
允许的话，模型也能自己压：[自压缩](/zh/guide/commands#self-compaction)。`/compact` 为这个会话、或为所有从未选过的
会话打开它：

![`/compact` 面板：上面这根滑轨是这个会话自己的选择，下面是其他所有会话的默认值](/screens/compact.svg)

`↑` `↓` 选一行，`←` `→` 挪那一行的旋钮，下面那行说明当前会是什么效果，`Enter` 两行一起应用——默认值写进
`config.toml`，会话自己的选择留在会话里。`Esc` 什么都不应用。

## 让请求保持小

- **只读要用的。** 读一段行比读整个文件强。输出在被压掉之前，每次请求都要为它付费。
- **关掉不用的工具。** 每个 MCP server、每个在范围内的 skill 都会给请求加 schema；见
  [Skills 与 MCP](/zh/guide/skills-and-mcp)。
- **让稳定的部分稳定。** 系统提示和工具列表是 provider 缓存的东西，所以前缀不变更便宜。那就是状态行和
  `/usage` 里的 `cached`。

哪一行大，做法就写在里面：`Tool output` 意味着读窄一点，`Tool schemas` 意味着少开 server 和 skill，
`Environment notes` 意味着指令写短些。

## 下一步

- [命令参考](/zh/guide/commands)：`/compact`、`/new` 和自压缩。
- [Token 用量](/zh/guide/usage)：这个项目花了多少。
- [读懂状态行](/zh/guide/models#读懂状态行)：回复到来时的 `ctx` 和 `cached`。
