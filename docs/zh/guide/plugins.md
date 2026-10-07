# 插件

插件是一个 Python 包，用来给 ZettCode 加东西：一个命令、一个工具、屏幕上的一行，或者对模型
收到内容的调整。装上这个发行包就是“启用”，不需要改什么注册表。

## 安装一个插件

插件在 `zettcode.plugins` 这个 entry point 组下发布一个类：

```toml
[project.entry-points."zettcode.plugins"]
greeter = "my_package:Greeter"
```

```python
from zettcode.app.commands import CommandContext
from zettcode.plugins import CommandResult, Plugin, PluginContainer


class Greeter(Plugin):
    name = "greeter"
    description = "say hello"

    def activate(self, container: PluginContainer) -> None:
        container.register_command("greet", "say hello", self.greet)

    async def greet(self, context: CommandContext) -> CommandResult:
        return CommandResult(notification=f"hello {context.argument}".strip())
```

把插件安装到 **ZettCode 使用的同一个 Python 环境**，再重启，命令就会出现在 `/` 菜单里，
排在内置命令之后。安装到另一个虚拟环境，不会让 `uv tool` 安装的 ZettCode 自动发现它。

例如，本地已有一个插件项目 `/path/to/greeter`，可以这样安装：

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

`Plugin` 组合了两组钩子，插件只覆盖自己关心的阶段：

- **代理的工作** —— 和 `zett-agent` 扩展同一套生命周期：setup、run、turn、model、tool、
  compaction，以及外部事件。插件可以注册工具、改写发给模型的消息、转换工具结果，或者观察一次
  运行的结束。
- **屏幕** —— 头部和状态行各自分成左右两侧，每一侧都由注册过的片段共同画出来。

```python
from zettcode.plugins import Plugin, ShellContext


class WorkspaceLabel(Plugin):
    """用模型和工作区标签替换头部右侧片段。"""

    name = "workspace-label"

    def render_header_right(self, context: ShellContext) -> str:
        return f"{context.model.name} · {context.session.workspace.name}"
```

返回 `str`、带样式的 `TextLine`，或者 `None`（什么都不画）。没有自带样式的片段会继承这一行的
灰色样式，所以默认看起来是融进去的，想上色再上色。用已存在的名字注册会**原地替换**那个片段；
新名字追加在该侧已有的片段之后。返回 `(value, True)` 表示独占该侧，这是在不知道内置名字的
情况下接管整侧的做法。

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

## 出问题的时候

导入或激活失败的插件会被跳过，而不是让程序挂掉：对话里出现一行 `plugin: …`，会话继续正常
工作。两个插件不能重名；抢同一个命令名时，后一个会被跳过，而不是悄悄替换前一个。
