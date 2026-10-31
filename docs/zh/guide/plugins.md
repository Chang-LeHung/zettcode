# 插件

插件是一个 Python 包，用来给 ZettCode 加东西：一个命令、一个工具、屏幕上的一行，或者对模型
收到内容的调整。装上这个发行包就是“启用”，不需要改什么注册表。

## 插件拿到的东西：`ctx` 与三个组

插件的 `activate(ctx)` 只有一个上下文，任何进程里都是同一个类型。它能往哪里注册，取决于这个上下文有哪些组：

| 组 | 存在于 | 放什么 |
| --- | --- | --- |
| `ctx.agent` | 每个进程 | agent 扩展、模型 provider、`@` 资源、供别人查找的 service |
| `ctx.commands` | 每个进程 | 普通命令：名字、摘要、返回文本／提示／错误（绝不是一个页面）的处理器，于是哪个前端都能跑 |
| `ctx.tui` | 只有终端；其余进程为 `None` | 会开页面或需要 shell 的命令、配色、宠物、presenter、页眉/状态行、请求结束那一行的条目 |

所以插件**不需要**声明自己面向哪个前端：它往组里注册，而组是否存在，取决于它被加载到哪个进程。只加屏幕相关东西
的插件，在 `activate` 开头加一句判断即可：

```python
from zettcode.app.plugins import PluginContext, TuiPlugin


class Greeter(TuiPlugin):  # 这个 mixin 提供行相关的钩子；基类仍是同一个 Plugin
    name = "greeter"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_extension(GreeterExtension())
        if ctx.tui is None:
            return
        ctx.tui.register_theme("acme", ACME_THEME)
```

答案是文字的时候用 `ctx.commands`：它在每个进程里都存在，终端会把它和 `ctx.tui` 里的命令放在同一张表里。会开页面、
要 shell 动手、需要等请求结束的命令，放在 `ctx.tui`。

**不会因为"不是给这个前端的"而被拒绝**：插件总会被激活；真正坏掉的（导入失败、两个插件抢同一个名字）会作为失败报告出来，读者看得到。

## 安装一个插件

插件在 `zettcode.plugins` 这个 entry point 组下发布一个类：

```toml
[project.entry-points."zettcode.plugins"]
greeter = "my_package:Greeter"
```

```python
from zettcode.app.commands import CommandContext, CommandResult
from zettcode.app.plugins import PluginContext, TuiPlugin


class Greeter(TuiPlugin):
    name = "greeter"
    description = "say hello"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.tui is None:
            return
        ctx.tui.register_command("greet", "say hello", self.greet)

    async def greet(self, context: CommandContext) -> CommandResult:
        return CommandResult(notification=f"hello {context.argument}".strip())
```

把插件安装到 **ZettCode 使用的同一个 Python 环境**，再重启，命令就会出现在 `/` 菜单里，
排在内置命令之后。安装到另一个虚拟环境，不会让 `uv tool` 安装的 ZettCode 自动发现它。

也可以让 ZettCode 自己安装：

```sh
zettcode plugins install /path/to/greeter                  # 本地项目、wheel 或 sdist
zettcode plugins install ./greeter.py                      # 单个 Python 文件
zettcode plugins install owner/repo                        # GitHub 仓库
zettcode plugins install owner/repo@v1.2.0                 # tag、分支或提交
zettcode plugins install https://github.com/owner/repo/tree/main/plugins/greeter
```

命令会装进 `zettcode` 正在运行的那个环境——有 pip 就用 pip，没有就用 uv 的 pip（`uv tool` 安装的环境就是如此）。
插件在仓库的子目录里时，用上面的 `tree` 地址。重启 ZettCode，插件就在 `/` 菜单里了。

单个 `.py` 文件不会装进 site-packages，而是复制到 `~/.zettcode/plugins`：下次启动时，文件里每个继承
`Plugin` 或 `TuiPlugin` 的类都会被加载——一个文件可以有多个类，不需要指定类名。文件必须是一个模块（不能用相对导入），
而且不声明依赖——它需要的依赖按插件自己的说明安装。覆盖一个内容不同的文件会被拒绝，除非加 `--force`
（提示会说明它要替换成哪个名字）。

```sh
zettcode plugins list                  # 每个插件的名字、来源、位置和开关
zettcode plugins list --json           # 同样的内容，给程序读
zettcode plugins uninstall greeter     # 文件名（去掉 .py）、发行包名，或 entry point 名
zettcode plugins disable greeter       # 下次启动不加载
zettcode plugins enable greeter        # 重新加载
```

`list` 会列出程序自带的 agent 插件（位置是 `compiled in`）、装在旁边的发行包（entry point 名、发行包名和 site-packages 目录），
以及 `~/.zettcode/plugins` 里的单文件插件（文件路径），并说明下次启动是否加载、由哪个开关决定。编译进程序的插件
`ENABLED` 是 `-`，它的设置在旁边的 `SWITCH` 里。`uninstall` 会从 `~/.zettcode/plugins` 删掉文件，
或者卸载名字对应的发行包；名字可以是发行包名、`/plugins` 里显示的 entry point 名，或者文件名（去掉 `.py`）。
`enable` 和 `disable` 写的就是 `/plugins` 面板用的同一个开关文件；编译进程序的插件由配置里的设置控制，面板会改它，这条命令不会。

如果你想自己管理环境，也可以手动安装。例如本地已有一个插件项目 `/path/to/greeter`：

::: code-group

```bash [uv tool]
uv tool install --force --with /path/to/greeter zettcode
```

```bash [ZettCode 所在环境的 pip]
python -m pip install /path/to/greeter
```

:::

本地项目需要自己的 `pyproject.toml`、可安装的 Python 模块，以及上面的 entry point。
已经发布的插件则把路径换成它实际的包名。进入 ZettCode 输入 `/greet Ada`，就会看到
`hello Ada` 的通知。

不卸载但暂时停用，可以把下面的段落加到 `config.toml`，然后重启：

```toml
[plugins]
enabled = true
disable = ["greeter"]
```

这里的 `greeter` 是 entry-point 名称，不一定等于包名。
`enabled = false` 关闭全部第三方插件，不会关闭内置 UI。

::: warning 只安装可信插件
插件在 ZettCode 进程里执行 Python 代码，能影响模型流程和本地文件，没有沙箱隔离。
安装前应检查来源、代码和依赖。
:::

## 插件能参与什么

`Plugin` 组合了两组钩子（代理那一组在 `zettcode.engine.plugins`，屏幕那一组由 `zettcode.app.plugins`
里的 `TuiPlugin` 加上），插件只覆盖自己关心的阶段：

- **代理的工作** —— 和 `zett-agent` 扩展同一套生命周期：setup、run、turn、model、tool、
  compaction，以及外部事件。插件可以注册工具、改写发给模型的消息、转换工具结果，或者观察一次
  运行的结束。
- **屏幕** —— 头部和状态行各自分成左右两侧，每一侧都由注册过的片段共同画出来。

```python
from zettcode.app.plugins import ShellContext, TuiPlugin


class WorkspaceLabel(TuiPlugin):
    """用模型和工作区标签替换头部右侧片段。"""

    name = "workspace-label"

    def render_header_right(self, context: ShellContext) -> str:
        return f"{context.model.name} · {context.session.workspace.name}"
```

返回 `str`、带样式的 `TextLine`，或者 `None`（什么都不画）。没有自带样式的片段会继承这一行的
灰色样式，所以默认看起来是融进去的，想上色再上色。用已存在的名字注册会**原地替换**那个片段；
新名字追加在该侧已有的片段之后。返回 `(value, True)` 表示独占该侧，这是在不知道内置名字的
情况下接管整侧的做法。

还没配置模型时，`context.model.name` 是空串，`context.model.efforts` 是空元组，
`context.model.config`（那一项本身）是 `None`。读这一项的片段应该说自己没有模型，而不是假定它一定在。

## 写一个命令

命令处理器收到一个 `CommandContext`：

| 属性 | 是什么 |
| --- | --- |
| `argument` | 命令名之后去掉首尾空白的参数。 |
| `ui.markdown(text)` | 往对话里追加 Markdown。 |
| `ui.notice(text)` / `ui.error(text)` | 追加一行灰色提示 / 一行错误。 |
| `ui.notify(text, level=…)` | 弹一个 toast。 |

处理器返回一个 `CommandResult`，描述做完之后要发生什么：`message`（追加到对话的 Markdown）、
`notification`（toast）、`widget`（一个由你决定的页面，盖在对话之上）、以及 `relayout`
（这次变化会挪动屏幕布局时）。慢命令可以在运行过程中通过 `context.ui` 汇报进度，而不是憋到
最后一起说。

插件命令排在最后，也不能顶掉内置命令，所以 `/model`、`/resume` 等等永远和
[命令](/zh/guide/commands)里写的一致。

例如，一个命令可以汇报进度，也可以返回 Markdown 内容：

```python
async def greet(self, context: CommandContext) -> CommandResult:
    if not context.argument:
        context.ui.error("Usage: /greet <name>")
        return CommandResult()
    context.ui.notice("Preparing a greeting…")
    return CommandResult(message=f"## Hello\n\nWelcome, {context.argument}.")
```

用这个方法替换前面 `Greeter.greet` 即可。错误、提示和 Markdown 结果只展示在 transcript，
不是发送给模型的用户消息。用 command UI 方法输出，不要用会绕过终端界面的 `print()`。

### 让模型干活

命令可以用 `await context.require_host().prompt(text)` 跑一轮对话，效果等同于读者亲手输入了这句话：文本作为读者的消息写进 transcript、存进会话、边答边显示，最后落在那行结束语上；`@` 引用会被解析，而且命令会一直占着这次请求，直到答案回来。它返回 `False` 时什么都不会启动：文本为空、会话被另一个进程打开，或者已经有请求在跑 —— 后者的情况下，想让命令在忙时可用，就声明 `when_busy="queue"`（见[请求运行期间](#请求运行期间)）。

命令想展示的东西比它要告诉模型的短时，把两者分开传：`prompt(brief, shown="/review")` 让对话里显示 `/review` —— 现在看到的、以及会话恢复后看到的都是它 —— 而 brief 照样给模型看。brief 属于那一轮消息，所以之后每一轮模型都还能读到，短的只是展示。`/code-review` 就是这么写的。

这就是“命令是给模型的预设，而不是对模型的汇报”的写法：

```python
async def review(self, context: CommandContext) -> CommandResult:
    if not context.argument:
        context.ui.error("Usage: /review <看什么>")
        return CommandResult()
    await context.require_host().prompt(f"评审这次改动，然后列出你会改的地方。{context.argument}")
    return CommandResult()
```

### 提示第一个词

如果命令的第一个词是固定的（`/deploy staging`），可以把它列出来，补全菜单在输入命令和空格之后就会给出这些词：

```text
ctx.tui.register_command("deploy", "ship a build", self.deploy, subcommands=["staging", "prod"])
```

带说明的词用 `zettcode.app.commands.Subcommand("prod", "the live site")`；传一个返回列表的函数则每次打开菜单时都会被调用，
适合依赖当前会话的词。它们只是建议：handler 拿到的仍然是输入的原样（`context.argument`），而且只有紧跟在命令后面
的那个词会被提示。

### 请求运行期间

默认情况下，请求运行时输入的命令会被拒绝，因为大多数命令会改动这个请求正依赖的东西。注册时用
`when_busy` 另行声明：

```text
ctx.tui.register_command("status", "show the build status", self.status, when_busy="now")
```

| `when_busy` | 请求运行期间输入它会怎样 |
| --- | --- |
| `"refuse"`（默认） | 被拒绝，提示 “busy”。 |
| `"queue"` | 先记下来，请求一结束就运行，和 `/btw` 一样。 |
| `"now"` | 立刻运行，与请求并行，请求不受影响地继续。 |

只有“只读取或报告”、或者“只改请求在需要时才去读的设置”的命令才用 `"now"`。它运行时**不会**独占
忙碌状态，所以一个会修改 transcript、会话、或请求启动时所用模型的命令，会把请求脚下的地面抽走。
处理函数想等多久都可以：请求不会等它，退出时会取消它。

## 描述一个 provider {#providers}

插件可以往 `/config` 提供的列表里添加一个服务商，这样 ZettCode 不认识的服务，选中它再给一个 token
就能配好：

```python
from zettcode.engine.plugins import Plugin, PluginContext
from zettcode.providers import Provider


class Acme(Plugin):
    name = "acme"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_provider(
            Provider(
                "acme",  # `/config add acme` 里输入的名字
                "Acme AI",  # 选择器里显示的名字
                api="chat",  # chat | responses | anthropic
                base_url="https://api.acme.example/v1",
                token_env="ACME_API_KEY",  # 只用于提示，不会被读取
                note="model ids look like acme-<size>",  # 显示在旁边的一行说明：小写短语，不以冠词开头，不加句号
            )
        )
```

provider 只描述一个地址和一种协议：不会调用或连接任何东西，token 和模型 id 仍然由用户提供。
`models=("acme-small", …)` 可以给提问处提示几个 id。

名字在整个应用里唯一。如果插件注册的名字已被内置 provider（`openai`、`anthropic`、`deepseek`、
`openrouter`、`groq`、`ollama`、`custom`）占用，或被先加载的插件占用，这个插件会被跳过，并像其他加载
失败的插件一样报告。

## 提供配色 {#themes}

插件可以给 `/theme` 添加配色。每个配色都会出现在菜单里，光标移到它时就预览，用 `/theme <名字>` 切换。
ZettCode 自带的配色（`nord`、`dracula`、`gruvbox` 等）也是由一个内置插件用同样的方式提供的，所以下面
就是全部机制：

```text
from pathlib import Path

from zettcode.app.plugins import PluginContext, TuiPlugin


class Palettes(TuiPlugin):
    name = "acme-palettes"

    def activate(self, ctx: PluginContext) -> None:
        # 包里自带的主题文件：格式与 ~/.zettcode/themes/<名字>.toml 相同。
        ctx.tui.register_theme("acme", Path(__file__).parent / "acme.toml")
        # 或者一个返回 zettcode.tui.Theme 的函数；第一次被用到时才会调用。
        ctx.tui.register_theme("acme-night", build_night, description="深蓝，低眩光")
```

名字是一个词（字母、数字、`.`、`_`、`-`）。`dark` 和 `light` 属于 ZettCode。名字如果已被内置配色或更早
加载的插件占用，就会被跳过并像其他加载失败的插件一样报告。读者放在 `~/.zettcode/themes/` 里的同名文件
优先于插件提供的，所以读者总能改动别人给的配色。插件提供的配色也可以作为启动配色：
`[ui] theme = "acme"` 能找到它。

## 提供宠物 {#pets}

宠物和配色一样按名字提供，ZettCode 自带的十三只（`cat`、`dog`、`tiger`、`polarbear`、`snowbear`、`penguin`、`scarfy`、`kangaroo`、`seagull`、`whale`、`chibi`、`slime`、`sprout`）也是由一个内置插件通过同一个调用提供的。一只宠物就是一张调色板，加上它各种心情的像素图：图里的每个字符对应一种颜色，`.` 是透明，两行像素组成一行字符单元格，所以行数必须是偶数，而且同一只宠物的每一帧大小相同：

```text
from zettcode.app.pets import Pet
from zettcode.app.plugins import PluginContext, TuiPlugin

PALETTE = {"G": "#84b795", "D": "#263d34", "H": "#e4b47c"}
ASLEEP = ("..GGGG..", ".GGGGGG.", "GGGGGGGG", "GDDGGDDG", "GGGHHGGG", ".GGGGGG.")
AWAKE = ("..GGGG..", ".GGGGGG.", "GGGGGGGG", "GGDGGDGG", "GGGHHGGG", ".GGGGGG.")


class Blobs(TuiPlugin):
    name = "acme-blobs"

    def activate(self, ctx: PluginContext) -> None:
        # 心情有 "idle"（必须有：即睡着）、"working"（请求运行时）和 "glad"（被拍时）；
        # 缺少的心情就保持原样。一种心情有多帧时会循环播放。
        pet = Pet("blob", PALETTE, {"idle": (ASLEEP,), "working": (AWAKE, ASLEEP), "glad": (AWAKE,)})
        ctx.tui.register_pet("blob", pet, description="一只安静的绿色团子")
```

也可以传一个构造宠物的函数，第一次用到时才会调用。名字是一个词（字母、数字、`.`、`_`、`-`）；名字如果已被内置宠物或更早加载的插件占用，就会被跳过并像其他加载失败的插件一样报告。宠物会出现在 `/pet` 面板里，也可以作为启动时的宠物：`[ui] pet = "blob"`。

## 绘制一行 {#presenters}

对话里的每一行都由一个 *presenter* 绘制：它把一种 entry 变成带样式的行。ZettCode 自带的 presenter
也由一个内置插件注册，优先级最低，所以插件为同样的行注册一个就能覆盖，不需要压过任何东西：

```text
from zettcode.app.agent.conversation.entries import EntryKind
from zettcode.app.agent.conversation.presenters import Presenter
from zettcode.app.plugins import PluginContext, TuiPlugin
from zettcode.tui import Span, Style, TextLine


class QuietNotice(Presenter):
    kind = EntryKind.NOTICE

    def lines(self, entry, width, theme, frame):
        return [TextLine((Span(entry.text, Style(foreground=theme.muted)),))]


class QuietNotices(TuiPlugin):
    name = "quiet-notices"

    def activate(self, ctx: PluginContext) -> None:
        ctx.tui.register_presenter(QuietNotice())
```

presenter 指定一个 `kind`（`EntryKind` 的一项）；如果只画某一种子行——比如工具行里的编辑行——则指定
`entry_type`。`lines` 收到 entry、可用列数、配色和动画步数，返回 `TextLine`；宽度是预算，要自己换行或截断。
需要动画的 presenter 读 `frame`，不需要的应当对任何 `frame` 都给出同样的行。

同一个位置有多个 presenter 时，`priority` 高的赢；优先级相同则后注册的赢。内置 presenter 就是这样成为默认的：
优先级 0，最先注册。插件想压过另一个插件，就在 presenter 类上把 `priority` 提高；只想画某一个子行时不需要
优先级，注册子行本身就是更窄的声明。为整个 kind 注册的 presenter 声明接管它的每一行，所以会压过在它之前、
同级注册的子行；在那之后注册、或优先级更高的子行仍然保留自己的行。

## 把整个扩展交给代理 {#extensions}

上面的钩子方法，运行在 ZettCode 为所有插件承载的同一个扩展里。如果一个插件本身就是一个扩展，或者包装了
`zett-agent` 的某个扩展，可以把它整个交出去：

```python
from zettcode.engine.plugins import Plugin, PluginContext


class Audit(Plugin):
    name = "audit"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.config.workspace.name != "scratch":
            ctx.agent.register_extension(AuditExtension())  # zett_agent 的 AgentExtension
```

代理会把它和其他扩展并列收下，按扩展自己声明的 `priority` 排序，同级则按插件加载的先后。它的 `name`
必须唯一：重复了已注册的名字，或者叫 `plugins`，该插件会会被报告。如果扩展导入很慢，或者需要代理起始的那个模型，
更适合用 `ctx.agent.register_extension_factory(name, build)` 注册：`build` 会在构建代理时才调用，而不是在界面还在
绘制的时候，返回 `None` 表示什么都不加。代理运行的每一个扩展都是这样注册的：ZettCode 自带的代码工具、会话日志、
shell 审批、压缩、`ask_user` 工具、项目指令、skills、MCP 和待办工具都是内置插件，所以 `[harness]` 等处的开关只是决定它们的插件注册与否。

## 关掉一个插件

`/plugins` 打开一页，每个能关掉的插件前面一个开关：编译进程序的在前，装进来的在后。`~/.zettcode/plugins` 里的单文件插件
也算“装进来的”，而且无论开关状态都会列出来——被关掉的文件仍然留在页面上，只是显示为关，可以再打开。上下移动，左右和空格拨开关，Enter
把改动写下来，Esc 什么都不写。开关**下次启动**生效：当前这个会话还是用它已经加载的东西。

开关写到哪儿，看这个插件是哪一种：

- **装在程序旁边**的插件记在 `~/.zettcode/plugins.json`，那是 ZettCode 自己的文件，放在会话存储旁边。
  `/plugins disable <名字>`、`/plugins enable <名字>` 对单个名字做同样的事，配置文件的 `[plugins] disable` 写同样的
  名字，两份列表会合并。`/plugins` 不会改写你的配置文件。
- **编译进程序**的插件由你本来就有的设置决定——`[skills] enabled`、`[mcp] enabled`、`[agents_md] enabled`、
  `[harness] subagent`、`[harness] todowrite`、`[ask_user] enabled`——面板写的就是配置文件里的那个键。没有这种设置的
  内置插件根本不会列出来：它上面没有可以按的东西。（加载失败的内置插件还是会列出来，写明原因——没有什么可按，
  但这件事值得知道。）

配置文件里已经用 `[plugins] disable` 关掉的名字，两个前端里都打不开，那一行归你改。在哪儿问都是同一个答案：终端的
`/plugins` 页面、编辑器的 **ZettCode: Show Plugins** 面板以及服务器上的 `PUT /plugins/{name}`，走的是同一套规则、
写的是同样的文件。

## 出问题的时候

导入或激活失败的插件会被跳过，而不是让程序挂掉：对话里出现一行 `plugin: …`，会话继续正常
工作。两个插件不能重名；抢同一个命令名时，后一个会被跳过，而不是悄悄替换前一个。
