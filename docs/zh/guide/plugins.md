# 插件

插件是一个 Python 包，用来给 ZettCode 加东西：一个命令、一个工具、屏幕上的一行，或者对模型
收到内容的调整。装上这个发行包就是“启用”，不需要改什么注册表。

## 这一页怎么读

先读前三节建立模型；具体要做什么时，再按下面的表跳转：

| 你想…… | 读 |
| --- | --- |
| 知道从安装到插件运行之间发生了什么 | [插件如何加载](#插件如何加载) |
| 看一个完整的、能运行的插件 | [一个完整插件](#一个完整插件) |
| 知道 `ctx` 和 service 给了什么 | [上下文和它提供的 service](#上下文和它提供的-service) |
| 加命令、行、配色、宠物、provider、工具或 trigger | 下面的小节和 [插件 API 参考](#插件-api-参考) |
| 声明配置或命令行参数 | [读配置](#读配置)、[命令行参数](#命令行参数) |
| 理解失败、顺序和依赖 | [依赖别的插件](#deps)、[出问题的时候](#出问题的时候) |

## 插件如何加载

单位是一个带 entry point 的 Python 发行包——或者 `~/.zettcode/plugins` 里的单个 `.py` 文件：

```toml
[project.entry-points."zettcode.plugin"]
journal = "my_package.plugin:Journal"
```

左边的 `journal` 是插件的 **origin**：`[plugins] disable` 用它，`PLUGIN_CLI` 的值也按它分组。
右边是 `Plugin` 子类。它的 `name` 是身份，默认等于 entry-point 名字。配置在
`[plugins.<name>]`，`deps` 也用 `name`；`[plugins] disable` 和 `/plugins` 匹配的是 **origin**
（entry-point 名字），即使插件声明了不同的 `name`。包改名时这个区别很重要。
加载器只做一次下面这些事：

1. 发现已安装的 entry point，以及 `~/.zettcode/plugins` 里单独的文件。
2. 实例化每个类。构造函数应当很轻，不读 workspace，也不调用模型。
3. 为这个插件建立 `PluginContext`，调用 `activate(ctx)`。它故意是同步的：只能注册贡献，
   不能 await 或启动工作，所以界面和 agent 开始构建之前，所有注册都已经完成。
4. 检查命令、扩展、service、主题、宠物、trigger、provider 的名字是否重复。
5. 合并到应用中。`Plugin` 的 hook 跑在一个宿主扩展里；用
   `register_extension()` 注册的完整扩展跑在它旁边。
6. 关闭时调用一次 `await plugin.aclose()`，最后激活的最先调用。

加载器是宽容的：导入或激活失败的插件会显示为 `plugin: …`，应用继续运行。依赖和顺序见
[依赖别的插件](#deps)。

插件没有“终端插件”和“服务端插件”之分。它在所有进程里拿到同一个 `PluginContext`；
只是没有屏幕时 `ctx.tui` 是 `None`。把可移植的部分写在 `ctx.agent`、`ctx.commands` 和
service 上，屏幕相关的工作先判断：

```text
if ctx.tui is None:
    return
```

加载器不会按前端过滤插件：插件在加载它的每个进程里都会激活。所以屏幕相关的代码必须放在这个判断之后；
否则激活失败，插件已经注册的其他内容也会被丢弃。

## 一个完整插件

这个插件加一个 `/journal` 普通命令，声明一个配置项和一个启动参数，并从应用提供的 service
读值。文件保存为 `plugin.py`，加上上面的 entry point，安装后重启即可。

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
        return TextCommandResult(
            message=f"## {self.prefix}\n\nLast {self.limit} entries about: {context.argument}"
        )
```

运行 `zettcode --journal-limit 5`，然后在输入框输入 `/journal tests`。同一个插件也可以
在 `zettcode daemon spawn --journal-limit 5` 启动的 daemon 里使用。

## 上下文和它提供的 service

`PluginContext` 是插件通往应用的唯一通道。它的属性是 service 的短别名，两种写法都支持：

```text
ctx.config is ctx.service(PLUGIN_CONFIG, ZettCodeConfig)
ctx.agent is ctx.service(PLUGIN_AGENT, AgentGroups)
ctx.commands is ctx.service(PLUGIN_COMMANDS, CommandGroups)
ctx.tui is ctx.find(PLUGIN_TUI, TuiGroup)       # 没有屏幕时为 None
```

### 上下文给了什么

| 成员 | 类型 | 用途 |
| --- | --- | --- |
| `ctx.config` | `ZettCodeConfig` | 解析后的配置，只读 |
| `ctx.workspace` | `Path` | 这个会话工作的目录 |
| `ctx.settings` | `PluginSettings` | 声明和读取 `[plugins.<name>]` |
| `ctx.agent` | `AgentGroups` | 扩展、provider、mention、trigger、service |
| `ctx.commands` | `CommandGroups` | 所有前端都能跑的普通命令 |
| `ctx.tui` | `TuiGroup \| None` | 只属于终端的命令、行、配色、宠物、presenter |
| `ctx.service(name, kind)` | `T` | 必需 service；没有时抛 `LookupError` |
| `ctx.find(name, kind)` | `T \| None` | 可选 service；没有时返回 `None` |
| `ctx.provide(name, value)` | `object` | 给后面的插件发布 service |

`service`/`find` 会检查 `kind`。类型不对是 `TypeError`，不会静默变成 `None`。
`provide` 拒绝本插件已提供的名字、六个上下文自有的名字、空白名字；名字被别的插件占用时
加载器会拒绝。

### 应用提供的 service

名字都是 `zettcode.plugin_api` 导出的常量。**可用性**很重要：屏幕和消息相关的 service
不是每个进程都有。

| service | 类型 | 何时存在 | 用途 |
| --- | --- | --- | --- |
| `PLUGIN_AGENT` | `AgentGroups` | 总是 | 注册扩展、provider、mention、trigger |
| `PLUGIN_COMMANDS` | `CommandGroups` | 总是 | 普通 `/命令` |
| `PLUGIN_TUI` | `TuiGroup` | 只有终端 | 屏幕命令、行、主题、宠物、presenter |
| `PLUGIN_CONFIG` | `ZettCodeConfig` | 总是 | 解析后的配置 |
| `PLUGIN_WORKSPACE` | `Path` | 总是 | 会话工作目录 |
| `PLUGIN_SETTINGS` | `PluginSettings` | 总是 | 本插件的配置表 |
| `LLM` | `ModelAccess` | engine | `.models` 和 `.ask(...)` side question |
| `PLUGIN_CLI` | `dict[str, dict[str, object]]` | engine | 解析后的插件命令行参数 |
| `HOST_LINK` | `HostLink` | 只有终端 | TUI 命令晚绑定的 `CommandHost` |
| `INBOX` | `Inbox` | messaging 插件加载时 | 把事件交给会话 |
| `SESSION_STORE` | `SessionStoreService` | engine | 列出已存储会话 |
| `USAGE_LEDGER` | `UsageLedgerService` | engine | 读取 token 用量 |
| `CONTEXT_REPORT` | `ContextReportService` | engine | 某个会话的上下文报告 |
| `CONTEXT_PAGE` | `ContextPageService` | engine | `/context` 页面的数据和写入 |
| `MODELS` | 以 `ModelConfig` 为键的 provider 适配器 | engine | 已经构建的模型 |
| `CAPABILITIES` | `ModelCapabilities` | built-in capabilities 插件 | 按模型过滤工具 |
| `POLICY` | `ShellPolicy` | engine | 当前 shell 权限策略 |
| `PERSISTENCE` | `SessionStore` | engine | 存储实现 |
| `COMPACTION_COUNTER` | `CompactionCounter` | engine | token 计数 |
| `SELECTED_MODEL` | `ModelConfig` | 配置了模型时 | 下一次运行使用的模型 |
| `APPROVAL`、`USAGE`、`CONTEXT`、`SIDES`、`COMPACTION`、`TODOS` | engine 契约 | 内置功能插件 | 功能 service |

`HARNESS` 和 `DELIVERY` 是 engine 内部 service，不属于插件契约，也没有类型化 reader。
这张表里的类型由 `zettcode.plugin_api` 导出（契约定义在 `zettcode.engine`）。

可能不存在的 service 用 `ctx.find`，尤其是 `INBOX`、`HOST_LINK`、`SELECTED_MODEL` 和页面
service。只有当插件 README 说明它依赖的插件会提供时，才用 `ctx.service`；缺少必需 service
会得到明确的 `LookupError`，不是静默默认值。

### 模型访问

`LLM` 给需要模型回答、但不想开启一轮对话的插件：

```text
from zettcode.plugin_api import LLM, ModelAccess

access = ctx.service(LLM, ModelAccess)
for model in access.models:
    ...
answer = await access.ask("Summarise the failing test", origin="journal")
```

这是 side question：问题和答案不进入对话，恢复会话时也不会恢复插件问的内容。完整签名是
`ask(question, *, origin="plugin", cache="read", timeout=None)`。`LLM.ask` 在前端绑定对话之前会抛
`RuntimeError`；它不能在 `activate` 里用，只能在能跑请求之后用。插件从当前运行上下文拿当前模型；`ModelAccess`
不会改变读者选择的模型。

## 安装一个插件

插件在 `zettcode.plugin` 这个 entry point 组下发布一个类；加载器也接受零参数工厂或实例，通常写类：

```toml
[project]
name = "my-package"
dependencies = ["zettcode-plugin-api>=0.4,<0.5"]

[project.entry-points."zettcode.plugin"]
greeter = "my_package:Greeter"
```

插件只需要依赖 `zettcode-plugin-api` 这一个包，运行所需的一切都在里面。如果要用 `Client`、`ModelInfo`、`Usage`
这类 SDK 类型做注解，请从各自模块导入：`Client` 来自 `zettcode.sdk`，`ModelInfo` 来自 `zettcode.sdk.types`，
`Usage` 两处都有。这些模块不会随 `zettcode-plugin-api` 单独安装。只安装你的包做 CI/类型检查时，加 extra：
`dependencies = ["zettcode-plugin-api[types]>=0.4,<0.5"]`，它会拉入 `zettcode-sdk`。不加的话，除非设置
`ignore_missing_imports`，mypy 会找不到这些 import；运行时没有差别。配色或 presenter 注解里的 `Theme`
来自 `zettcode.tui`，它随 `zettcode-plugin-api` 安装。

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

把插件安装到 **ZettCode 使用的同一个 Python 环境**，再重启，命令就会出现在 `/` 菜单里，
排在内置命令之后。安装到另一个虚拟环境，不会让 `uv tool` 安装的 ZettCode 自动发现它。

也可以让 ZettCode 自己安装：

```sh
zettcode plugin install /path/to/greeter                  # 本地项目、wheel 或 sdist
zettcode plugin install ./greeter.py                      # 单个 Python 文件
zettcode plugin install owner/repo                        # GitHub 仓库
zettcode plugin install owner/repo@v1.2.0                 # tag、分支或提交
zettcode plugin install https://github.com/owner/repo/tree/main/plugins/greeter
```

命令会装进 `zettcode` 正在运行的那个环境——有 pip 就用 pip，没有就用 uv 的 pip（`uv tool` 安装的环境就是如此）。
插件在仓库的子目录里时，用上面的 `tree` 地址。重启 ZettCode，插件就在 `/` 菜单里了。

单个 `.py` 文件不会装进 site-packages，而是复制到 `~/.zettcode/plugins`：下次启动时，文件里每个继承
`Plugin` 或 `TuiPlugin` 的类都会被加载——一个文件可以有多个类，但每个类要有不同的 `name`（否则都回退到文件 stem，第二个会被拒绝）。文件必须是一个模块（不能用相对导入），
而且不声明依赖——它需要的依赖按插件自己的说明安装。覆盖一个内容不同的文件会被拒绝，除非加 `--force`
（提示会给出目标路径，并说明先删除或加 `--force`）。

```sh
zettcode plugin list                  # 每个插件的名字、来源、位置和开关
zettcode plugin list --json           # 同样的内容，给程序读
zettcode plugin uninstall greeter     # 文件名（去掉 .py）、发行包名，或 entry point 名
zettcode plugin disable greeter       # 下次启动不加载
zettcode plugin enable greeter        # 重新加载
```

`list` 会列出程序自带的 agent 插件（位置是 `compiled in`）、装在旁边的发行包（entry point 名、发行包名和 site-packages 目录），
以及 `~/.zettcode/plugins` 里的单文件插件（文件路径），并说明下次启动是否加载、由哪个开关决定。编译进程序的插件
`ENABLED` 是 `-`，它的设置在旁边的 `SWITCH` 里。`uninstall` 会从 `~/.zettcode/plugins` 删掉文件，
或者卸载名字对应的发行包；名字可以是发行包名、`/plugins` 里显示的 entry point 名，或者文件名（去掉 `.py`）。
`enable` 和 `disable` 写的就是 `/plugins` 面板用的同一份 `[plugins] disable` 列表，但只限这条命令接受的插件；面板还会列出程序自己的可选终端部分，这条命令不管它们。编译进程序的插件由配置里的设置控制，面板会改它，这条命令不会。
程序自己的终端部分（`themes`、`pets`、`context`、`usage`）由 `/plugins` 页面列出，不在这个命令里。

这个命令以前叫 `zettcode plugins`：为旧名字写的脚本仍然可用，不过 `zettcode --help` 里只列 `plugin`。

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

## 增加 `@` 资源

Mention provider 增加一种 `@` 引用，补全菜单能提供，模型能解析：

```text
from zettcode.plugin_api import Mention, MentionProvider, Plugin, PluginContext


class Tickets(MentionProvider):
    kind = "ticket"                 # 整个应用唯一

    def candidates(self, query: str) -> list[Mention]:
        return [Mention("@ABC-123", self.kind, "ABC-123", "the open ticket")]

    def expand(self, name: str) -> str | None:
        return f"Ticket {name}" if name.startswith("ABC-") else None


class TicketsPlugin(Plugin[PluginContext]):
    name = "ticket-resources"

    def activate(self, ctx: PluginContext) -> None:
        ctx.agent.register_mention(Tickets())
```

`candidates(query)` 返回补全项；`expand(name)` 返回模型看到的文本，token 不属于这个 provider 时返回 `None`。
可以覆盖 `rename(name)`，返回模型看到的替代文本；`precedence` 决定 provider 的顺序（小的先），两个 provider
提供同一个名字时，排在前面的那个拥有它的补全、展开和重命名。

## 插件能参与什么

`Plugin` 组合了两组钩子（代理那一组在 `zettcode.engine.plugins`，屏幕那一组由 `TuiPlugin` 加上；两组都由
`zettcode.plugin_api` 重新导出，插件只需要从它导入），插件只覆盖自己关心的阶段：

- **代理的工作** —— 和 `zett-agent` 扩展同一套生命周期：setup、run、turn、model、tool、
  compaction，以及外部事件。插件可以注册工具、改写发给模型的消息、转换工具结果，或者观察一次
  运行的结束。
- **屏幕** —— 头部和状态行各自分成左右两侧，每一侧都由注册过的片段共同画出来。
- **窗口与轮次** —— 终端启动时会请求焦点报告，所以插件能知道读者什么时候离开、什么时候回来；对话的一轮
  开始和结束也都能收到。想在人不在时汇总、提醒，或者等读者停下来再做事的插件，就建立在这些钩子上：

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
        """终端窗口获得（``True``）或失去（``False``）焦点。"""

    def started(self) -> None:
        """对话的一轮开始了，在请求发出之前。"""

    def ended(self, completed: bool) -> None:
        """对话的一轮结束了；被停止或失败的一轮里 ``completed`` 是 false。"""
```

两者都不是行，也不能消费事件：只是被告知，怎么处理是插件自己的事。钩子被调用时也不是动手的好时机：它运行在
刚结束的那次请求里面，shell 还没空出来，所以要开新一轮的工作——比如 `HOST_LINK` 的 host `prompt(...)`，或 `INBOX.deliver(..., mode="followup")`——应该排到之后去做，
而不是在处理器里直接做。

什么算「一轮」：读者发的一次请求，或另一个会话发来、由本会话回答的那次请求。执行命令本身不算一轮，但命令用
`host.prompt` 开起来的那一轮算；侧问和继续的请求也不算。不支持焦点报告（``DECSET 1004``）的终端则永远不会
调用第一个钩子，其它行为不变。

```python
from zettcode.plugin_api import ShellContext, TuiPlugin


class WorkspaceLabel(TuiPlugin):
    """用模型和工作区标签替换头部右侧片段。"""

    name = "workspace-label"

    def render_header_right(self, context: ShellContext) -> str:
        return f"{context.model.name} · {context.session.workspace.name}"
```

返回 `str`、带样式的 `TextLine`、`Row`，或者 `None`（什么都不画）。`Row` 由具名部分组成（`row.add(name, summary, text)`），`/statusline` 开关的是这些部分；`lead`/`trail` 是它们两边的固定文本。没有自带样式的片段会继承这一行的
灰色样式，所以默认看起来是融进去的，想上色再上色。用已存在的名字注册会**原地替换**那个片段；
新名字追加在该侧已有的片段之后。返回 `(value, True)` 表示独占该侧，这是在不知道内置名字的
情况下接管整侧的做法。

还没配置模型时，`context.model.name` 是空串，`context.model.efforts` 是空元组，
`context.model.config`（那一项本身）是 `None`。读这一项的片段应该说自己没有模型，而不是假定它一定在。

## 默认关闭

插件自己决定读者没要求时是否加载。重写 `default_enabled` 并返回 `False`，加载器就会跳过它，直到
`[plugins] enable` 列出它的 entry-point 名称：

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

默认值是 `True`，所以不写这个方法的插件和以前一样加载。

## 命令行参数

插件通过覆盖类方法 `cli_arguments()` 声明启动参数：

```text
CliOption(flags=("--journal-limit",), dest="limit", help="...", default="3", metavar="N")
```

加载器在读配置之前从插件类读取声明，所以还没选 workspace 时这些参数就能用。解析后的值是
`PLUGIN_CLI` service，按 entry-point 名字分组：

```text
limit = ctx.service(PLUGIN_CLI, dict).get("journal", {}).get("limit", "3")
```

参数是全局的，要放在子命令之前：`zettcode --journal-limit 5 resume ID`。
`zettcode daemon spawn` 接受同样的参数，并私下把值传给子进程。值必须 JSON 安全（`str`、数字、bool、列表、
字典或 `None`），因为 daemon 通过 JSON 传递。声明有重名 flag 或非 JSON 默认值时，只跳过该选项并打印一行，
不会 traceback。

只有 **entry-point** 插件能声明这些参数。声明在构建缓存时从插件类读取；`~/.zettcode/plugins` 里单个
`.py` 文件没有 entry point，所以它的 `cli_arguments()` 不会被读取。刷新缓存会导入所有已安装插件的类，
包括被禁用的插件——让那个模块保持轻量。`zettcode --help` 故意跳过插件发现，所以不会列出这些 flag；
`zettcode daemon spawn --help` 会。`~/.zettcode/.ztrc` 只为会话启动预置它们，不会作用于 `daemon spawn`。

为了让交互启动快，parser 从 `~/.zettcode/plugin-cli.json` 读这些声明，而不是导入每个插件。缓存缺失或过期时，
daemon 线程才导入插件类刷新；刚安装或修改插件的第一次启动还没有新 flag，下一次启动才有。读不到缓存时不等待，直接继续；`prompt`、`doctor`、`--dry-run` 和 `daemon spawn` 结束得太快，会同步刷新。
如果 `.ztrc` 在缓存存在前写了插件 flag，这一次启动会同步刷新声明并应用，不会丢掉这个预置项。

## 读配置

有配置项的插件自己声明这些项，以及读者没写时它们取什么值。配置文件不可能知道装了哪些插件，所以它把每个
插件自己的表原样保留（`[plugins.<名字>]`），键的含义由插件决定：

```python
def activate(self, ctx: PluginContext) -> None:
    given = ctx.settings.declare(after_seconds=180, quiet=False)
    self.after_seconds = int(given["after_seconds"])
    self.quiet = bool(given["quiet"])
```

读者的值优先；类型和默认值不一致时，插件激活时就会报错，并指出是哪张表、哪个键；读一个插件没声明过的键
是错误，而不是悄悄给个默认值。没装某个插件时，它的 `[plugins.recap]` 表放着也无害；以后才装的插件不需要
改配置代码。

```toml
[plugins.recap]
after_seconds = 240
quiet = true
```

`declare` 可以调用多次，继续声明更多键：这些默认值既是校验读者那张表的依据，也是读者没写时的取值。

插件自己的设置表和 `[plugins]` 的开关写在同一个文件里，互不妨碍。`[plugins.recap]` 生效不需要你另写一行
`[plugins]`；`/plugins` 和 `zettcode plugin disable` 要写 `disable = [...]` 时，如果文件里只有
`[plugins.<名字>]` 这类表，它们会把 `[plugins]` 表头补在文件末尾（你的那些表下面），你写的内容原样不动。如果文件用别的
方式声明了 `plugins`（内联表、`plugins.disable = []` 这样的点号键、`[[plugins.<名字>]]`，或一张 `[plugins.disable]`
表），就不会去改它：命令会直接说明，留给你手工处理。

## 两套命令系统

答案是文字或文档时用 `ctx.commands`；它在所有前端都能跑。需要终端页面、shell、实时行或
`CommandHost` 操作时用 `ctx.tui`。

| | `ctx.commands` | `ctx.tui` |
| --- | --- | --- |
| handler 上下文 | `PlainCommandContext` | `CommandContext` |
| 返回值 | `TextCommandResult` 或 `TurnCommandResult` | `CommandResult` |
| 没有屏幕时 | 能跑 | 不能 |
| handler | 同步或异步 | 异步 |
| 名字 | 必须带前导 `/` | 前导 `/` 可选 |
| shell 能力 | `PlainCommandHost`（`compact`、`title`、`export`） | 完整 `CommandHost` |
| 页面/widget | 没有 | `CommandResult.widget` |

普通命令的 `host` 可能是 `None`：终端适配器传 `None`，服务端传真实的 `PlainCommandHost`。
用之前先判断。

`CommandHost` 是终端命令的 shell API：`client`、`agent`、`transcript`、`commands`、
`prompt(text, *, shown=None, cache=None)`、`close_page`、`request_layout`、
`wait_for_frame`、`offer`、`quit`、`select_session`、`resume_session`、
`fork_session`、`rename_session`、`run_continue`、`run_side_question`、
`change_model`、`select_model`、`change_effort`、`change_permission`。
`CommandContext.require_host()` 返回它或抛 `RuntimeError`。`CommandAgent` 提供
`session_id`、`workspace`、`require_session()`；`CommandTranscript` 提供 `notice`、
`error`、`markdown`、`start_compaction`、`complete_compaction`、`clear`。

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

要等模型、或任何要好几秒的命令，不要把等待留在处理器里：用 `intro` 说明正在做什么，把剩下的
交给 `run`。shell 会把 `intro` 放进读者正在看的固定行，等 `run` 完成后再收尾；Ctrl-C、Escape、读者发下一条消息、以及在空输入框上按回车，
都会停掉它，那一行会写成 `stopped`。

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
        # 这时 shell 还没有;命令运行时才通过它去拿。
        self.link = ctx.find(HOST_LINK, HostLink)
        if ctx.tui is not None:
            ctx.tui.register_command("recap", "总结这个会话", self.recap)

    async def recap(self, context: CommandContext) -> CommandResult:
        return CommandResult(intro="Recap \u2026 writing", run=self.really_recap())

    async def really_recap(self) -> CommandResult:
        if self.link is None or self.link.host is None:
            raise ValueError("shell 还没准备好")
        host = self.link.host
        answer = await host.client.session.ask("简短地总结这个会话进行到哪了。", cache="read", origin="recap")
        return CommandResult(message=f"> {answer}")
```

`ask` 是旁问：这一问一答不会进对话历史，shell 也不会把它画出来 —— 因为它没有为它开一轮，这跟参数无关。
`origin="recap"` 管的是另一半：它说明是谁问的，而恢复会话时只有读者自己问的那些会被恢复。沿用默认 `origin="reader"`
的命令，自己的问题就会在重开之后回到屏幕上。答案只出现在命令自己放的地方 —— 这里是一段引用。`/btw` 是同一种问题，
origin 是读者，所以 shell 会把那一次画出来，也会在恢复时把它恢复回来。

插件命令排在最后，也不能顶掉内置命令，所以 `/model`、`/resume` 等等永远和
[命令](/zh/guide/commands)里写的一致。

### 返回一个文档

注册在 `ctx.commands` 上的命令，返回的是 `TextCommandResult` 或 `TurnCommandResult`，都不依赖终端。
`TextCommandResult` 有三个字段，都可以不填：`message` 是对话里的一行，`notification` 是一个 toast，
`markdown` 是一份由前端单独展示的文档。适合用 `markdown` 的是要读而不是要划过去的内容——一份报告、
一次评审、插件自己数据拼出来的一页；`message` 留空，或者只放一句说明：

```python
from zettcode.plugin_api import PlainCommandContext, TextCommandResult


def notes(context: PlainCommandContext) -> TextCommandResult:
    """返回一份文档，由前端在自己的视图里展示。"""
    return TextCommandResult(markdown="# 笔记\n\n- 构建是绿的\n- 还有两件事要读")
```

在 `activate` 里用 `ctx.commands.register("/notes", "show the notes", notes)` 注册它——普通命令需要前导斜杠。
它的上下文有 `argument`、`level`（`deny`/`ask`/`safe`/`full`）和可选的 `host`，后者有 `compact()`、`title()`、
`export()`。终端适配器传 `host=None`；需要 host 的普通命令必须处理这种情况，并说明哪个前端做不了。
之所以加字段而不是加第三种结果类型，是为了不破坏已经写好的命令：不认识这个字段的前端照样执行命令，
照样显示 `message`。各端的处理：

| 前端 | 文档展示在哪里 |
| --- | --- |
| 终端 | 盖在对话之上的一页：渲染后的 Markdown，方向键滚动，Escape 关闭。 |
| 编辑器 | 聊天旁边的 Markdown 预览。 |
| 服务端 | `POST /commands/{name}` 返回里的 `markdown`，由客户端负责渲染。 |

`ctx.commands` 没有 widget，也没有 `CommandUi`，所以文档是一个命令最多能打开的东西；需要自己的
widget、要向人提问、或者边跑边汇报的命令，属于 `ctx.tui`，只在有终端的地方运行。

例如，一个跑在 `ctx.tui` 上的命令可以汇报进度，并把结果作为 Markdown 的 `message` 返回：

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

一轮对话会读取上下文的缓存前缀，默认还会把它延长给下一轮用 —— 长对话能便宜就是靠这个。如果命令的回答不会
有人接着用，可以换个说法：`prompt(text, cache="read")` 复用已经热起来的前缀，但不把这次的文字标进缓存；
`cache="off"` 则完全不带缓存指令。plain 命令用 `TurnCommandResult(prompt=…, cache="read")` 表达同样的事，
运行它的每个前端都会照做。默认的 `"read_write"` 才是对话里一轮该用的。

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

带说明的词用 `zettcode.plugin_api.Subcommand("prod", "the live site")`；传一个返回列表的函数则每次打开菜单时都会被调用，
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
from zettcode.plugin_api import Plugin, PluginContext
from zettcode.plugin_api import Provider


class Acme(Plugin[PluginContext]):
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
ZettCode 自带的配色（`nord`、`dracula`、`gruvbox-dark`、`gruvbox-light` 等）也是由一个内置插件用同样的方式提供的，所以下面
就是全部机制：

```text
from pathlib import Path

from zettcode.plugin_api import PluginContext, TuiPlugin


class Palettes(TuiPlugin):
    name = "acme-palettes"

    def activate(self, ctx: PluginContext) -> None:
        # 包里自带的主题文件：格式与 ~/.zettcode/themes/<名字>.toml 相同。
        ctx.tui.register_theme("acme", Path(__file__).parent / "acme.toml")
```

名字是一个词（字母、数字、`.`、`_`、`-`）。`dark` 和 `light` 属于 ZettCode。名字如果已被内置配色或更早
加载的插件占用，就会被跳过并像其他加载失败的插件一样报告。读者放在 `~/.zettcode/themes/` 里的同名文件
优先于插件提供的，所以读者总能改动别人给的配色。插件提供的配色也可以作为启动配色：
`[ui] theme = "acme"` 能找到它。

## 提供宠物 {#pets}

宠物和配色一样按名字提供，ZettCode 自带的十三只（`cat`、`dog`、`tiger`、`polarbear`、`snowbear`、`penguin`、`scarfy`、`kangaroo`、`seagull`、`whale`、`chibi`、`slime`、`sprout`）也是由一个内置插件通过同一个调用提供的。一只宠物就是一张调色板，加上它各种心情的像素图：图里的每个字符对应一种颜色，`.` 是透明，两行像素组成一行字符单元格，所以行数必须是偶数，而且同一只宠物的每一帧大小相同：

```text
from zettcode.plugin_api import Pet
from zettcode.plugin_api import PluginContext, TuiPlugin

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

presenter 的 `handle(entry, next)` 就是它全部的认领声明：返回 `self` 表示画这一行，调用 `next(entry)`
表示交给下一个 presenter。注册表只负责排序并启动这条链，自己不匹配任何行。永远返回 `self` 的 presenter
会接管问它的每一行，所以位置很重要：把 catch-all 的 `priority` 放到内置 presenter 之下（例如 `-1`）才是兜底。内置 `ToolPresenter`
之所以是兜底，是因为它注册在具名工具 presenter 之前。

内置 presenter 按 `entry.kind` 认领；工具行的 presenter 按工具自己的名字（`entry.tool`）认领，所以
`read` 和 `read_file` 共用一个读取 presenter，`glob` 和 `grep` 共用一个搜索 presenter；其他工具家族各有自己的，
`ToolPresenter` 则是所有未命名工具的兜底。
插件可以只替换一种工具的行，而不影响另一种。`lines` 收到 entry、可用列数、配色和动画步数，返回
`TextLine`；宽度是预算，要自己换行或截断。需要动画的 presenter 读 `frame`，不需要的应当对任何 `frame`
都给出同样的行。

同一个位置有多个 presenter 时，`priority` 高的赢；优先级相同则后注册的赢。内置 presenter 就是这样成为默认的：
优先级 0，最先注册。插件想压过另一个插件，就在 presenter 类上把 `priority` 提高；只想画某一种行时通常不需要
优先级，后注册本身就是更窄的声明。

## 给请求加一个工具

setup hook 可以给每次请求加工具。工具是 `zett-agent` 的 `AgentTool`；插件只决定这次运行能看到哪些：

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

`on_tool` 在请求构建之前运行；这次加进去的工具只属于这次请求，下次要再加。
观察一次调用用 `before_tool`，替换结果用 `on_tool_call` middleware。

## 把整个扩展交给代理 {#extensions}

上面的钩子方法，运行在 ZettCode 为所有插件承载的同一个扩展里。如果一个插件本身就是一个扩展，或者包装了
`zett-agent` 的某个扩展，可以把它整个交出去：

```python
from zettcode.plugin_api import Plugin, PluginContext


class Audit(Plugin[PluginContext]):
    name = "audit"

    def activate(self, ctx: PluginContext) -> None:
        if ctx.config.workspace.name != "scratch":
            ctx.agent.register_extension(AuditExtension())  # zett_agent 的 AgentExtension
```

代理会把它和其他扩展并列收下，按扩展自己声明的 `priority` 排序，同级则按插件加载的先后。它的 `name`
必须唯一：重复了已注册的名字，或者叫 `plugins`，该插件会被报告。如果扩展导入很慢，或者需要代理起始的那个模型，
更适合用 `ctx.agent.register_extension_factory(name, build)` 注册：`build` 会在构建代理时才调用，而不是在界面还在
绘制的时候，返回 `None` 表示什么都不加。代理运行的每一个扩展都是这样注册的：ZettCode 自带的代码工具、会话日志、
shell 审批、压缩、`ask_user` 工具、项目指令、skills、MCP 和待办工具都是内置插件，所以 `[harness]` 等处的开关只是决定它们的插件注册与否。

## 依赖别的插件 {#deps}

插件用 `deps` 写出它需要的插件，ZettCode 会先激活被依赖的：

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
    deps = ("stats-provider",)  # 提供者的 `name`，不是发行包名

    def activate(self, ctx: PluginContext) -> None:
        stats = ctx.service("stats", Stats)
        stats.calls += 1
```

`deps` 里写的是插件的**名字**：各插件声明的 `name`；没有声明时就是它入口点的名字。依赖的插件不存在、被关掉、加载失败或处在环里时，
这个插件会被跳过并说明原因，需要它的插件也一样。彼此没有 `deps` 的插件按发现的顺序加载。名字就是插件的身份，
所以两个插件不能重名。发行版或单文件插件也不能占用别的插件已经有的入口名：先发现的保留，后来的不加载，并在日志里留一行。

插件用 `ctx.inject(name, service)` 把对象交给需要它的插件。运行时页面服务用类型化 reader 读取：
`ctx.agent.session_store_service()`、`ctx.agent.usage_ledger_service()`、
`ctx.agent.context_report_service()` 和 `ctx.agent.context_page_service()`；其他服务用 `ctx.service(name, kind)` 取（`ctx.find` 在没人提供时返回
`None`）。对象是什么、怎么用，由相关插件自己约定；ZettCode 只保证名字唯一、顺序正确。

## 事件发生时开始工作 {#triggers}

触发器（trigger）盯着某个事件（定时器、文件、套接字），在没有人提问时启动一段工作。插件把触发器连同处理函数一起注册，
会话开着的时候 ZettCode 就一直运行它：

```python
import asyncio
from zettcode.plugin_api import INBOX, Inbox, Plugin, PluginContext, Trigger, TriggerEvent, TriggerScope


class EveryMinute(Trigger):
    name = "every-minute"            # 首字符是小写字母或数字，之后可用小写字母/数字/._-，1-64 字符；同时是锁文件的名字
    scope = TriggerScope.MACHINE     # 整台机器只跑一个

    async def run(self, fire):
        while True:
            await asyncio.sleep(60)
            await fire({"reason": "tick"})


class Heartbeat(Plugin[PluginContext]):
    name = "heartbeat"

    def activate(self, ctx: PluginContext) -> None:
        # mypy 不接受抽象类作为 type[_T];运行时查找就是普通 isinstance。
        queued = ctx.find(INBOX, Inbox)  # type: ignore[type-abstract]
        self._inbox = queued
        ctx.agent.register_trigger(EveryMinute(), self.on_tick)

    async def on_tick(self, event: TriggerEvent) -> None:
        if self._inbox is not None:
            self._inbox.deliver(f"tick: {event.payload['reason']}",
                                mode="followup", origin="trigger")
```

`scope` 决定同时运行几份：

- `TriggerScope.PROCESS`（默认）：每个进程一份。同一进程里的第二个运行时不会再启动它。
- `TriggerScope.MACHINE`：整台机器一份，不管开了多少个 ZettCode 窗口。持有会话目录旁锁文件
  （`~/.zettcode/triggers/<name>.lock`）的窗口运行它，其余窗口待命，持有者退出后几秒内接手。持有者崩溃时操作系统会
  释放这把锁，所以崩掉的窗口不会卡住触发器。

触发器抛出异常会被标记为失败，不会自动重启；处理函数抛出异常只影响那一次事件。两个插件不能注册同名的触发器。

触发器只负责“发生了一件事”。要让 agent 真的动手，把事件交给会话的队列：`INBOX` 服务，它的类型 `Inbox` 和队列项
`Waiting` 都由 `zettcode.plugin_api` 导出，上面的处理函数就是这么做的。没人等着结果的事用 `mode="followup"`
更稳妥：它不会打断正在进行的请求。

插件如果打开了比一轮更长久的东西（连接、后台任务），在 `async def aclose(self)` 里释放。会话关闭时运行时调用它，
越晚加载的插件越先关。

## 插件 API 参考

这一节是精确查表用的。上面的正文说明什么时候用；这里只列名字、类型和默认值。

### `Plugin` 与 `TuiPlugin`

| 成员 | 含义 |
| --- | --- |
| `name` | 身份；被 `deps`、诊断和 `/plugins` 使用。为空时使用 entry-point 名字 |
| `origin` | entry-point 名字；单文件插件是文件 stem；由加载器设置。`[plugins] disable` 按它匹配 |
| `description` | 给作者和诊断用的一行说明；程序目前不显示它 |
| `deps` | 依赖的插件 **name**；加载器先激活它们 |
| `priority` | 宿主扩展内插件之间的顺序；越小越先。宿主取最小值，所以一个插件的 priority 会把整组 hooks 相对其他扩展移动到那个位置。默认 `100` |
| `setting` | 仅程序内部：编译进程序的插件的配置开关；第三方插件不声明 |
| `rank` | 仅程序内部：角色组内的排序；第三方插件保持 `0` |
| `default_enabled()` | 类方法；返回 `False` 表示要 `[plugins] enable = ["name"]` 才加载 |
| `cli_arguments()` | 类方法；返回启动和 `daemon spawn` 用的 `CliOption` |
| `activate(ctx)` | 同步；注册插件贡献的一切 |
| `aclose()` | 异步；释放长期资源，按激活逆序调用一次 |

`TuiPlugin` 是 `Plugin` 加四个可选行方法：
`render_header_left`、`render_header_right`、`render_status_left`、
`render_status_right`。每个接收 `ShellContext`，返回片段、`None`，或
`(片段, True)` 接管整侧。

### Agent hook 组

只需要覆盖自己关心的阶段。除 `accept` 外都是异步方法，默认什么都不做：

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

签名和可变的 context 来自 `zett-agent`。本身就是扩展的插件，用
`ctx.agent.register_extension()` 整体交给 agent；需要延迟导入或等到 agent 构建时再建，
用 `register_extension_factory(name, build)`，`build` 可以返回 `None`。

### Context 方法

| 方法 | 契约 |
| --- | --- |
| `service(name, kind)` | 必需；没有抛 `LookupError`，类型不对抛 `TypeError` |
| `find(name, kind)` | 可选；没有返回 `None` |
| `provide(name, value)` / `inject` | 给后面的插件发布；名字必须唯一，且不能是六个 `PLUGIN_*` 之一 |
| `register_provider(Provider)` | 往 `/config` 加模型主机 |
| `register_extension(AgentExtension)` | 把完整扩展交给 agent |
| `register_extension_factory(name, build)` | 延迟构建；`build` 可以返回 `None` |
| `register_mention(MentionProvider)` | 加一种 `@` 资源 |
| `register_trigger(Trigger, handler)` | 随会话启动长期 watcher |

### 命令

`ctx.commands.register(name, summary, handler, *, when_busy="refuse", subcommands=())`
加普通命令。handler 收到 `PlainCommandContext`：

| 字段 | 含义 |
| --- | --- |
| `argument` | 命令名之后去掉首尾空白的原始文本 |
| `level` | `deny`、`ask`、`safe` 或 `full` |
| `host` | `PlainCommandHost \| None`；用于 `compact`、`title`、`export` |

`TextCommandResult(message="", notification="", markdown="")` 返回文字、提示或文档。
`TurnCommandResult(prompt, shown="", notification="", cache="")` 开启一轮对话；
`cache` 是 `"read"`、`"read_write"` 或 `"off"`。

`ctx.tui.register_command(name, description, handler, *, when_busy="refuse",
subcommands=())` 加终端命令。handler 收到 `CommandContext`，有 `argument`、`ui` 和
`host`；`context.require_host()` 是 shell。`CommandResult` 字段是 `message`、
`notification`、`widget`、`relayout`、`intro`、`run`。`intro` + `run` 让慢命令的行保持
运行状态。

`when_busy`：

- `"refuse"`（默认）：请求进行中时拒绝。
- `"queue"`：等那一轮结束后运行。
- `"now"`：和请求并行；只用于读取，或改请求需要时才会读的设置。

### 屏幕贡献

没有终端时 `ctx.tui` 是 `None`。方法：

| 方法 | 加什么 |
| --- | --- |
| `register_command` | 带 `CommandUi` 和 `CommandHost` 的 `/命令` |
| `register_header_left/right`、`register_status_left/right` | 一个片段（`str`、`TextLine` 或 `Row`）；`name` 为空时追加（`segment-N`），`render_*` 覆盖则注册 `<region>_<side>` 并替换内置片段；`override=True` 清空该侧 |
| `register_turn_segment(name, summary, builder)` | 请求结束那一行的条目；name 以 `turn-` 开头 |
| `register_theme(name, theme, *, description="")` | 配色、文件或 builder |
| `register_pet(name, pet, *, description="")` | 宠物或 builder |
| `register_presenter(presenter)` | 行 presenter；后注册的同优先级胜出 |
| `register_focus_handler(handler)` | 窗口获得/失去焦点 |
| `register_turn_start_handler(handler)` | 一轮开始 |
| `register_turn_end_handler(handler)` | 一轮结束；停止/失败时 `completed` 为 false |

`register_turn_segment` 的名字必须以 `turn-` 开头；builder 收到
`TurnContext(label, seconds, clock, usage, tools, failed_tools)`，`[statusline]` 里对应的开关控制是否显示。
行方法收到 `ShellContext`：

| `ShellContext` 字段 | 类型 | 内容 |
| --- | --- | --- |
| `config` | `ZettCodeConfig` | 解析后的配置 |
| `session` | `SessionState` | `id`、`title`、`name`、`workspace`、`handle` |
| `model` | `ModelState` | `config`、`name`、`effort`、`efforts` |
| `activity` | `ActivityState` | `busy`、`status`、`note`、`auto_shell`、`usage`、`tasks`、`frame`、`permission`、`self_compact` |
| `display` | `DisplayState` | `theme`、`width`、`height`、`screen`、`scrolled_up` |

Presenter 实现 `handle(entry, next)` 和 `lines(entry, width, theme, frame)`。
`handle` 返回 `self` 认领，或 `next(entry)` 交给下一个。`priority` 决定平局；
`gutter` 要求标记列；`look` 说明渲染块依赖哪些字段；`block` 缓存渲染结果；
`text_lines` 按宽度换行和缩进。Entry 暴露 `id`、`kind`（`EntryKind`）以及类型相关字段，
如 `text`、`tool`、`title`、`diff`；`EntryStatus` 是 `running`/`completed`/`failed`/`skipped`。

### 配置和命令行

`ctx.settings.declare(**defaults)` 返回读者的值或默认值。可以调用多次，继续声明更多键；
`ctx.settings.get(key)` 读一个已声明键，`ctx.settings.values()` 返回全部。只允许 `bool`、`int`、`float`、
`str`。读者写在 `[plugins.<name>]`；类型不对会在激活时报出键名。

`cli_arguments()` 返回 `CliOption(flags, dest, help="", default=None,
action="store", choices=None, metavar=None)`。解析后的值是
`ctx.service(PLUGIN_CLI, dict).get(origin, {}).get(dest)`。参数放在子命令之前：
`zettcode --journal-limit 5 resume ID`。`daemon spawn` 接受同样的参数，并私下传给子进程。
坏掉的选项只跳过并打印一行，不会让 ZettCode 退出。

### 加载、顺序和失败

- `deps` 写插件名字，不是发行包名；缺失、被禁用、失败或成环的依赖会让依赖它的插件不加载，
  并说明原因。
- `default_enabled()` 为 false 的插件，只有在 `[plugins] enable` 点名、程序需要，或被保留的
  插件需要时才加载。
- 重复的身份、被另一个插件占用的命令名、service 名、扩展名、主题名和宠物名会让后一个插件失败，不会拖垮整个
  应用。
- 没有屏幕时 `ctx.tui is None`，屏幕相关代码必须判断。
- `Plugins.failures` 是 `origin: why`；`Plugins.taken` 记录输给前一个插件的名字。失败的插件
  不提供任何东西。
- `aclose` 按激活逆序执行；一个插件关闭失败只记录，不阻止其他插件。

## 测试插件

插件就是普通 Python。用测试 helper 建上下文，自己调用 `activate`，不需要真的终端：

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

没有屏幕半边时，用 `PluginContext(config, services)` 和 `ctx.commands`。屏幕测试需要安装程序本身
（`zettcode.app` 不是 `zettcode-plugin-api` 的依赖）；没有屏幕半边的插件只需要 `PluginContext`。
测试命令 handler 时构造 `PlainCommandContext(argument="...")` 或
`CommandContext(argument="...", ui=...)`；测试屏幕贡献时用 `ctx.tui` 和与应用相同的
helper。测试必须用临时目录：插件不能写读者的 home 或 checkout。

## 关掉一个插件

`/plugins` 打开一页，每个能关掉的插件前面一个开关：编译进程序的在前，装进来的在后。`~/.zettcode/plugins` 里的单文件插件
也算“装进来的”，而且无论开关状态都会列出来——被关掉的文件仍然留在页面上，只是显示为关，可以再打开。上下移动，左右和空格拨开关，Enter
把改动写下来，Esc 什么都不写。开关**下次启动**生效：当前这个会话还是用它已经加载的东西。

开关写到哪儿，看这个插件是哪一种：

- **装在程序旁边**的插件（包括 `~/.zettcode/plugins` 里的单文件插件）记在 `config.toml` 的
  `[plugins] disable` 里。`/plugins disable <名字>`、`/plugins enable <名字>` 对单个名字做同样的事。旧的
  `~/.zettcode/plugins.json` 仍然会读、会和配置合并，所以原来关掉的插件不会自己打开；下一次为某个名字写开关时，
  会把它从那个旧文件里删掉。
- **编译进程序**的插件由你本来就有的设置决定——`[skills] enabled`、`[mcp] enabled`、`[agents_md] enabled`、
  `[harness] subagent`、`[harness] todowrite`、`[harness] jit`、`[compaction] self`、`[ask_user] enabled`——
  面板写的就是配置文件里的那个键。没有这种设置的
  内置插件根本不会列出来：它上面没有可以按的东西。（加载失败的内置插件还是会列出来，写明原因——没有什么可按，
  但这件事值得知道。）
- 程序自己的**终端部分**里，非必需的（`themes`、`pets`、`context`、`usage`）会作为第三方行出现，
  `[plugins] disable` 能关掉；终端启动必需的四个不会列出，`zettcode plugin disable` 也关不掉这两类。

想要的名字已经被另一个插件占用的插件，会带一条说明列出来，但没有开关：拿到名字的那个留下，页面说明是谁没拿到，
而不是只把它写进日志。

`[plugins] disable` 里的名字现在可以从页面上重新打开：它就是普通开关，不再是“只能手改”的那一行。在哪儿问都是同一个
答案：终端的 `/plugins` 页面、编辑器的 **ZettCode: Show Plugins** 面板以及服务器上的 `PUT /plugins/{name}`，走的是
同一套规则、写的是同样的文件。

## 出问题的时候

导入或激活失败的插件会被跳过，而不是让程序挂掉。失败发生在哪里，结果不同：

| 失败 | 结果 |
| --- | --- |
| import、`activate`、重复身份，或名字冲突（另一个插件已占用的命令、主题、宠物、provider、mention、扩展、trigger、service） | 整个插件被拒绝，已注册内容全部丢弃；对话里出现 `origin: why`，也进 `Plugins.failures` |
| 依赖缺失、被禁用、失败或成环 | 依赖它的插件也被拒绝，并说明 `needs plugin 'x' …` |
| 命令抛 `ValueError` 或 `ZettCodeError` | 那句话作为命令自己的错误显示 |
| 命令抛其他异常 | 显示一行 `/<name>: <reason>`，traceback 写入日志 |
| focus / turn-start / turn-end handler 抛异常 | 显示一行 `a plugin hook failed: …`（只报告一次）；这个 handler 在之后的事件里仍会被调用。agent 侧 hook（`before_turn`、`on_tool` 等）失败会向上传播，让请求失败 |
| trigger 抛异常 | trigger 标记为 failed，不再重启；handler 抛异常只损失一个事件 |
| presenter 在绘制时抛异常 | 不会像 hook 那样隔离：对任何 frame 返回同样的行，不要抛 |

失败的插件不提供任何东西。`ctx.find` 返回 `None`；`ctx.service` 抛 `LookupError`。同样的信息还出现在 shell 的
`plugin: …` 行、`/plugins`，以及 SDK 客户端的 `client.plugins.failures`；`plugin list` 只显示安装和开关状态，不显示失败原因。结构化日志是
`~/.zettcode/log/` 下的 JSON lines（默认 `terminal.jsonl`）；`ZETTCODE_LOG_LEVEL=debug` 打开更多内容。`Plugins.taken` 记录输给
前一个插件的名字。两个插件不能重名，先到的保留。命令名也是共享的：shell 自己的四个（`/config`、`/theme`、`/pet`、
`/statusline`）或 agent 的命令（`/new`、`/compact`、`/export`）已经占用的名字会被静默丢弃——插件仍加载，但命令不列出、
不能运行，也不报告失败；安装后检查 `/help`。名字已被另一个插件（包括 `/model`、`/resume` 这样的程序插件）占用时，
插件加载失败并报 “command … is already registered by another plugin”，原因出现在 `Plugins.failures`。
