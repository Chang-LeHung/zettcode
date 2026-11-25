# 插件

插件是一个 Python 包，用来给 ZettCode 加东西：一个命令、一个工具、屏幕上的一行、一个模型 host、一套配色、一只
宠物，或者按定时器跑起来的活。装上这个发行包就是启用，没有注册表要改。

## 安装一个

```sh
zettcode plugin install owner/repo                 # GitHub 仓库，也可以跟 tag、分支或 commit
zettcode plugin install /path/to/greeter           # 本地项目、wheel 或 sdist
zettcode plugin install ./greeter.py               # 单个 Python 文件
```

包装进 `zettcode` 所在的那个环境，重启后它的命令就出现。单个 `.py` 文件不装进 site-packages，而是复制到
`~/.zettcode/plugins`：每次启动加载它定义的每个 `Plugin` 类，所以只能是一个模块、不能用相对导入，内容不同时
要加 `--force` 才能覆盖。手工装就是 `uv tool install --force --with /path/to/greeter zettcode`，或者在
ZettCode 所在的环境里 `pip install /path/to/greeter`。

`zettcode plugin list` 列出每个插件的 origin、位置和开关；`--json` 给程序读。
`zettcode plugin uninstall <name>` 删掉一个单文件插件或一个发行包。

::: warning 只装你信得过的插件
插件在 ZettCode 进程里跑 Python，既能改模型干的活，也能改你的文件。它不受沙箱保护：装之前先读源码。
:::

## 这个仓库发布的插件

| 包 | 加了什么 | 装法 |
| --- | --- | --- |
| `zettcode-models` | 为环境里的每个厂商 key 提供一个官方模型：OpenAI、Anthropic、DeepSeek、Z.AI | `zettcode[models]` |
| `zettcode-recap` | `/recap`：你离开时，说明这个会话到哪儿了 | `zettcode[recap]` |
| `zettcode-monitor` | `/monitor`：每次模型调用和它的回答导出成 HTML，不脱敏 | `zettcode[monitor]` |
| `zettcode-code-agents` | 把 Codex 与 Claude Code 作为会话和群组的成员 | `zettcode[code-agents]` |
| `zettcode-ssh` | 终端 `/ssh` 面板：选择 SSH 主机，用密钥/agent 或密码登录，通过长连接操作远端文件 | `zettcode[ssh]` |

`zettcode[all]` 把五个一起装上；`code-agents` 是网关插件，终端里看不到它。
`/ssh` 列出 `~/.ssh/config` 中的具体主机别名，也支持手动输入，连接需要 full 权限。
密码在面板里输入，只留在内存中，不会保存，也不会被子进程 daemon 继承。
远端需要 Python 3.10+，不需要安装 ZettCode。

`/monitor` 自带面板：这个会话的两个开关——记录它的模型调用、连图片数据一起记——再加一行把目前为止
记下的内容写成工作区里的一个 HTML 文件，不脱敏。

![`/monitor` 面板：记录开关、图片开关，以及写出报告的那一行](/screens/monitor.svg)

`←` `→` 只是挪开关，还没生效；`Enter` 两个一起保存并关掉面板，光标在 Export 那行时先写出文件；`Esc` 什么都不应用
直接关掉。一条记录都没有时导出会让面板留着，并说明原因。

## 打开或关掉一个

`/plugins` 打开一页，你能关的插件每个一个开关：`←` `→` 翻转一个（点开关也行），Enter 写入，Escape 什么都不写，打字则把
列表收窄。

![`/plugins` 页面：每个插件带序号，能关的排在前面、固定的排在后面，每行带开关、开关写入的配置键或发行包名字，以及它带来什么](/screens/plugins.svg)

每一行都带它在整个列表里的序号，能关的插件排在前面：被配置文件按住、或程序离不开的插件排在它们后面，那一行没有
开关，写的是 `fixed`（加载失败时是 `failed`），原因在列表下面那行。打插件名字、发行包名字或那句“它带来什么”里的
任意一段——`search`、`html`——列表就只留包含它的插件。序号不随搜索变化：搜索只筛行、不重排，所以光标所在那一行还是
原来的序号、开关和配置键。Backspace 删掉一个字符，Escape 先清空搜索框，再按一次才关掉页面。

每一行都写明开关落在哪一边：编译进程序的插件由配置键决定（`rows.enabled`），安装的插件由 `[plugins] disable`
决定。加载失败的插件也留着那一行——你就是这么知道它失败的——而这次进程从没读到过设置的插件根本没有开关，
原因写在列表下面那行。
`zettcode plugin enable <name>` 和 `zettcode plugin disable <name>` 对单个名字做同样的事，`/plugins
disable <name>` 在输入框里就能做。所有开关都在**下一次启动**生效。

```toml
[plugins]
enabled = true          # false 会放下所有插件，只留程序离不开的那几个
disable = ["recap"]     # 下次启动时不加载这些插件
enable = ["quiet"]      # 一个自己声明默认关闭的插件
```

`disable` 和 `enable` 写的是插件的 **origin**——它的 entry-point 名字，可能和包名、也和插件自己的 `name`
不同。每个插件在页面上都有一行，不管它已加载、已关闭、默认关闭还是加载失败。已经有自己设置的插件由那个键开关
（`[mcp] enabled`、`[skills] enabled`），页面写的是那个键；`disable` 行或 `enabled = false` 仍会拦住它，打开它时会清掉那一行。
大约二十个插件是程序离不开的——agent 的工具、shell 权限、会话日志、用量、上下文和压缩，以及终端的 shell 行、回合行、渲染器和命令——
`disable` 行和 `enabled = false` 都管不到它们，也没有 `[plugins]` 开关（其中 `subagents` 和 `self-compaction` 仍有各自的 setting）。

要画界面的插件（shell 行、渲染器、命令、配色、宠物）发布在单独的 entry-point 组 `zettcode.tui` 里，只有终端会读它，所以脚本或服务端
这类不开界面的进程不会导入它们。你自己的插件两个组都可以用；只有它要导入终端时才用 `zettcode.tui`。

## 插件的配置放在哪

配置是 `config.toml` 里的一张 `[plugins.<name>]` 表，和开关并排。插件自己声明每个键，以及你没写时它的取值：

```toml
[plugins.recap]
after_seconds = 240
```

`<name>` 是插件自己的名字，不是 origin。类型不对的值在插件激活时被拒绝，消息会指出表和键。你不需要自己写
`[plugins]` 这一行：`/plugins` 会把表头加在你的表下面，你写的表一处不动。

## 插件能加什么

### 在 provider 上提供模型 {#providers}

一个 host 的模型直接出现在 `/model` 里，不写进 `config.toml`，token 来自环境。详见
[在 provider 上提供模型](/zh/guide/plugin-api#providers)。

### 从环境变量得到官方模型 {#official-models}

`zettcode[models]` 为它找到的每个厂商 key 注册一个当前的官方模型；没有配模型的机器就用它启动。详见
[从环境变量得到官方模型](/zh/guide/plugin-api#official-models)。

### 配色和宠物 {#pets}

`/theme` 和 `/pet` 也来自插件，所以插件可以带一套配色或一只宠物；内置的那些也是同样的方式提供的。详见
[提供配色](/zh/guide/plugin-api#themes)和[提供宠物](/zh/guide/plugin-api#pets)。

### 命令、行、工具和 trigger

一个在每个前端都能用的 plain `/command`、一个带自己页面的终端命令、对话里的一行、请求里的一个工具，以及按
定时器开始的活。从[写一个命令](/zh/guide/plugin-api#写一个命令)入手。

## 插件加载不了的时候 {#when-something-goes-wrong}

导入或激活失败的插件会报成 `plugin: …`，程序其余部分照常工作。名字被占用是最常见的原因：shell 自己的命令会说
都不说就丢掉，别的插件占用的则让这个插件失败。`/plugins` 和 `zettcode plugin list` 说明是哪个插件、它现在
什么状态；[参考页](/zh/guide/plugin-api#出问题的时候)有每种失败的结果和怎么看到它。

## 写一个

插件是一个 `Plugin` 子类，它的 `activate(ctx)` 注册要加的东西，再加上 `pyproject.toml` 里的一个 entry
point；`zettcode-plugin-api` 是它唯一的依赖。[插件 API](/zh/guide/plugin-api)有一个完整例子、每一种注册、
参考表和测试辅助。

## 下一步

- [插件 API](/zh/guide/plugin-api)：写、测试和注册一个插件。
- [Skills 与 MCP](/zh/guide/skills-and-mcp)：不写代码也能加工具和指令。
- [命令参考](/zh/guide/commands)：内置命令，以及插件的名字只能占哪一块。
