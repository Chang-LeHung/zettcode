# 常见问题

## 起不来

**`zettcode: Config key ... must be str` / `Unknown config keys ...`** —— 报错里会点名出错的键。
拼错的键会被拒绝而不是忽略，所以通常改拼写就好。完整的键见[配置文件](/zh/guide/config)。

**`zettcode: No models configured`** —— 这是 `zettcode ask` 和 `zettcode doctor` 在
`~/.zettcode/config.toml` 里还没有 `[[models]]` 表时的回答。终端不会因此停下：它照常打开，头部显示
`no model`，`/config` 会一步步问你要第一项配置 —— 供应商、model id、token —— 再把它写进那个文件；这台机器
从来没建过配置文件时，它会连文件一起建出来。在那之前输入的 prompt 会用同一句话拒绝，你写的字仍留在输入框里。
想直接改文件，可以照抄[快速开始](/zh/guide/getting-started#先配一个模型)里的例子。

**`zettcode: no session <id> in <path>`** —— `--resume` 给的 id 不在这个工作区的存储里。会话是
按工作区隔离的：确认 `-w` 指向的目录和创建会话时是同一个，或者直接运行 `zettcode` 用
`/resume` 从列表里挑。

## 起来了但用不了

**第一条请求就报连接错误。** `base_url` 是 OpenAI 兼容 API 的**根地址**，不是聊天网页，
也不是完整的 completion 路径。DeepSeek 使用 `https://api.deepseek.com`，其他接入点可能
需要 `/v1`。按[连接测试](/zh/guide/config#checking-the-connection)使用同一个模型和 key
验证，再检查 API 余额、权限和代理设置。

**模型名被拒绝。** 用接入点期望的 id，而不是某个界面里显示的名字 —— `display_model` 只是头部
显示用的，随便写。

**第一帧出得很慢。** 模型客户端延迟创建，但配置、存储和插件加载仍然发生在启动阶段。
macOS/Linux 可以用 `time zettcode --dry-run`，PowerShell 可以用
`Measure-Command { zettcode --dry-run }` 测量本地启动流程。它会绘制一帧后退出，
不是 API 连通性检查。先比较关闭第三方插件后的时间，不要直接把延迟归因于模型或终端。

## 界面

**颜色不对，或者文字看不清。** 用 `/theme light` 或 `/theme dark`。启动时 ZettCode 会问终端
背景色是什么；终端不回答、中间隔了 multiplexer、或者 `TERM` 报错了颜色深度，都可能让它判断
失误。`/theme` 对本次运行生效，`config.toml` 里的 `[ui] theme = "..."`（或 `~/.zettcode/theme.toml`）则是一劳永逸。
输入 `/theme ` 和一个空格会打开菜单，在里面移动时会预览每一套配色。

**用久了显示乱掉。** 按 `Ctrl-L` 重画。窗口大小变化是被处理好的，但别的程序绕过 ZettCode 直接
往终端写，这个没法处理。

**在终端里选不中 / 复制不了。** ZettCode 在你松开拖动时自己复制选区，所以绕开了终端自带的选择。
想用终端自带的，按住它的修饰键（<kbd>Shift</kbd> 或 <kbd>Option</kbd>）再拖。

**粘贴图片没反应。** 图片粘贴需要桌面剪贴板，所以 macOS 可用，Linux 需要装 `wl-paste` 或
`xclip`，Windows 暂不支持。把图片**当文本**粘贴的终端（比如 VS Code 的）我们也能识别。

## 会话

**对话丢了。** 所有内容都是边发生边追加到
`~/.zettcode/sessions/<工作区键>/<会话 id>/data.jsonl`，所以它还在：`/resume` 会列出这个
工作区最近的会话（新的在前）。会话目录里的 `metadata.json` 存着它的标题。

**恢复出来的会话不一样。** 标题和 token 统计来自元数据索引，对话来自 JSONL 树。如果崩溃截断了
文件的最后一行，那一行会被忽略，其余部分照常加载。

**对话内容和我说的话不一致。** 模型看到的是它该看到的，屏幕显示的是你打的内容。`@skill` 和
图片芯片会为请求展开、但为你保留成芯片，所以恢复会话时看到的是芯片。

## 上下文与花费

**`ctx` 很高而且在涨。** 打开 `/context`：百分比是窗口内部的占比，所以最大的那一行就是占地方
的东西 —— 通常是工具输出。`/compact` 可以不等触发线直接总结。详见[上下文窗口](/zh/guide/context)。

**缓存命中率很低。** provider 缓存的是前缀，所以请求开头任何变化都会打断它：不同的系统提示、
不同的工具集合、不同的模型。切换模型、压缩和修改指令可能让比例下降，缓存寿命也由供应商
决定，没有通用的“正常百分比”。计算方式和例子见[读懂状态行](/zh/guide/models#读懂状态行)。

**跑了我不想跑的命令。** 先看状态栏里的档位：`· full` 表示每条命令都用你自己的权限直接跑，`· safe` 表示命令在只能写工作区和
`/tmp` 的沙箱里跑（Windows 或没有 `bwrap` 的 Linux 上，是认出只读的命令直接跑），没有标记就是 `ask`。`/permission ask` 把询问放回来，`/permission deny` 则完全禁止 shell
命令。用 `--full`（或 `--auto`、`--yolo`）启动的这轮也一样从 `full` 开始，只是对话里不会有那行公告。之前的审批选择也要看：`a` 切到了 `full`，`s` 切到了 `safe`，`p` 会在当前进程中记住精确命令，
重启会把这些全部清除。档位针对内置 shell 工具，不覆盖文件编辑或 MCP 工具，而且只有 `safe` 会做沙箱，
应使用版本控制并检查 diff。

## Skills、MCP 与插件

**我的 skill 没出现。** 它需要是一个目录，里面有 `SKILL.md`，且 front matter 带 `name` 和
`description`，位置在 `~/.zettcode/skills/` 或配置的 `[skills] roots` 下。只有 front matter
会被索引；同名时前面的根目录优先。

**MCP 服务器起不来。** 它的横幅和报错都写进 `~/.zettcode/log/tui.log`，因为画到屏幕上会把
画面弄乱。启动失败的服务器会在对话里被点名；常见原因是 URL 写错或连不上。

**插件被跳过了。** 在普通 Python 里 import 它就能看到真正的报错；ZettCode 会报出插件名并让
会话继续。两个插件不能重名，也不能占用已存在的命令名。

## 新版本

**它提示我升级。** ZettCode 每天会在后台向 PyPI 问一次有没有新版本；启动从不等待这个请求，
`[update] enabled = false` 可以完全关掉。查到更新的版本后，下一次启动会在对话之上弹出面板：

- **Upgrade now**：按当前安装方式执行升级 —— `uv tool upgrade zettcode`，或
  `pip install --upgrade zettcode` —— 在后台跑，而且**直接从 PyPI 的索引下载**
  （`https://pypi.org/simple`），因为最新版本就是从 PyPI 读到的：机器上配置的镜像可能落后，
  包管理器于是对早已发布的版本回答“already satisfied”。点下升级的那一刻会**再从 PyPI 读一次版本**，
  所以用来判定的不是上次检查写进文件的值；读不到时才回退到文件里的那个。
  **升级期间窗口不接受输入** —— composer 锁住，和“会话被另一个进程打开”时一样 ——
  因为要应答的代码正在被替换。当前窗口用的还是启动时的代码，升级后需要重启。
  包管理器正常退出不等于装上了新版本（`uv tool upgrade` 会提示 “Nothing to upgrade” 并返回成功；
  pip 在索引还没列出这个版本时也一样），所以之后 ZettCode 会用一个全新的进程把已安装的版本读回来，
  并如实告诉你：**装好了**、**仍是旧版本**（几分钟后再试）、或**读不回来**。只有确认装上的版本才会写进
  `~/.zettcode/update.json`、不再被提示；没有生效的升级，下次启动会再次提示。
- **Skip this version**：把版本记进 `~/.zettcode/update.json`，这个版本不再提示，再往后的
  新版本会重新提示。
- **Not now**（或 `Esc`）：什么都不写，下次启动还会就同一个版本再问一次。

提示来自那个文件而不是网络，所以离线机器不会看到任何版本相关的打扰。

**我不想等它提示。** 在 shell 里运行 `zettcode update`：它会先问 PyPI，已经是最新版就直接说明，否则用和
**Upgrade now** 相同的方式执行升级，包管理器的输出直接显示在你的终端上。然后它从一个全新的进程里读回已安装的版本，
只有确实读到新版本时才报告 `updated 0.1.0 → 0.2.0`（否则说明版本没变或者无法读回；升级失败时退出码为 1）。
升级是**从 PyPI 自己的索引**下载的，而不是机器上配置的镜像：镜像可能还没同步，会把一个更新的版本答成 “already satisfied”；
反过来，如果这台机器只能访问内网镜像，这次升级会失败，那就手动装镜像里的那份（`pip install --upgrade zettcode`
或 `uv tool upgrade zettcode`，不带索引参数）。已经打开的 ZettCode 需要重启才能用上新版本。

**我升级了，可它还是显示旧版本。** 先看你启动的是哪一份：`zettcode --version` 会打印版本，
`which zettcode` 会告诉你启动的是哪个命令。如果 ZettCode 已经确认装上了新版本、而你启动的程序仍是旧的，
说明有别的东西在提供代码 —— 一个可编辑安装的检出目录，或者 `PYTHONPATH`。这时 ZettCode 会说明一次
（并指出正在运行的代码来自哪个目录），而不是再提示同一个升级。另一份从没升级过的副本（比如 `uv tool` 旁边
还有一份 `pip` 安装的）会照常被提示升级，并且显示的命令是针对正在运行的那一份的。

## 诊断日志

**出错了要反馈时，日志在哪？** 三个常驻程序各有一份：

- 终端：`~/.zettcode/log/tui.log`
- broker：`~/.zettcode/broker/broker.log`
- gateway：`~/.zettcode/gateway/gateway.log`

程序会为关键事件追加一行 JSON；失败时还会带上异常类型、消息和 traceback。这些 JSON 行会和各个程序自己的文本日志混在一起（uvicorn、broker 的启动/停止行，以及子进程在界面占用屏幕时写出的内容），所以请逐行解析。上面的路径是默认值：`ZETTCODE_BROKER_DIR` 和 `ZETTCODE_GATEWAY_DIR` 会移动后两份。daemon 自己的日志在 `~/.zettcode/daemon/<workspace>/<session-id>/log`，也可以用 `zettcode daemon log <id>` 查看。程序不会额外写入提示词、消息正文或凭据字段，但异常的 message 和 traceback 会原样写入；附加日志前请先检查。

## 退出

**怎么退出？** `/quit`，或者在输入框为空时按 `Ctrl-D`。**Ctrl-C** 是停止正在跑的请求、请求为
空时清空草稿 —— 它不是退出。退出时会打印恢复当前会话的 `zettcode resume …` 命令。
