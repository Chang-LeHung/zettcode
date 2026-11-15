# 界面

屏幕是一个固定框架，中间是滚动的对话：输入框停在底部，需要选择时面板盖住下面一部分。

```
  ▐ zettcode  New session · @api · ~/projects/api   DeepSeek Pro · high  ← header
 ─────────────────────────────────────────────────────────
 ● Read src/api/users.py · 199 lines                       ← transcript
 ● Edit src/api/users.py +24 -6                         (scrolls)
 ● Bash pytest tests/test_users.py
 ─────────────────────────────────────────────────────────
   ▸ panels open here: model, context, sessions           ← panel
 ─────────────────────────────────────────────────────────
   /model  /resume  /context                              ← completions
 › add a limit/offset window to GET /users                ← composer
   ● ready  ↑18.4k ↓900 · ctx 12.3%                       ← status line
```

## 头部

左侧写明程序、会话和工作目录。

- 会话有标题之前显示 `New session`；开着[会话互发消息](/zh/guide/messaging)时，标题后面跟着它的 `@名字`。
- 工作目录只留路径最后有用的那一段。
- 终端太窄时先截断标题，再截断工作目录。

右侧写明**下一次**请求要用的模型和思考强度。

## 对话区

每件事一行，按发生顺序排列。

- **你发的消息**前面标 `›`。
- **思考**折成一行；按 `Ctrl-T` 或点一下展开最新一段，每段也能单独展开。
- **工具调用**像日志：`Read src/app.py · 199 lines`、`Bash pwd`、`Edit app.py +24 -6`、`Write src/new.py +40`、
  `Searched TODO in src`。

  成功的编辑在行下给出改动：删掉的行红、加上的行绿，前后各留一行未变的做参照。写入整份文件时每一行都算新增。
  失败的编辑显示错误。前五行始终可见，其余点开再看，最多四十行；长行截断，不折行。

- **一次请求改过的文件**在请求结束时列一次，位置在 `Processed for …` 之上。一个文件一行
  （`Changed src/app.py +4 -1`）；多个文件是小列表（`Changed 3 files`，八行，之后是 `and N more`）。路径相对工作
  目录。只有成功的编辑、写入和删除才算数，被停掉的请求也照实报告已经做完的部分。shell 命令改的文件看不到。
- **回答**按 Markdown 渲染，表格能处理宽的 CJK 字符，HTML 实体画成它指代的字符。
- **正在跑的请求**固定在底部一行：`✦ Processing (8s · ^C/Esc to interrupt)`。请求结束后这一行变成
  `Processed for 12s · 22:53`，后面跟着它花掉的：`↑12.3k ↓1.2k · 87.0% cached · 3 model calls · 62 tok/s · 5 tool
  calls, 1 failed`。

  模型二十秒没出声时，这一行用警示色说明。五秒后行下挂一条提示，用的就是工具结果那个 `└`，每十五秒换一条；
  `[transcript]` 下的 `tips = false` 关掉它们。
- **失败的请求**给出库报的错，并在括号里给出服务端的回答，还点名该查哪个设置。服务商或网络的问题，行尾补一句
  `/continue tries the request again from where it stopped.` 疑似凭据的内容换成 `…`，这一行可以直接贴进 issue。
- **没正常结束的回答**会说明原因——输出上限、被服务商截断或暂停、上下文窗口满了、模型拒答——以及该怎么办：
  `/continue`、`/compact`、`/model`。
- **提示**——复制了选区、命令被拒、导出了文件——是灰的一行。

`Page Up` / `Page Down` 和滚轮滚动，终端每发一个事件走一行；一帧最多走半屏。嫌慢就调
`transcript.mouse_scroll_speed`。向上翻时出现 `↓ back to bottom` 标记；按 `Esc` 回到最新一行，请求在跑时
`Esc` 则停止它。

## 输入框

`›` 提示符随草稿长高，最多占屏幕的一部分。

- **Enter** 发送；**Alt-Enter** 或 **Shift-Enter** 换行。
- **`/`** 打开命令菜单，**`@`** 打开资源菜单（技能、文件和其他正在跑的会话）。`↑` / `↓` 选，`Enter` 或
  `Tab` 填入，`Esc` 关闭。
- 超过 512 个字符、或高过输入框能长的程度，粘贴内容变成 `[pasted text 6012 chars]` 块；`Backspace` 整块删掉，
  发送时文本恢复。
- **Ctrl-V** 把图片附成 `[image #N]` 块；文字和图片保持你写的顺序。
- `/命令` 和 `@资源` 只有真的存在才上色：命令必须是第一个词。`Backspace` 删假的按字符删，删真的整块删。

## 请求运行时输入

模型工作时继续输入并按 Enter，ZettCode 会问这条消息算什么：

```text
You sent a message while ZettCode is working. What should it do?

› then open a pull request

▸ 1. Follow up  send it after this request finishes (f)
  2. Steer      hand it to the agent now; it replaces the rest of the current task (s)

enter choose · f follow up · s steer · esc keep editing the draft
```

`f` 和 `s` 直接选一行，`Enter` 选高亮的那行（Follow up），`Esc` 把草稿留在输入框。只有一种可能时——比如正在跑
`/compact` 这类不能引导的命令——它什么也不问。

**Steer（引导）**放进输入框上方的 `↳ steer` 列表。智能体在下一个安全点读到它，丢掉当前任务剩下的部分；最多排
八条。它是同一个任务的新指令，不会撤销已经做的修改。智能体拿到之后就不能再改。

**Follow up（后续）**放进输入框正上方的 `• follow-up` 列表，在这轮对话顺利结束后自己发出去——一次一条，按顺序，
最多八条。你可以移动、编辑、改成引导或删掉；按键见[快捷键与鼠标](/zh/guide/keys)。

停掉请求不会把列表发出去，也不会丢掉：列表显示 `held until your next reply completes`，在下一条完成的回复之后
发出。`/new`、`/resume` 和 `/fork` 把列表退回输入框变成文本，智能体没读到的引导消息也退回去。要它立刻停下，
按 `Esc`。

## 弹窗与审批

需要选择时，命令弹一个面板。`↑` / `↓` 移动，`Enter` 确认，`Esc` 回到输入框，对话区在下面积着不动。

- `/model` 选之后请求用的模型。`/resume` 选最近的会话，带标题和改动时间。
- `/context` 看上下文窗口被什么占着。`/usage` 看这个项目花掉多少，占满整个屏幕。见[Token 用量](/zh/guide/commands#usage)。
- **审批**面板问要不要跑一条 shell 命令。

`/theme` 和 `/permission` 用命令菜单；`/effort` 打开一条用 `←` `→` 滑动的档位条。

模型提问时——格式、用哪个文件、要不要继续——面板的高度只够这个问题。`↑` / `↓` 和 `Enter` 管选项，也可以自己
打字回答。`Esc` 拒绝。

### 审批

`bash` 是唯一会问的工具。`/permission` 随时改它多久问一次：

| 级别 | shell 命令会怎样 |
| --- | --- |
| `deny` | 一条也不跑。模型被告知命令已关闭，改用文件工具。 |
| `ask` | 每条都等你回答。新会话从这里开始。 |
| `safe` | 每条都不问，在操作系统沙箱里跑。 |
| `full` | 每条都用你自己的权限跑，不问，也没有沙箱。（`auto` 仍然可用。） |

级别只管 shell。文件编辑和 MCP 工具不问，所以 `deny` 不是只读模式。新会话从 `ask` 开始；恢复的会话沿用上次的
级别。

在 `ask` 下，面板给出命令和它所在的目录。

| 按键 | 作用 |
| --- | --- |
| `y` | 只跑这一次。 |
| `p` | 跑，并在本次会话里记住这条命令。记住的是命令文本，不是目录。 |
| `s` | 跑，并且以后不问：后续命令都在沙箱里跑。`safe` 下不提供。 |
| `a` | 跑，并且以后不问：完全访问，没有沙箱。 |
| `Esc` | 拒绝。智能体被告知命令失败，可以另想办法。 |

### `safe` 沙箱允许什么 {#the-safe-sandbox}

macOS 用 Seatbelt（`sandbox-exec`），Linux 用 bubblewrap（`bwrap`）。沙箱里的命令可以：

- **写**工作目录和临时目录，别处不行；
- **读**机器其余部分，凭据所在的地方除外（`~/.ssh`、`~/.aws`、`~/.gnupg`）；
- 不联网，除非在 `[shell]` 下设 `network = true`；
- 不改 `.git/hooks`、`.git/config` 或 shell 启动文件，工作目录里的也不行；
- 只看得到一小串环境变量。

Windows 和没有 `bwrap` 的 Linux 没有这样的沙箱：`safe` 只跑只读命令，别的都问。

`safe` 只在命令的每一部分都在只读程序清单上时（`ls`、`cat`、`grep`、`git status`……）不问就跑。`;`、`&&`、
重定向和 `$(…)` 都会问。只读命令也可能打印出工作目录里的秘密：`safe` 保证不变，不保证不被看见。`git` 配置可以
指定要跑的程序，可能藏着这种东西的工作目录请用 `ask`。

## 旁路提问（btw）

`/btw <问题>` 问一件模型凭已有的知识就能答的事。回答像普通一轮那样出现，标着 `btw ›`，底色单独一块。

它会写进会话文件，但从不回放进模型的上下文，之后几轮不知道发生过。恢复会话时它会回到对话区，但不会进
[导出](/zh/guide/sessions#导出)。只提供读取类工具，所以改动不会溜出这轮对话。请求在跑时提问会等它结束；token
照样计数，也不触发压缩或命名。

## 图片与粘贴

**Ctrl-V** 自己读剪贴板，在图片该在的位置插入 `[image #N]` 块。PNG、JPEG、WebP 和 GIF 都按原始格式作为图片
部分发出去。

通过 `ssh` 时它看不到你本机复制的图片：把文件放到服务器上，用路径引用它。

恢复的会话显示块，不显示图。`multimodal = false` 的模型会拒绝附图。见[模型](/zh/guide/models)。

## 通过 `ssh` 复制 {#copying-over-ssh}

在服务器上，选区经 OSC 52 由你的终端复制，落在你坐着的这台机器上；提示写 `sent`，因为程序看不到终端是否接受。
如果转发的显示让服务器的剪贴板才是你要的那个，设 `ZETTCODE_CLIPBOARD=system`。终端不支持 OSC 52 就什么也复制
不了，此时按住它自己的修饰键（<kbd>Shift</kbd> 或 <kbd>Option</kbd>）再拖。

## 状态行

左半边说正在发生什么、花了多少；右半边留着两个值得记的键（`^C/Esc to interrupt`、`^D exit`）。

| 片段 | 含义 |
| --- | --- |
| `●` / 闪动的 `✦` | 圆点是空闲，闪动的星是在干活。 |
| `ready`、`running` | 当前状态，或一句临时说明。 |
| `· deny`、`· safe`、`· full` | 不是默认的 `ask` 时，显示 shell 权限。 |
| `↑18.4k ↓900` | 本次会话发出去和生成的 token。 |
| `71.2% cached` | 输入里由服务商缓存承担的比例。 |
| `74 tok/s` | 本次会话的生成速度，每秒 token。 |
| `ctx 12.3%` | 最新一次请求占掉了模型窗口的多少。 |

### 选择显示哪些部分 {#choosing-what-is-shown}

两条栏里的每个词都属于一个有名字的部分，没关掉之前都显示。`/statusline` 把它们列出来——`ctx`、`cache`、`model`、
请求结束行里的 `turn-*`、`pet` 等等——`Enter` 应用，`Esc` 保持原样。在 `config.toml` 里，每个关掉的部分一行：

```toml
[statusline]
ctx = false
```

`/statusline hide ctx speed` 和 `/statusline show all` 在键盘上做同样的事。终端变窄时，最不重要的数字整个省掉
——先是 `speed`，再是 `cache`，再是 `tokens`——`ctx` 留下。

## 宠物 {#the-pet}

对话右侧可以站一个小伙伴。它默认关着，把 `[statusline]` 下的 `pet` 设成 `true`，或在 `/statusline` 里打开
`pet` 部分才出现。`/pet` 打开面板，`/pet whale` 一步选定。用鼠标拖它就能换地方，位置会为之后的会话保存。终端
窄于 80 列时不画它。见 [`/pet`](/zh/guide/commands#斜杠命令) 和[可选功能](/zh/guide/config#可选功能)。

## 下一步

- [快捷键与鼠标](/zh/guide/keys)：所有按键和鼠标操作都在一页。
- [命令](/zh/guide/commands)：所有斜杠命令和 `zettcode` 命令行。
- [配置](/zh/guide/config)：所有设置，包括 `[transcript]`、`[statusline]` 和 `[tools]`。
