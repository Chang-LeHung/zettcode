# 命令

你输入的一切：ZettCode 里的斜杠命令和 `@` 引用，以及 `zettcode` 命令行。

输入 `/` 打开菜单，边打边过滤，`Enter` 或 `Tab` 填入高亮的那一条。需要参数的命令，在名字后面加空格和参数。
只有列表里的名字才是命令 —— `/var/log/syslog`、`/tmp is full` 都是普通文本，和其他消息一样发给模型。

有固定第一个词的命令，在输入名字和空格之后会把它列出来：`/config ` 给出 `add`、`remove`、`list` 和
`providers`，`/theme ` 给出各个配色，`/model ` 给出你配置过的模型。`Enter` 直接运行高亮的那一项，所以
`/model ` 再按 `↓` `Enter` 就切换模型，不再打开选择器。

## 斜杠命令

| 命令 | 作用 | 例子 |
| --- | --- | --- |
| `/help` | 列出命令和快捷键。 | `/help` |
| `/new` | 开一个新会话，旧会话仍留在磁盘上。 | `/new` |
| `/clear` | 清空可见的对话，会话本身继续。 | `/clear` |
| `/resume` | 打开已保存的会话：可搜索的最近会话面板，或按 id 直接打开。 | `/resume 01a10b75` |
| `/continue` | 继续一个被打断的请求。见[下文](#continue)。 | `/continue` |
| `/fork` | 把当前对话带进一个新会话，并在那里继续。 | `/fork` |
| `/model` | 切换后续请求使用的模型；插件提供的模型也列在里面。 | `/model DeepSeek Pro` |
| `/config` | 不用改文件就能添加、修改和删除模型。 | `/config add --model gpt-4o --token sk-… --url …` |
| `/effort` | 设置模型思考多少，从下一个请求开始。 | `/effort high` |
| `/permission` | 设置 shell 命令在多大范围内不用问。 | `/permission safe` |
| `/plugins` | 打开或关掉一个插件，下次启动生效。 | `/plugins disable recap` |
| `/harness` | 查看 harness、工具和文件；`gen` 最多接收 4000 个字符（行内显示前 120 个）。 | `/harness gen 一个列出 TODO 的工具` |
| `/btw` | 问一件只在当场回答、不进入对话的事。 | `/btw 这里的幂等是什么意思？` |
| `/code-review` | 评审尚未提交的改动；文字说明重点看什么。 | `/code-review 检查错误处理` |
| `/bash` | 在工作区里打开一个全屏 shell。见[下文](#bash)。 | `/bash git status` |
| `/theme` | 选择配色，菜单里会预览每一套。 | `/theme nord` |
| `/pet` | 选择对话上方的宠物。 | `/pet whale` |
| `/context` | 查看上下文窗口有多满、被什么占着，以及会话的工作目录和存储文件。 | `/context` |
| `/usage` | 查看这个项目的会话花了多少。 | `/usage` |
| `/compact` | 立即总结对话，不用等窗口快满。 | `/compact` |
| `/statusline` | 选择头部和状态行里哪些部分要显示。 | `/statusline hide ctx` |
| `/title` | 给会话命名；不带参数时报告当前名字。 | `/title users endpoint` |
| `/export` | 把这个会话写成一个独立的 HTML 文件。 | `/export review.html` |
| `/quit`、`/exit` | 退出，并打印恢复这个会话的命令。 | `/quit` |

命令来自三处，菜单按这个顺序排列：外壳自己的、代理的，以及任何注册了命令的[插件](/zh/guide/plugins)。插件
不能占用已有的名字，所以 `/model` 永远是本页说的行为。

有面板的命令，按键属于那个面板：`Esc` 取消，`Enter` 应用。`/permission` 和 `/theme` 只在几个固定的词里选，
所以用菜单列出来；`/model` 和 `/resume` 打开选择器，因为模型名可能带空格，会话最好连标题一起挑；`/effort`
打开一条滑轨，`/context` 打开一页条形图。

多数命令要等手上的请求结束。这些不用等：`/help`、`/plugins`、`/context`、`/usage`、`/theme` 只是展示，
`/bash` 跑的是你自己的命令，`/title` 写的名字没有人在读，`/permission`、`/effort` 和 `/model` 改的是下一个
请求要用的东西。`/quit` 不等回答，`/btw` 和 `/code-review` 排队等轮到它。`/new`、`/clear`、`/resume`、
`/fork`、`/compact`、`/export` 和 `/config` 会回答 “busy”。

### 继续被打断的请求 {#continue}

`/resume` 打开的是以前的会话；`/continue` 继续的是当前会话里没做完的那个请求。做什么，取决于它是怎么结束的：

| 怎么结束的 | `/continue` 做什么 |
| --- | --- |
| 回答之前就停了或失败了，或者工具已经跑完 | 再问一次模型，不添加任何内容。 |
| 工具运行时被停掉 | 告诉模型哪些工具被中断，由它决定。工具绝不会自己重新运行。 |
| provider 截断了回复，或回复碰到输出上限 | 请模型接着写这段回复。 |
| provider 暂停了 | 把这一轮交还给 provider。 |
| 已经完成、被拒绝，或上下文窗口已满 | 什么都不做并说明原因；窗口满了需要 `/compact` 或 `/new`。 |

它使用下一条消息会用的模型和推理强度，并且先说明要做什么，再去做。

### 自我压缩 {#self-compaction}

自我压缩是模型在判断细节已不再需要时，自己压缩自己的上下文。默认是打开的（`config.toml` 里的
`[compaction] self`），`/plugins` 里有一个 `self-compaction` 开关，开启时状态行末尾显示 `self-compact`。
见[上下文窗口](/zh/guide/context)。

### Shell 面板 {#bash}

`/bash` 在工作区里打开一个全屏命令行，`/bash <命令>` 则打开后立即运行这条命令。它就是你自己的 shell、由你
自己动手：不需要权限确认，模型看不到其中任何内容，关闭面板后输出也随之消失。请求还在运行时也能打开。

| 按键 | 作用 |
| --- | --- |
| <kbd>Enter</kbd> | 运行命令。 |
| <kbd>Tab</kbd>、<kbd>Shift</kbd>+<kbd>Tab</kbd> | 补全光标处的词；再按一次看下一个候选。 |
| <kbd>↑</kbd> <kbd>↓</kbd>、<kbd>Ctrl</kbd>+<kbd>R</kbd> | 翻阅、搜索以前的命令。 |
| <kbd>Ctrl</kbd>+<kbd>C</kbd>、<kbd>Esc</kbd> | 停止正在运行的命令；没有命令在运行时，关闭面板。 |

每条命令在工作区里单独起一个进程，用你自己的 shell；向程序提问时，它读到的是输入结束。单独的 `cd` 会留给
下一条命令。`fish` 不加载配置启动。历史读自 bash、zsh、fish 和 PowerShell，你在这里敲的命令记在
`~/.zettcode/command_history`。

### Token 用量 {#usage}

`/usage` 打开这个项目的会话花了多少，分三个视图：按模型、按会话，以及一张按天的日历图。每个字段的含义，
以及它和状态行的区别，都在 [Token 用量](/zh/guide/usage)。

## `@` 引用

`@` 把一个资源拉进消息：按路径引用的工作区文件，按名字引用的 [skill](/zh/guide/skills-and-mcp)，或者另一个
[会话](/zh/guide/messaging)。

> @packages/zettcode/src/zettcode/cli.py 这个文件是做什么的？

输入 `@` 后菜单把它们列出来，文件还带着大小。文件引用发出去的是路径而不是内容：模型用自己的工具去读，所以
一次引用只占一句话的上下文，而不是一整个文件。目录则指向搜索。存下来的是你亲手打的草稿，恢复会话时看到的
仍是 `@路径`。光标紧跟芯片时，一次 **Backspace** 删掉整个芯片。

## `zettcode` 命令行

`zettcode --help` 列出命令行接受的全部参数，并不多。

| 参数 | 作用 |
| --- | --- |
| `-v`、`-V`、`--version` | 打印版本 —— ZettCode、它运行的 zett-agent，以及 Python —— 然后退出。报告问题时请附上。 |
| `-w`、`--workspace DIR` | 在哪个目录里工作。默认是当前目录。 |
| `-r`、`--resume SESSION` | 打开已保存的会话，而不是新开一个。 |
| `--full`、`--auto`、`--yolo` | 本次运行里 shell 命令用你自己的权限跑、不再询问。等同于 `/permission full`。 |
| `--dry-run` | 走一遍启动，画一帧就走。用于分析启动耗时。 |

子命令是同一个可执行文件下的其他程序：

| 子命令 | 作用 |
| --- | --- |
| `resume SESSION` | 等同于 `--resume`；`-w DIR` 放在它前后都行。 |
| `update`、`upgrade` | 装最新的版本然后退出。见 [FAQ](/zh/guide/faq#新版本)。 |
| `doctor` | 向配置里的每个模型问一个很短的问题，打印哪些能答、多快，或者为什么不能。有一个不行就退出 1。 |
| `prompt` | 发一条 prompt，打印回答，退出。见[下文](#zettcode-prompt)。 |
| `daemon` | 启动、列出、查看日志、停止或杀掉一个[后台 agent](/zh/guide/daemons)。 |
| `broker` | 运行本地的[会话 broker](/zh/guide/messaging)。 |
| `gateway` | 提供[网页网关](/zh/guide/gateway)。 |
| `plugin` | 安装、删除和切换[插件](/zh/guide/plugins)。 |

## `zettcode prompt` {#zettcode-prompt}

`zettcode prompt` 发一条 prompt，打印回答，然后退出 —— 用在脚本或管道里。不带 `-m` 和 `-s` 时，它用配置
文件里的第一个模型和一个新会话。

```bash
zettcode prompt "说明这个仓库是做什么的"
git diff | zettcode prompt "评审这次改动"
zettcode prompt -m "Claude Sonnet" -s 01a10b75 "测试呢？"
zettcode prompt --continue -s 01a10b75
```

| 选项 | 作用 |
| --- | --- |
| `PROMPT` | 要问什么。省掉，或者写 `-`，就从标准输入读。 |
| `-m`、`--model NAME` | 模型，用 `/model` 显示的名字。 |
| `-s`、`--session ID` | 接着一个已保存的会话。 |
| `-c`、`--continue` | 不带 prompt：接着被打断的请求，和 [`/continue`](#continue) 一样。需要 `-s`。 |
| `-e`、`--effort LEVEL` | 推理强度。 |
| `-w`、`--workspace DIR` | 在哪个目录里工作。 |

标准输出里只有回答；用过的工具和最后一行 `session: <id>` 写到标准错误。这里没有人可以问，所以 shell 权限
永远是 `auto`：模型要跑的命令不问就执行。只在你愿意把 shell 交出去的目录里用它。

## 退出码

| 码 | 含义 |
| --- | --- |
| `0` | 答完了。 |
| `1` | 这次运行失败或提前停了。`doctor` 遇到不回答的模型也退出 1。 |
| `2` | 参数用不了。 |
| `3` | `--continue` 没有找到可以接着做的东西。 |

## 下一步

- [会话](/zh/guide/sessions)：对话存在哪里，怎么回来。
- [界面](/zh/guide/interface)：屏幕上每一行是什么意思。
- [配置](/zh/guide/config)：每一个键，以及命令可以添加的模型。
- [插件](/zh/guide/plugins)：插件带来的命令。
