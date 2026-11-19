# 插件 API

这一页写给要写插件的人。安装、开关和排错见[插件](/zh/guide/plugins)。插件是一个 Python 包，它向程序注册东西；能注册的东西都在这一页。

## 加载器找的是什么

单位是一个带 entry point 的 Python 发行包——或者 `~/.zettcode/plugins` 里的单个 `.py` 文件：

```toml
[project.entry-points."zettcode.plugin"]
journal = "my_package.plugin:Journal"
```

左边的 `journal` 是插件的 **origin**：`[plugins] disable` 用它，`PLUGIN_CLI` 的值也按它分组。右边是
`Plugin` 子类。它的 `name` 是身份，默认等于 entry-point 名字。配置在 `[plugins.<name>]`，`deps` 也用
`name`；`[plugins] disable` 和 `/plugins` 匹配的是 **origin**（entry-point 名字），即使插件声明了别的
`name`。包改名时这个区别才有意义。

加载器接受一个类、一个无参工厂或一个实例；类是最常见的写法。`zettcode-plugin-api` 是插件唯一需要的依赖，插件运行要用的一切都在里面。要标注 SDK 的类型，就从拥有它的模块导入：`Client` 来自 `zettcode.sdk`，`ModelInfo` 来自 `zettcode.sdk.types`，`Usage` 两边都有。这些模块不在 `zettcode-plugin-api` 里，在只装你自己的包的 CI 或 lint 环境里，用 extra `dependencies = ["zettcode-plugin-api[types]>=0.4,<0.5"]`，它会带上 `zettcode-sdk`。配色或 presenter 标注里的 `Theme` 来自 `zettcode.tui`，它随 `zettcode-plugin-api` 安装。

## 一个最小插件

```python
from zettcode.plugin_api import CommandContext, CommandResult
from zettcode.plugin_api import PluginContext, TuiPlugin


class Greeter(TuiPlugin):
    name = "greeter"
    description = "say hello"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.tui is None:
            return
        ctx.tui.register_command("greet", "say hello", self.greet)

    async def greet(self, context: CommandContext) -> CommandResult:
        return CommandResult(notification=f"hello {context.argument}")
```

配上上面的 entry point、装好包，`/greet Ada` 会弹出一句 `hello Ada`。插件的命令盖不掉终端自己的命令，所以
`/model`、`/resume` 等命令不会被换掉。

## 插件如何加载

加载器按这个顺序做一次：

1. 发现已安装的 entry point 和 `~/.zettcode/plugins` 里的单个文件。
2. 实例化每个类。构造函数要便宜，不该读工作区，也不该调模型。
3. 为该插件建一个 `PluginContext`，调用 `activate(ctx)`。这一步同步是故意的：它只注册插件贡献的东西，绝不
   await、绝不启动工作，所以 shell 或 agent 建立之前，所有注册都已经完成。
4. 检查重复的 command、extension、service、theme、pet、trigger 和 provider 名字。
5. 合并进应用。`Plugin` 的 hook 跑在一个宿主 extension 里；用 `register_extension()` 注册的整个 extension
   跑在它旁边。
6. 退出时调用一次 `await plugin.aclose()`，最新的插件先。

加载器故意宽容：导入或激活失败的插件报成 `plugin: …`，程序其余部分照常工作。依赖和顺序见[依赖别的插件](#deps)。

插件不分终端插件和服务器插件。它在任何地方拿到的都是同一个 `PluginContext`；没有屏幕的进程里 `ctx.tui`
就是 `None`。可移植的部分对着 `ctx.agent`、`ctx.commands` 和 service 写，屏幕相关的部分用这个挡住：

```text
if ctx.tui is None:
    return
```

加载器不按前端筛插件。插件在加载它的每个进程里都会被激活，所以只在屏幕上有意义的活必须放在这个 guard
后面；否则激活失败，它别的注册也一起丢掉。

## 一个完整插件

这个插件加一个 `/journal` plain 命令，声明一个配置项和一个启动参数，并读取应用交给它的 service。把它存成
`plugin.py`，加上上面的 entry point，装包，重启。

```python
from zettcode.plugin_api import (
    PLUGIN_CLI,
    CliOption,
    PlainCommandContext,
    Plugin,
    PluginContext,
    TextCommandResult,
)


class Journal(Plugin[PluginContext]):
    name = "journal"
    description = "Keep a short, local journal of what this session is doing"

    @classmethod
    def cli_arguments(cls) -> tuple[CliOption, ...]:
        """Read before activation; values arrive in the PLUGIN_CLI service."""
        return (
            CliOption(
                ("--journal-limit",),
                "limit",
                help="how many recent entries to show",
                default="3",
                metavar="N",
            ),
        )

    def activate(self, ctx: PluginContext) -> None:
        given = ctx.settings.declare(prefix="session")
        cli = ctx.service(PLUGIN_CLI, dict).get("journal", {})
        self.prefix = str(given["prefix"])
        self.limit = int(cli.get("limit", "3"))
        ctx.commands.register("/journal", "show recent journal entries", self.show)

    async def show(self, context: PlainCommandContext) -> TextCommandResult:
        if not context.argument:
            return TextCommandResult(message=f"{self.prefix}: nothing chosen")
        return TextCommandResult(message=f"## {self.prefix}\n\nLast {self.limit} entries about: {context.argument}")
```

运行 `zettcode --journal-limit 5`，在输入框里敲 `/journal tests`。同一个插件对
`zettcode daemon spawn --journal-limit 5` 启动的守护进程也可用。

## 上下文和它提供的 service

`PluginContext` 是插件通向应用唯一的渠道。它的属性是 service 的简短类型别名，两种写法都支持：

```text
ctx.config is ctx.service(PLUGIN_CONFIG, ZettCodeConfig)
ctx.agent is ctx.service(PLUGIN_AGENT, AgentGroups)
ctx.commands is ctx.service(PLUGIN_COMMANDS, CommandGroups)
ctx.tui is ctx.find(PLUGIN_TUI, TuiGroup)       # None without a screen
```

### 上下文给了什么

| 成员 | 类型 | 用途 |
| --- | --- | --- |
| `ctx.config` | `ZettCodeConfig` | 解析后的配置；只读 |
| `ctx.workspace` | `Path` | 这个会话工作的目录 |
| `ctx.settings` | `PluginSettings` | 声明和读取 `[plugins.<name>]` 的键 |
| `ctx.agent` | `AgentGroups` | extension、provider、mention、trigger、service |
| `ctx.commands` | `CommandGroups` | 每个前端都能用的 plain 命令 |
| `ctx.tui` | `TuiGroup \| None` | 只在终端有的命令、行、配色、宠物、presenter |
| `ctx.service(name, kind)` | `T` | 必需的 service；缺失时抛 `LookupError` |
| `ctx.find(name, kind)` | `T \| None` | 可选的 service；缺失时返回 `None` |
| `ctx.provide(name, value)` | `object` | 给后面的插件提供一个 service |

`ctx.service` 和 `ctx.find` 会核对 `kind`。类型不对是 `TypeError`，不是悄悄返回 `None`。`ctx.provide`
拒绝本插件已经提供过的名字、六个 context 自有的名字，以及空名字；加载器拒绝另一个插件已经发布过的 service
名字。

### 应用提供的 service

名字是 `zettcode.plugin_api` 导出的常量。可用性才是重点：屏幕和消息相关的 service 不在每个进程里都有。

| service | 类型 | 什么时候有 | 用途 |
| --- | --- | --- | --- |
| `PLUGIN_AGENT` | `AgentGroups` | 总是 | extension/provider/mention/trigger 注册 |
| `PLUGIN_COMMANDS` | `CommandGroups` | 总是 | plain `/commands` |
| `PLUGIN_TUI` | `TuiGroup` | 只在终端 | 屏幕命令、行、配色、宠物、presenter |
| `PLUGIN_CONFIG` | `ZettCodeConfig` | 总是 | 解析后的配置 |
| `PLUGIN_WORKSPACE` | `Path` | 总是 | 会话的工作区 |
| `PLUGIN_SETTINGS` | `PluginSettings` | 总是 | 这个插件的配置表 |
| `LLM` | `ModelAccess` | engine | `.models` 和 `.ask(...)` 旁问 |
| `PLUGIN_CLI` | `dict[str, dict[str, object]]` | engine | 解析后的插件命令行参数 |
| `HOST_LINK` | `HostLink` | 终端 | TUI 命令用的、晚绑定的 `CommandHost` |
| `INBOX` | `Inbox` | 加载了消息插件 | 把一个事件交给会话 |
| `SESSION_STORE` | `SessionStoreService` | engine | 列出已存会话 |
| `USAGE_LEDGER` | `UsageLedgerService` | engine | 读 token 用量 |
| `CONTEXT_REPORT` | `ContextReportService` | engine | 某个会话的上下文报告 |
| `CONTEXT_PAGE` | `ContextPageService` | engine | `/context` 页面数据和写入 |
| `MODELS` | 按 `ModelConfig` 索引的 provider 适配器 | engine | 已经建好的模型 |
| `CAPABILITIES` | `ModelCapabilities` | 内置 capabilities 插件 | 按模型筛工具 |
| `POLICY` | `ShellPolicy` | engine | 当前的 shell 权限策略 |
| `PERSISTENCE` | `SessionStore` | engine | 存储实现 |
| `COMPACTION_COUNTER` | `CompactionCounter` | engine | token 记账 |
| `SELECTED_MODEL` | `ModelConfig` | engine，配置了模型时 | 下一次运行用的模型 |
| `APPROVAL`、`USAGE`、`CONTEXT`、`SIDES`、`COMPACTION`、`TODOS` | engine 契约 | 内置功能插件 | 各功能 service |

`HARNESS` 和 `DELIVERY` 是 engine 内部 service，不属于插件契约，没有类型化的读取入口。表里的类型由
`zettcode.plugin_api` 导出（契约本身在 `zettcode.engine`）。

插件**可能提供、也可能不提供**的东西用 `ctx.find`，尤其是 `INBOX`、`HOST_LINK`、`SELECTED_MODEL`
和几个页面 service。只有插件的 README 说它的依赖会提供时，才用 `ctx.service`。缺一个必需的 service 是清楚的
`LookupError`，不是悄悄给个默认值。

### 模型访问

`LLM` 是给“要一个模型回答、但不想开一轮”的插件用的 service：

```text
from zettcode.plugin_api import LLM, ModelAccess

access = ctx.service(LLM, ModelAccess)
for model in access.models:
    ...
answer = await access.ask("Summarise the failing test", origin="journal")
```

这是一个旁问：问答不进对话，恢复的 transcript 也不会还原插件的问题。完整签名是
`ask(question, *, origin="plugin", cache="read", timeout=None)`。前端还没绑好对话之前 `LLM.ask` 抛
`RuntimeError`，所以它不能在 `activate` 里用。插件拿到的是当前这次运行的模型；`ModelAccess` 不会改读者选中的
模型。

## 插件能参与什么

`Plugin` 组合了两组 hook，插件只覆盖自己需要的阶段（agent 那组在 `zettcode.engine.plugins`；屏幕那组由
`TuiPlugin` 加上；两组都由 `zettcode.plugin_api` 重新导出）：

- **agent 的活** —— 和 `zett-agent` extension 一样的生命周期：setup、run、turn、model、tool、compaction、
  外部事件。插件可以注册工具、改写发给模型的消息、改写工具结果，或者在一次运行结束时看一眼。
- **屏幕** —— 标题行和状态行各自分成左右两边，每一边都由注册上来的片段画。
- **窗口和轮次** —— 终端启动时会请求焦点报告，所以插件能知道读者离开和回来；也能知道一轮对话的开始和结束。
  做总结、通知、或者等读者停下来的插件都建在这上面：

```python
from zettcode.plugin_api import PluginContext, TuiPlugin


class Away(TuiPlugin):
    name = "away"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.tui is None:
            return
        ctx.tui.register_focus_handler(self.focused)
        ctx.tui.register_turn_start_handler(self.started)
        ctx.tui.register_turn_end_handler(self.ended)

    def focused(self, focused: bool) -> None:
        """The terminal window gained (``True``) or lost (``False``) focus."""

    def started(self) -> None:
        """A turn of the conversation is starting, before its request goes out."""

    def ended(self, completed: bool) -> None:
        """A turn of the conversation ended; ``completed`` is false for a stopped or failed one."""
```

这两种都不是行，也都不能消费任何东西：它们只是被通知，拿来干什么由插件自己决定。hook 被通知的时刻也不能乱动：
它跑在刚结束的那个请求里，shell 还没空出来，所以凡是会自己开一轮的活——`HOST_LINK` 宿主的 `prompt(...)`，或
`INBOX.deliver(..., mode="followup")`——都要排出去，不能在 handler 里做。

什么算一轮：读者发出的请求，或者另一个会话发来、这个会话回答的请求。跑一个命令本身不是一轮，虽然命令用
`host.prompt` 开的那一轮算；旁问和恢复的请求也不算。不上报焦点的终端（``DECSET 1004``）只是永远不调用第一个
hook，别的都不变。

```python
from zettcode.plugin_api import ShellContext, TuiPlugin


class WorkspaceLabel(TuiPlugin):
    """Replace the header's right segment with a model/workspace label."""

    name = "workspace-label"

    def render_header_right(self, context: ShellContext) -> str:
        return f"{context.model.name} · {context.session.workspace.name}"
```

可以返回 `str`、带样式的 `TextLine`、`Row`，或 `None`（不画）。`Row` 由具名的片段拼成
（`row.add(name, summary, text)`），`/statusline` 切换的就是它们；`lead`/`trail` 是首尾的固定文字。没有
自己样式的 span 继承这一行的弱化样式，所以片段默认融进去，想要颜色时才自己上色。用已经存在的名字注册会**替换**
那一段；新名字追加在已有的后面。返回 `(value, True)` 表示整边接管。

还没配置模型时，`context.model.name` 是空的，`context.model.efforts` 是空的，`context.model.config` 是
`None`。读它的片段应该说没有模型，而不是假设有。

## 默认关闭

读者没表态时，插件是否开启由插件自己决定。覆盖 `default_enabled` 返回 `False`；加载器会把它放下，直到
`[plugins] enable` 点了它的 entry point：

```python
class Quiet(TuiPlugin):
    name = "quiet"

    @classmethod
    def default_enabled(cls) -> bool:
        return False
```

```toml
[plugins]
enable = ["quiet"]
```

默认是 `True`，所以什么都不说的插件照旧加载。这种状态的插件在 `/plugins` 和 `zettcode plugin list` 里画成
**off**——加载器根本没装它，写 on 就是在骗人——那一行写着 `off by default; [plugins] enable turns it on`。
按它的开关（或运行 `zettcode plugin enable quiet`）会把这个名字写进 `[plugins] enable`。一个例外：只因为别的
插件需要它才加载的插件可能要按两次，因为页面不加载它就问不到它的类——那一行会说第二次按写哪一行。

## 命令行参数

插件用类方法 `cli_arguments()` 声明启动参数：

```text
CliOption(flags=("--journal-limit",), dest="limit", help="...", default="3", metavar="N")
```

加载器在读取配置之前就从插件类读到声明，所以工作区还没选定时参数就能用。解析后的值是 `PLUGIN_CLI` service，
按 entry-point 名字分组：

```text
limit = ctx.service(PLUGIN_CLI, dict).get("journal", {}).get("limit", "3")
```

参数是全局的，放在子命令之前：`zettcode --journal-limit 5 resume ID`。`zettcode daemon spawn` 接受同样的
参数，并通过 JSON 私下传给子进程。值必须是 JSON 安全的（`str`、数字、bool、list、dict、`None`）。撞车的参数名
或非 JSON 的默认值会让整个声明被跳过并给一条消息，绝不会有 traceback。

只有 **entry point** 插件能声明这些参数。声明是建缓存时从插件类读的；单个 `.py` 文件没有 entry point，它的
`cli_arguments()` 永远不会被问到。刷新缓存会导入每个已安装的插件类，包括关掉的那个——让那个模块保持好导入。
`zettcode --help` 故意跳过发现，所以不列这些参数；`zettcode daemon spawn --help` 会列。`~/.zettcode/.ztrc`
只在会话启动时预置它们，对 `daemon spawn` 不管用。

为了让交互式启动快，解析器从 `~/.zettcode/plugin-cli.json` 读这些声明，而不是导入每个插件。缓存缺失或过期时，
一个守护线程去导入插件类并刷新；所以装完或改完插件后的第一次启动没有新参数，下一次才有。缓存没有时不等它；
`prompt`、`doctor`、`--dry-run` 和 `daemon spawn` 会同步刷新，因为它们结束得太快，等不到后台线程。如果 `.ztrc`
在缓存还不存在时就点了插件参数，那一次启动会同步刷新声明并应用它们，预置不会丢。

## 读配置

有配置的插件自己声明配置，以及读者没写时每个键的取值。配置文件不可能知道装了哪些插件，所以它把每个插件自己的表
原样留着（`[plugins.<name>]`），键是什么意思由插件决定。`<name>` 是插件声明的 `name`；一个以 `greeter`
发布、但声明 `name = "greeting"` 的插件写 `[plugins.greeting]`，却要用 `disable = ["greeter"]` 关掉，
因为开关用的是 entry-point origin：

```python
def activate(self, ctx: PluginContext) -> None:
    given = ctx.settings.declare(after_seconds=180, quiet=False)
    self.after_seconds = int(given["after_seconds"])
    self.quiet = bool(given["quiet"])
```

读者写的值优先；类型和默认值不一致的值在插件激活时被拒绝，并指出表和键；读一个插件从未声明过的键是错误，不是
悄悄给默认值。没装某个插件时留着它的 `[plugins.recap]` 表无害。

```toml
[plugins.recap]
after_seconds = 240
quiet = true
```

`declare` 可以调用多次，每次加几个键：默认值是读者那张表被核对的依据，也是它什么都不说时的取值。

插件的配置表和 `[plugins]` 开关在同一个文件里并排。`[plugins.recap]` 不需要你自己写 `[plugins]` 一行就能
工作，`/plugins` 和 `zettcode plugin disable` 会写在它旁边：文件里只有 `[plugins.<name>]` 表时，它们把
`[plugins]` 头加在文件末尾、你的表下面，你写的东西一处不动。用别的方式声明 `plugins` 的文件（内联表、
`plugins.disable = []` 这样的点号键、`[[plugins.<name>]]`、`[plugins.disable]` 表）不会被改；它们会说一声，
留给你。

## 两套命令系统

回答是文字或文档的命令用 `ctx.commands`；它在每个前端都能跑。需要终端页面、shell、活的行或 `CommandHost`
操作的命令用 `ctx.tui`。

| | `ctx.commands` | `ctx.tui` |
| --- | --- | --- |
| handler 的 context | `PlainCommandContext` | `CommandContext` |
| 返回 | `TextCommandResult` 或 `TurnCommandResult` | `CommandResult` |
| 没有屏幕也能跑 | 能 | 不能 |
| handler | 同步或异步 | 异步 |
| 名字 | 要带 `/` | `/` 可省 |
| shell 访问 | `PlainCommandHost`（`compact`、`title`、`export`、`locked`、`session_id`、`workspace`、`hub`） | 完整的 `CommandHost` |
| 页面/组件 | 没有 | `CommandResult.widget` |

plain 命令的 `host` 可能是 `None`：终端适配器传 `None`，服务器传真的 `PlainCommandHost`。用它之前先判空。
`hub()` 返回 `you`、`sessions`、`daemons`、`edges` 和 `error`；每个条目的字段写在 ABC 的 docstring 里。

`CommandHost` 是终端命令的 shell API：`client`、`agent`、`transcript`、`commands`、
`prompt(text, *, shown=None, cache=None)`、`close_page`、`request_layout`、`wait_for_frame`、`offer`、`quit`、
`select_session`、`resume_session`、`fork_session`、`rename_session`、`run_continue`、`run_side_question`、
`change_model`、`select_model`、`change_effort`、`change_permission`。`CommandContext.require_host()` 返回它，
否则抛 `RuntimeError`。`CommandAgent` 暴露 `session_id`、`workspace` 和 `require_session()`；
`CommandTranscript` 暴露 `notice`、`error`、`markdown`、`start_compaction`、`complete_compaction` 和 `clear`。

## 写一个命令

命令拿到一个 `CommandContext`：

| 属性 | 是什么 |
| --- | --- |
| `argument` | 命令名后面去掉首尾空白的文本 |
| `ui.markdown(text)` | 往对话里追加 Markdown |
| `ui.notice(text)` / `ui.error(text)` | 加一行弱化或报错的行 |
| `ui.notify(text, level=…)` | 弹一个 toast |

handler 返回一个 `CommandResult`，说明结束时该发生什么：`message`（加进对话的 Markdown）、`notification`
（toast）、`widget`（盖在对话上的一页，你自己画），以及改动会挪动屏幕时的 `relayout`。慢命令可以在跑的时候
通过 `context.ui` 报进度。

要等模型、或者任何要花几秒的命令，把等待返回出去，而不是在里面做完：`intro` 说明正在发生什么，`run` 是剩下的
结果。shell 把 `intro` 放进读者正在看的那一行，等 `run`，它回答时收尾；Ctrl-C、Escape、读者发的下一行、
空输入框上按 Enter 都会停掉它，那一行写着 `stopped`。

```python
from zettcode.plugin_api import (
    HOST_LINK,
    CommandContext,
    CommandResult,
    HostLink,
    PluginContext,
    TuiPlugin,
)


class Recap(TuiPlugin):
    name = "recap"

    def activate(self, ctx: PluginContext) -> None:
        # The shell does not exist yet; this is how a command reaches it when it runs.
        self.link = ctx.find(HOST_LINK, HostLink)
        if ctx.tui is not None:
            ctx.tui.register_command("recap", "summarise this session", self.recap)

    async def recap(self, context: CommandContext) -> CommandResult:
        return CommandResult(intro="Recap \u2026 writing", run=self.really_recap())

    async def really_recap(self) -> CommandResult:
        if self.link is None or self.link.host is None:
            raise ValueError("The shell is not ready yet")
        host = self.link.host
        answer = await host.client.session.ask("Recap where this session is, briefly.", cache="read", origin="recap")
        return CommandResult(message=f"> {answer}")
```

`ask` 是旁问：这一段问答不进对话，shell 也不画它，因为它没开一轮。`origin="recap"` 是另一半：它说明是谁问
的，不是读者自己问的问题不会进入恢复会话时重建的 transcript。用默认 `origin="reader"` 的命令，重开之后会在
屏幕上看到自己说的话。回答只出现在命令放它的地方——这里是引用。`/btw` 是同一类问题，带读者的 origin，所以
shell 会画它，也会还原它。

插件的命令盖不掉终端自己的命令，所以 `/model`、`/resume` 等永远按[命令](/zh/guide/commands)里说的做。

### 返回一个文档

注册在 `ctx.commands` 上的命令返回 `TextCommandResult` 或 `TurnCommandResult`——都不需要终端。
`TextCommandResult` 有三个都可选的字段：`message` 是对话里的一行，`notification` 是 toast，`markdown`
是前端在自己的一页里展示的文档。读者是要读、不是要滚过去的回答用 `markdown`——报告、评审、插件自己数据的一页
——`message` 留空或放一句提示：

```python
from zettcode.plugin_api import PlainCommandContext, TextCommandResult


def notes(context: PlainCommandContext) -> TextCommandResult:
    """Answer with a document, which the front end shows in a view of its own."""
    return TextCommandResult(markdown="# Notes\n\n- the build is green\n- two things to read")
```

在 `activate` 里用 `ctx.commands.register("/notes", "show the notes", notes)` 注册——plain 命令要带 `/`。
它的 context 有 `argument`、`level`（`deny`/`ask`/`safe`/`full`），以及可选的 `host`（`compact()`、
`title()`、`export()`、`locked`、`session_id`、`workspace`、`hub()`）。终端适配器传 `host=None`；需要 host 的
plain 命令必须处理这种情况。`markdown` 是一个字段而不是新的结果类型，所以对着旧契约写的东西不会有任何变化：
不认识这个字段的前端仍然运行命令、仍然显示 `message`；`TurnCommandResult` 是第二种结果类型，早于它的前端不认识。
各前端拿文档怎么办：

| 前端 | 文档去哪里 |
| --- | --- |
| 终端 | 盖在对话上的一页：渲染好的 Markdown，方向键滚动，Escape 关闭 |
| 编辑器 | 聊天旁边的 Markdown 预览 |
| 服务器 | `POST /commands/{name}` 回答里的 `markdown`，由客户端画 |

`ctx.commands` 没有 widget，也没有 `CommandUi`，所以文档是命令能开的最大的东西：需要自己的组件、要提问、或者
边跑边报的命令属于 `ctx.tui`，只在有终端的地方跑。

比如，跑在 `ctx.tui` 上的命令可以报进度并用 Markdown 回答：

```python
async def greet(self, context: CommandContext) -> CommandResult:
    if not context.argument:
        context.ui.error("Usage: /greet <name>")
        return CommandResult()
    context.ui.notice("Preparing a greeting…")
    return CommandResult(message=f"## Hello\n\nWelcome, {context.argument}.")
```

用这个方法替换上面的 `Greeter.greet`。UI 的 error/notice/result 显示在 transcript 里，不是发给模型的用户消息。
优先用命令的 UI 方法，而不是 `print()`。

### 让模型干活

命令可以用 `await context.require_host().prompt(text)` 跑一轮对话——就像读者自己敲的一样。这段文字作为读者的
消息回显、存进会话、边答边流式显示，并由同一行收尾；`@` 引用会被解析，命令在回答到达之前一直占着请求位。文字
为空、会话在另一个进程里打开、或者已经有请求在跑时，它返回 `False`、什么都不开；想让这种情况下也能用的命令声明
`when_busy="queue"`（见[请求运行期间](#请求运行期间)）。

指令比想展示的长时，命令把它们分开传：`prompt(brief, shown="/review")` 在对话里显示 `/review`
——现在显示，会话恢复后也显示——而把 brief 放进模型面前。brief 仍属于那一轮，之后的轮次模型还会读到它；只有
显示是短的。`/code-review` 就是这么写的。

一轮读取对话缓存的 prefix，默认还会为下一轮延长它——长对话便宜的原因就在这里。回答没人接着用的命令可以另说：
`prompt(text, cache="read")` 复用已经热的 prefix，但不把这次请求自己的话标成可缓存；`cache="off"` 完全
不发缓存指令。plain 命令用 `TurnCommandResult(prompt=…, cache="read")` 说同一件事。默认的
`"read_write"` 才是对话里的一轮该保留的。

命令因此可以是对模型的预置，而不是对模型的汇报：

```python
async def review(self, context: CommandContext) -> CommandResult:
    if not context.argument:
        context.ui.error("Usage: /review <what to look at>")
        return CommandResult()
    await context.require_host().prompt(f"Review this change, then list what you would alter. {context.argument}")
    return CommandResult()
```

### 提示第一个词

接受固定第一个词的命令（`/deploy staging`）可以把它列出来，命令加一个空格之后补全菜单就给出这些词：

```text
ctx.tui.register_command("deploy", "ship a build", self.deploy, subcommands=["staging", "prod"])
```

带说明的名字是 `zettcode.plugin_api.Subcommand("prod", "the live site")`；给一个函数，则每次菜单打开时问它，
用于依赖会话的词。它们只是提示：handler 仍然收到 `context.argument` 里打的一切，而且只有命令后面紧跟的那个词
会被提示。

### 请求运行期间

请求跑的时候敲进来的命令默认被挡掉，因为大多数命令会动那个请求脚下踩着的东西。注册时用 `when_busy` 说明
不是这样：

```text
ctx.tui.register_command("status", "show the build status", self.status, when_busy="now")
```

| `when_busy` | 请求期间敲它时 |
| --- | --- |
| `"refuse"`（默认） | 被挡掉，回一句 "busy" |
| `"queue"` | 先存着，请求一结束就跑，像 `/btw` |
| `"now"` | 立刻跑，和请求并排，请求不受影响 |

只有读数据、报状态，或者改一个请求需要时才看的设置的命令，才用 `"now"`。它跑的时候**不**独占忙状态，所以会改
transcript 或会话的命令会把脚下抽空。（`/model` 就不是这一类：在飞的请求在开始时已经拿到它的 provider，
再也不会发出去。）handler 想 await 多久都行：请求不等它，退出会取消它。

## 增加 `@` 资源

mention provider 增加一种输入框能提示、模型能解析的 `@` 引用：

```text
from zettcode.plugin_api import Mention, MentionProvider, Plugin, PluginContext


class Tickets(MentionProvider):
    kind = "ticket"                 # unique across the application

    def candidates(self, query: str) -> list[Mention]:
        return [Mention("@ABC-123", self.kind, "ABC-123", "the open ticket")]

    def expand(self, name: str) -> str | None:
        return f"Ticket {name}" if name.startswith("ABC-") else None


class TicketsPlugin(Plugin[PluginContext]):
    name = "ticket-resources"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_mention(Tickets())
```

`candidates(query)` 返回补全；`expand(name)` 返回模型看到的文字，不是这个 provider 的 token 时返回 `None`。
provider 可以覆盖 `rename(name)`，返回模型读到的、代替 `@name` 的词。`precedence` 给 provider 排序（小的先）；
两个 provider 给同一个名字时，排序在前的那个拥有它的补全、展开和改名。

## 在 provider 上提供模型 {#providers}

插件可以在自己认识的 host 上提供模型：插件一加载它们就出现在 `/model` 里，选中哪个就发那个 provider 指定的
token。配置文件里什么都不写。

```python
from zettcode.plugin_api import Plugin, PluginContext
from zettcode.plugin_api import ProvidedModel, Provider


class Acme(Plugin[PluginContext]):
    name = "acme"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_provider(
            Provider(
                "acme",  # unique across the application
                "Acme AI",  # what a list shows for the host
                api="chat",  # chat | responses | anthropic
                base_url="https://api.acme.example/v1",
                token_env="ACME_API_KEY",  # the runtime reads the token from it
                models=(
                    ProvidedModel("acme-large", display_model="Acme Large", context_window=200_000),
                    ProvidedModel("acme-small", context_window=64_000),
                ),
                note="model ids scale by the suffix",  # a lower-case phrase, no leading article or full stop
            )
        )
```

`ProvidedModel` 可以覆盖 host 的协议、地址和图片支持，并设置自己的上下文窗口、压缩比例、推理档位和温度。
`ctx.agent.register_model("acme", ...)` 和 `register_models(...)` 给已经注册的 provider 加模型。

`token_env` 是运行时使用这个模型时读的变量名；不收 key 的 host 可以不给。插件提供的模型由 `/model` 列出，
不由 `/config` 列出，后者只改文件。名字在整个应用里唯一：用文件已经在用的名字、或者前面插件已经用过的名字，
会被拒绝，插件按加载失败的插件一样被报出来。

### 从环境变量得到官方模型 {#official-models}

`zettcode-models` 就是为四个大多数读者本来就有 key 的厂商做这件事：OpenAI、Anthropic、DeepSeek、Z.AI。
设了 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`DEEPSEEK_API_KEY` 或 `ZAI_API_KEY`（`ZHIPUAI_API_KEY` 和
`ZHIPU_API_KEY` 是接受的别名）时，它用当前的官方模型注册那个 host——`GPT-6.1 Sol`、`Claude Opus 5.5`、
`DeepSeek V4.1 Flash` 或 `GLM-5.3`。启动时不调用任何端点：列表是静态的。模型在 `/model` 里显示为
`from the openai plugin`（或 `anthropic`、`deepseek`、`zai`）；token 来自环境，从不写进文件。

这个插件默认是开的：环境里有 key 就够了。配置里没有自己的模型时，ZettCode 用插件提供的第一个模型启动。
`[plugins] disable = ["models"]` 把它放下；host 或显示名已经被你自己的条目用掉的厂商会被跳过，而不是让插件
失败。厂商更新时，`zettcode/models/__init__.py` 里的表是唯一要改的地方。

## 提供配色 {#themes}

插件可以给 `/theme` 加配色。每一个都列在菜单里，移过去就预览，用 `/theme <name>` 选中。ZettCode 自己的配色
（`nord`、`dracula`、`gruvbox-dark`、`gruvbox-light` 等）也是内置插件用同样的方式提供的：

```text
from pathlib import Path

from zettcode.plugin_api import PluginContext, TuiPlugin


class Palettes(TuiPlugin):
    name = "acme-palettes"

    def activate(self, ctx: PluginContext) -> None:
        # A theme file shipped inside your package: same format as ~/.zettcode/themes/<name>.toml.
        ctx.tui.register_theme("acme", Path(__file__).parent / "acme.toml")
```

名字是一个词（字母、数字、`.`、`_`、`-`）。`dark` 和 `light` 属于 ZettCode。内置配色或前面的插件已经用过的
名字会被报出来，像任何加载不了的插件一样。读者自己放在 `~/.zettcode/themes/` 的同名文件优先于插件的。插件
也可以是读者启动时用的配色：`[ui] theme = "acme"` 能找到它。

## 提供宠物 {#pets}

宠物和配色是同一套做法，ZettCode 自带的十三个（`cat`、`dog`、`tiger`、`polarbear`、`snowbear`、`penguin`、
`scarfy`、`kangaroo`、`seagull`、`whale`、`chibi`、`slime`、`sprout`）也是内置插件用同一个调用提供的。宠物是
一套配色加各个情绪的像素图；图里每个字符是一种颜色，`.` 是透明，两行像素合成一行格子，所以图的行数是偶数，宠物
的每一帧一样大：

```text
from zettcode.plugin_api import Pet
from zettcode.plugin_api import PluginContext, TuiPlugin

PALETTE = {"G": "#84b795", "D": "#263d34", "H": "#e4b47c"}
ASLEEP = ("..GGGG..", ".GGGGGG.", "GGGGGGGG", "GDDGGDDG", "GGGHHGGG", ".GGGGGG.")
AWAKE = ("..GGGG..", ".GGGGGG.", "GGGGGGGG", "GGDGGDGG", "GGGHHGGG", ".GGGGGG.")


class Blobs(TuiPlugin):
    name = "acme-blobs"

    def activate(self, ctx: PluginContext) -> None:
        # The moods are "idle" (required: it is the pet asleep), "working" (while a request runs) and "glad"
        # (when it is patted); a pet that lacks the others stays as it is. A mood with several frames cycles.
        pet = Pet("blob", PALETTE, {"idle": (ASLEEP,), "working": (AWAKE, ASLEEP), "glad": (AWAKE,)})
        ctx.tui.register_pet("blob", pet, description="a quiet green blob")
```

宠物也可以是一个函数，第一次被要到时才建。名字是一个词（字母、数字、`.`、`_`、`-`）；内置宠物或前面的插件
已经用过的名字会被报出来。宠物出现在 `/pet` 面板里，也可以是读者启动时用的那只：`[ui] pet = "blob"`。

## 绘制一行 {#presenters}

对话里的每一行都由一个 *presenter* 画：它把一种 entry 变成带样式的若干行。ZettCode 自带的 presenter 由
内置插件以最低优先级注册，所以给同一批行注册 presenter 的插件会赢：

```text
from zettcode.plugin_api import EntryKind
from zettcode.plugin_api import Presenter
from zettcode.plugin_api import PluginContext, TuiPlugin
from zettcode.plugin_api import Span, Style, TextLine


class QuietNotice(Presenter):
    def handle(self, entry, next):
        return self if entry.kind is EntryKind.NOTICE else next(entry)

    def lines(self, entry, width, theme, frame):
        return self.text_lines(entry.text, width, Style(foreground=theme.muted))


class QuietNotices(TuiPlugin):
    name = "quiet-notices"

    def activate(self, ctx: PluginContext) -> None:
        ctx.tui.register_presenter(QuietNotice())
```

presenter 的 `handle(entry, next)` 就是它的全部主张：返回 `self` 表示画这一条，调用 `next(entry)` 交给别人。
注册表只管排这条链、把它跑起来，自己从不匹配任何行。永远返回 `self` 的 presenter 会吃掉问它的每一行，所以它的
位置决定一切：用比内置更低的 `priority`（`priority = -1`）注册一个兜底的。内置的 `ToolPresenter` 就是兜底。

内置 presenter 按 `entry.kind` 认领；工具 presenter 按工具自己的名字（`entry.tool`）认领，所以 `read` 和
`read_file` 共用一个读取 presenter，`glob` 和 `grep` 共用一个搜索 presenter。插件可以替换一个工具，而不动
另一个工具的行。

`lines` 收到 entry、可用的列数、配色和一个动画步，返回若干 `TextLine`；宽度是预算，所以要么折行要么裁掉。会动的
presenter 读 `frame`；不动的应该对任何 frame 给出同样的行。

多个 presenter 都能画同一批行时，`priority` 高的赢，一样高就给后注册的。内置的是默认，原因就在这里：优先级 0，
最先注册。想压过另一个插件的插件把自己的 presenter 类上的 `priority` 调高；只画一个家族从来不需要优先级。

## 给请求加一个工具

setup hook 可以给每个请求加工具。工具就是 `zett-agent` 的 `AgentTool`；插件只决定这一次运行看到哪些：

```python
from zett_agent.tools import tool
from zettcode.plugin_api import Plugin, PluginContext


@tool
async def word_count(text: str) -> str:
    """Count words in a string.

    Guidelines:
        - Use it when the reader asks for a word count.
    """
    return str(len(text.split()))


class Counter(Plugin[PluginContext]):
    name = "word-count"

    async def on_tool(self, context) -> None:
        context.register_tool(word_count)
```

`on_tool` 在请求建好之前跑；这里加的工具到下一个请求就没了，除非 hook 再加一次。观察一次调用用
`before_tool`，替换结果用 `on_tool_call` 中间件。

## 把整个扩展交给代理 {#extensions}

上面的 hook 方法跑在 ZettCode 为所有插件托管的那一个 extension 里。本身**就是** extension、或者包着
`zett-agent` 某个 extension 的插件，可以整个交出去：

```python
from zettcode.plugin_api import Plugin, PluginContext


class Audit(Plugin[PluginContext]):
    name = "audit"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.config.workspace.name != "scratch":
            ctx.agent.register_extension(AuditExtension())  # a zett_agent AgentExtension
```

agent 把它和其他的一起收下，按 extension 声明的 `priority` 排，相同的按插件加载顺序排。它的 `name` 必须唯一。
导入慢、或者需要 agent 启动时那个模型的 extension，最好用
`ctx.agent.register_extension_factory(name, build)` 注册：`build` 在 agent 建立时调用，可以返回 `None`
表示什么都不加。agent 跑的一切都是这样注册的：ZettCode 自己的编码工具、会话日志、shell 审批、压缩、`ask_user`
工具、项目指令、skills、MCP 和 todo 工具都是内置插件，所以 `[harness]` 下面那些开关只是决定它们的插件要不要
注册。

## 依赖别的插件 {#deps}

插件写明它需要哪些插件，ZettCode 先激活它们：

```python
from dataclasses import dataclass
from zettcode.plugin_api import Plugin, PluginContext


@dataclass
class Stats:
    calls: int = 0


class StatsProvider(Plugin[PluginContext]):
    name = "stats-provider"

    def activate(self, ctx: PluginContext) -> None:
        ctx.inject("stats", Stats())


class Statistics(Plugin[PluginContext]):
    name = "statistics"
    deps = ("stats-provider",)  # the provider's `name`, not its distribution

    def activate(self, ctx: PluginContext) -> None:
        stats = ctx.service("stats", Stats)
        stats.calls += 1
```

`deps` 里是插件的 **name**：每个插件声明的 `name`，没声明就是它发行包的 entry-point 名字。依赖缺失、被关掉、
加载失败、或者成环的插件会被放下并说明原因，需要它的插件也一样。彼此之间没有 `deps` 的插件按发现的顺序加载。
名字是插件的身份，所以两个插件不能共用一个。发行包或文件也不能占用别的插件已经有的 entry-point 名字。

插件用 `ctx.inject(name, service)` 给需要它的插件发布一个对象。运行时的几个页面 service 用类型化的读取入口：
`ctx.agent.session_store_service()`、`ctx.agent.usage_ledger_service()`、
`ctx.agent.context_report_service()`、`ctx.agent.context_page_service()`；别的一律用
`ctx.service(name, kind)`（或 `ctx.find`，没人提供时返回 `None`）读。对象是什么、怎么用，由涉及的插件自己约好。

## 事件发生时开始工作 {#triggers}

trigger 盯着一个事件（定时器、文件、socket），开始没有人提示过的工作。插件用 handler 注册一个，ZettCode 在
会话打开期间一直跑它：

```python
import asyncio
from zettcode.plugin_api import INBOX, Inbox, Plugin, PluginContext, Trigger, TriggerEvent, TriggerScope


class EveryMinute(Trigger):
    name = "every-minute"  # a lowercase letter or digit first, then lowercase letters/digits/._-, 1-64; it names the lock file
    scope = TriggerScope.MACHINE  # one on the whole machine

    async def run(self, fire):
        while True:
            await asyncio.sleep(60)
            await fire({"reason": "tick"})


class Heartbeat(Plugin[PluginContext]):
    name = "heartbeat"

    def activate(self, ctx: PluginContext) -> None:
        # Mypy rejects an abstract class as a `type[_T]`; the runtime lookup is a plain isinstance.
        queued = ctx.find(INBOX, Inbox)  # type: ignore[type-abstract]
        self._inbox = queued
        ctx.agent.register_trigger(EveryMinute(), self.on_tick)

    async def on_tick(self, event: TriggerEvent) -> None:
        if self._inbox is not None:
            self._inbox.deliver(f"tick: {event.payload['reason']}", mode="followup", origin="trigger")
```

`scope` 说跑几份：

- `TriggerScope.PROCESS`（默认）——每个进程一份。
- `TriggerScope.MACHINE`——整台机器一份，不管开了几个 ZettCode 窗口。持有会话库旁边那个文件锁
  （`~/.zettcode/triggers/<name>.lock`）的窗口跑它，其余的待命，它关掉后几秒内接手。持有者死掉时操作系统会
  释放锁。

抛异常的 trigger 被标成失败，不再重启；抛异常的 handler 只损失那一个事件。两个插件不能注册同一个 trigger
名字。

trigger 只是报告“发生了什么”。要让 agent 真的动手，把事件交给会话的队列：`INBOX` service，它的类型 `Inbox`
和条目类型 `Waiting` 都来自 `zettcode.plugin_api`。没人等着的工作用 `mode="followup"` 更礼貌。

会打开比一轮更久的东西——连接、后台线程——的插件在 `async def aclose(self)` 里释放它。运行时在会话关闭时调用
它，最新的插件先。

## 插件 API 参考

上面各节讲什么时候用哪个东西；这里给准确的名称、类型和默认值。

### `Plugin` 与 `TuiPlugin`

| 成员 | 含义 |
| --- | --- |
| `name` | `deps`、诊断和 `/plugins` 用的身份。空表示用 entry-point 名字 |
| `origin` | entry-point 名字，单个文件的插件就是文件名；由加载器设置。`[plugins] disable` 和开关文件匹配的就是它 |
| `description` | 一句话说明插件加了什么。`/plugins` 把它显示在开关旁边，SDK 和服务器也往下传；这个进程没加载的发行包用它的包摘要描述 |
| `deps` | 这个插件需要的其他插件 **name**；加载器先激活它们 |
| `priority` | 插件在宿主里的顺序，小的先。默认 `100` |
| `setting` | 只给程序用：开关一个编译进程序的插件的配置键 |
| `rank` | 只给程序用：一个角色组内的顺序；第三方插件留 `0` |
| `default_enabled()` | 类方法；返回 `False` 表示要 `[plugins] enable = ["name"]` 才开 |
| `cli_arguments()` | 类方法；返回启动和 `daemon spawn` 用的 `CliOption` 声明 |
| `activate(ctx)` | 同步；注册插件贡献的一切 |
| `aclose()` | 异步；释放长期资源，只调一次，按激活的逆序 |

`TuiPlugin` 是 `Plugin` 加四个可选的行方法：`render_header_left`、`render_header_right`、
`render_status_left`、`render_status_right`。每个收到 `ShellContext`，返回一个片段、`None`，或
`(segment, True)` 表示接管那一整边。

### Agent hook 组

插件只覆盖自己需要的阶段。除 `accept` 外都是异步的，默认什么都不做：

| 组 | 方法 |
| --- | --- |
| setup | `on_tool`、`on_state`、`on_message` |
| run | `before_run`、`after_run`、`on_success`、`on_error` |
| turn | `before_turn`、`after_turn` |
| model | `before_model`、`after_model` |
| tool | `before_tool`、`after_tool` |
| maintenance | `on_compact` |
| events | `accept(config, event) -> bool`、`on_event` |
| middleware | `on_model_request`、`on_tool_call` |

hook 的签名和可变 context 来自 `zett-agent`。本身是 extension 的插件可以用 `ctx.agent.register_extension()`
整个注册；`register_extension_factory(name, build)` 把导入和构建推迟到 agent 建好时。

### Context 方法

| 方法 | 契约 |
| --- | --- |
| `service(name, kind)` | 必需；缺失抛 `LookupError`，类型不对抛 `TypeError` |
| `find(name, kind)` | 可选；返回 `None` 而不抛 |
| `provide(name, value)` / `inject` | 给后面的插件发布；名字必须唯一，且不能是六个 `PLUGIN_*` 之一 |
| `register_provider(Provider)` | 给 `/config` 加一个模型 host |
| `register_extension(AgentExtension)` | 把整个 extension 交给 agent |
| `register_extension_factory(name, build)` | 以后再建；`build` 可以返回 `None` |
| `register_mention(MentionProvider)` | 增加一种 `@` 资源 |
| `register_trigger(Trigger, handler)` | 随会话启动一个长期 watcher |

### 命令

`ctx.commands.register(name, summary, handler, *, when_busy="refuse", subcommands=())` 加一个 plain
命令。handler 收到 `PlainCommandContext`。`subcommands` 是 `Subcommand` 记录（`name`、`description`、`needs_more`）；
标了 `needs_more` 的词由菜单补全、等后面的内容，而不是直接运行，`GET /commands` 同时带上名字和这个标记。

字段是：

| 字段 | 含义 |
| --- | --- |
| `argument` | 命令名后面原样、去掉首尾空白的文本 |
| `level` | `deny`、`ask`、`safe` 或 `full` |
| `host` | `PlainCommandHost \| None`；用它做 `compact`、`title`、`export`、`session_id`、`workspace`、`hub`；`locked` 表示另一个进程占着这个会话 |

`TextCommandResult(message="", notification="", markdown="")` 用文字、toast 或文档回答。
`TurnCommandResult(prompt, shown="", notification="", cache="")` 开一轮对话；`cache` 是 `"read"`、
`"read_write"` 或 `"off"`。

`ctx.tui.register_command(name, description, handler, *, when_busy="refuse", subcommands=())` 加一个
终端命令。它的 handler 收到 `CommandContext`，有 `argument`、`ui` 和 `host`；`context.require_host()` 就是
shell。`CommandResult` 的字段是 `message`、`notification`、`widget`、`relayout`、`intro` 和 `run`。

`when_busy` 是其中之一：

- `"refuse"`（默认）：请求在跑时挡掉。
- `"queue"`：存到那个请求结束。
- `"now"`：和请求并排跑；只用于读数据，或改请求需要时才读的设置。

### 屏幕贡献

没有终端时 `ctx.tui` 是 `None`。方法有：

| 方法 | 加了什么 |
| --- | --- |
| `register_command` | 一个带 `CommandUi` 和 `CommandHost` 的 `/command` |
| `register_header_left/right`、`register_status_left/right` | 一个片段（`str`、`TextLine` 或 `Row`）；`name` 为空时追加（`segment-N`），`render_*` 覆盖会替换内置片段；`override=True` 清空那一整边 |
| `register_turn_segment(name, summary, builder)` | 请求结束时那一行里的一项；名字以 `turn-` 开头 |
| `register_theme(name, theme, *, description="")` | 一个配色、文件或构建函数 |
| `register_pet(name, pet, *, description="")` | 一只宠物，或构建函数 |
| `register_presenter(presenter)` | 一个行 presenter；后注册的赢平局 |
| `register_focus_handler(handler)` | 窗口获得/失去焦点 |
| `register_turn_start_handler(handler)` | 一轮开始 |
| `register_turn_end_handler(handler)` | 一轮结束；被停掉或失败时 `completed` 为 false |

`register_turn_segment` 要求名字以 `turn-` 开头；builder 收到
`TurnContext(label, seconds, clock, usage, tools, failed_tools)`，`[statusline]` 里同名的开关会把它藏起来。
行方法收到 `ShellContext`：

| `ShellContext` 字段 | 类型 | 装什么 |
| --- | --- | --- |
| `config` | `ZettCodeConfig` | 解析后的配置 |
| `session` | `SessionState` | `id`、`title`、`name`、`workspace`、`handle` |
| `model` | `ModelState` | `config`、`name`、`effort`、`efforts` |
| `activity` | `ActivityState` | `busy`、`status`、`note`、`auto_shell`、`usage`、`tasks`、`frame`、`permission`、`self_compact` |
| `display` | `DisplayState` | `theme`、`width`、`height`、`screen`、`scrolled_up` |

presenter 实现 `handle(entry, next)` 和 `lines(entry, width, theme, frame)`。`handle` 返回 `self` 认领
这一条，或 `next(entry)` 交给别人。`priority` 决定平局；`gutter` 要标记列；`look` 说画出来的块依赖哪些
字段；`block` 缓存画好的行；`text_lines` 按宽度折行并缩进。entry 暴露 `id`、`kind`（`EntryKind`），以及
`text`、`tool`、`title`、`diff` 这类按类型不同的字段；`EntryStatus` 是
`running`/`completed`/`failed`/`skipped`。

### 配置和命令行

`ctx.settings.declare(**defaults)` 返回读者写的值，或者默认值。可以调用多次，每次加几个键；
`ctx.settings.get(key)` 读一个已声明的键，`ctx.settings.values()` 返回全部。只允许 `bool`、`int`、`float`
和 `str`。读者写 `[plugins.<name>]`；类型不对在激活时被拒绝并指出键名。

`cli_arguments()` 返回 `CliOption(flags, dest, help="", default=None, action="store", choices=None,
metavar=None)`。解析后的值是 `ctx.service(PLUGIN_CLI, dict).get(origin, {}).get(dest)`。参数放在子命令
之前：`zettcode --journal-limit 5 resume ID`。`daemon spawn` 接受同样的参数，并私下传给子进程。

### 加载、顺序和失败

- `deps` 写的是插件，不是发行包；缺失、被关、失败或成环的依赖会让依赖它的插件被放下，并说明原因。
- `default_enabled()` 为 false 的插件，只有 `[plugins] enable` 点了它、程序需要它、或者被保留的插件需要它时
  才加载。
- 重复的身份、被别的插件占用的命令名、service 名、extension 名、配色名和宠物名会让后一个插件失败，而不是
  整个应用。
- 没有屏幕的进程里 `ctx.tui is None`；插件必须挡住只在屏幕上做的事。
- `Plugins.failures` 是 `origin: why`；`Plugins.taken` 记录输给前面插件的名字。失败的插件什么都不提供。
- `aclose` 最新的先跑。失败被记进日志，不阻止其他插件。

## 测试插件

插件就是普通 Python。用测试辅助建一个 context，自己调 `activate`；不需要终端：

```python
from zettcode.app.plugins.loader import terminal_context
from zettcode.config import ModelConfig, ZettCodeConfig
from zettcode.plugin_api import PLUGIN_CLI


def activate_for_test(tmp_path):
    config = ZettCodeConfig(
        workspace=tmp_path,
        store=tmp_path / "sessions",
        models=(ModelConfig(model="example", token="test"),),
    )
    ctx = terminal_context(config, {PLUGIN_CLI: {"journal": {"limit": "5"}}}, name="journal")
    Journal().activate(ctx)
    return ctx
```

插件没有屏幕那一半时，用 `PluginContext(config, services)` 和 `ctx.commands`。屏幕测试需要装了程序
（`zettcode.app` 不是 `zettcode-plugin-api` 的依赖）；没有屏幕那一半的插件只需要 `PluginContext`。测命令
handler 就构造 `PlainCommandContext(argument="...")` 或 `CommandContext(argument="...", ui=... )`；测屏幕
贡献就通过 `ctx.tui` 和应用自己用的那套 context 辅助。测试都放在临时目录里：插件永远不许写读者的 home 或
checkout。

## 出问题的时候

导入或激活不了的插件会被报出来，不是致命错误。失败落在哪里取决于什么失败了：

| 失败 | 结果 |
| --- | --- |
| 导入、`activate`、重复身份，或名字冲突（别的插件占用的命令、配色、宠物、provider、mention、extension、trigger、service） | 整个插件被丢掉，它的注册一条都不留；`origin: why` 出现在 transcript 和 `Plugins.failures` 里 |
| 依赖缺失、被关、失败或成环 | 依赖它的插件也被丢掉，带一句 `needs plugin 'x' …` |
| 命令抛 `ValueError` 或 `ZettCodeError` | shell 把这句话当命令自己的错误显示 |
| 命令抛其他异常 | 一行 `/<name>: <reason>`，traceback 进日志 |
| focus / turn-start / turn-end handler 抛异常 | 一行 `a plugin hook failed: …`，只报一次；之后的事件它照样被调用。agent 那边的 hook 抛异常会往上走，让请求失败 |
| trigger 抛异常 | trigger 被标成失败，不再重启；handler 抛异常损失一个事件 |
| presenter 在画的时候抛异常 | 它不像 hook 那样被隔离：每一帧都返回同样的行，不要抛 |

失败的插件什么都不提供。`ctx.find` 返回 `None`；`ctx.service` 抛 `LookupError`。同样的事实也在 shell 的
`plugin: …` 一行、`/plugins`，以及 SDK 客户端的 `client.plugins.failures` 里；`plugin list` 显示的是安装和
开关状态，不是失败原因。结构化日志是 `~/.zettcode/log/` 下的 JSON 行（默认 `terminal.jsonl`）；
`ZETTCODE_LOG_LEVEL=debug` 给更多。`Plugins.taken` 记录输给前面插件的名字。两个插件不能共用一个身份，
先来的保留它。命令名同样是共用的。被 shell 自己的四个命令（`/config`、`/theme`、`/pet`、`/statusline`）或
agent 的命令（`/new`、`/compact`、`/export`）占用的名字会被悄悄丢掉：插件加载了，命令不列出、也跑不了，而且
不报失败；装完看一眼 `/help`。被别的插件——包括 `/model`、`/resume` 这样的程序插件——占用的名字会让插件加载
失败，报 "command … is already registered by another plugin"，并出现在 `Plugins.failures` 里。

## 下一步

- [插件](/zh/guide/plugins)：安装、关掉，以及配置放在哪。
- [命令](/zh/guide/commands)：插件不能占用的那些内置命令。
- [认识界面](/zh/guide/interface)：插件画进去的行、面板和状态行。



