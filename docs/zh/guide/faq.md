# 问题与排查

东西不工作的时候从这里看。每个答案一段话，后面一个链接；细节在链接的那一页。

## 装不上，或者找不到 `zettcode`

引号要留着：`uv tool install "zettcode[all]"`——`fish` 和 `zsh` 会把没加引号的 `[all]` 当通配符。装完
之后报 `command not found: zettcode`，说明工具的目录不在 `PATH` 上；`uv tool install` 会打印该加的那行。
从 0.3 升上来遇到 `ModuleNotFoundError`，是包管理器把旧发行包的文件在新文件写完之后按路径删掉了，覆盖装一次：
`pip install --force-reinstall "zettcode[all]"`。见[快速开始](/zh/guide/getting-started)。

## 起来之后没有模型，或者第一个请求就失败

`No models configured` 表示 `~/.zettcode/config.toml` 里没有 `[[models]]` 表：终端照样打开，头部显示
`no model`，`/config` 带你写第一个条目。连接错误通常是把 `base_url` 写错了——那是 API 根，不是聊天网页，
DeepSeek 用 `https://api.deepseek.com`，有些端点要加 `/v1`。用[检查连接](/zh/guide/config#checking-the-connection)
确认，可用的条目见[快速开始](/zh/guide/getting-started)。

## `ctx` 很高

打开 `/context`：那里每个百分比都是**请求**的占比，所以最大的那一行就是占位的东西，通常是 `Tool output`。
改读一段行而不是整个文件，关掉不用的 MCP server 和 skill。见[上下文窗口](/zh/guide/context)。

## 我现在就想压缩

`/compact` 立刻总结这段对话，不等触发线，只把最后一轮原样留下。它不是 `/clear`：它改的是后面的请求带什么，
不是屏幕上看什么。见[压缩](/zh/guide/context#compaction)。

## 我不小心停掉了请求

`Esc` 或 `Ctrl-C` 停掉请求，它已经做完的事都留着。`/continue` 从停下的地方接着做；失败、或者撞到输出上限的
请求也这样续。见[命令参考](/zh/guide/commands#continue)。

## 提示有新版本 {#新版本}

ZettCode 每天在后台问一次 PyPI，有新版本时弹出面板：**Upgrade now**、**Skip this version**、**Not now**。
只有确认装好的才会被记住；窗口还跑着启动时那份代码，装完要重启才用上。`[update] enabled = false` 关掉
检查，`zettcode update` 不用等提示就能升。见[可选功能](/zh/guide/config#可选功能)。

## 在 Windows 上

在 Windows Terminal 里装和跑，别用老的 console，它送不出界面需要的按键。`safe` 级别在 Windows 上不做沙箱
——只跑它认得的只读命令——所以把级别留在 `ask`，一条命令按一次键。图片粘贴不可用，给模型一个路径。见
[审批](/zh/guide/interface#the-safe-sandbox)。

## 会话丢了

丢不了：每个会话一有内容就追加到 `~/.zettcode/sessions/<工作区 key>/<会话 id>/data.jsonl`。`/resume` 列出
这个工作区的会话，最近的在前；`--resume` 只有在 `-w` 指向它创建时那个目录时才找得到。见
[会话管理](/zh/guide/sessions#存在哪里)。

## 短问题

- **颜色不对。** `/theme light` 或 `/theme dark` 管这个会话；`config.toml` 里的 `[ui] theme` 让它长期有效。
  [颜色](/zh/guide/config#颜色)。
- **画面花了。** `Ctrl-L` 重画。有程序绕过 ZettCode 直接写了终端，就修不回来了。[对话区](/zh/guide/interface#对话区)。
- **复制不行。** 松手时 ZettCode 自己复制选中的内容；要用终端自己的，按住 <kbd>Shift</kbd> 或 <kbd>Option</kbd>
  再拖。走 `ssh` 时见[通过 `ssh` 复制](/zh/guide/interface#copying-over-ssh)。
- **某个 skill、MCP server 或插件没反应。** 失败会按名字报出来，会话继续；把插件拿到普通 Python 里导入就能看
  到它的错误，server 的 banner 在 `~/.zettcode/log/tui.log`。见[插件](/zh/guide/plugins#when-something-goes-wrong)
  和[Skills 与 MCP](/zh/guide/skills-and-mcp#服务器或工具出问题时)。
- **要报一个故障。** 附上 `~/.zettcode/log/tui.log`（终端输出）和 `~/.zettcode/log/terminal.jsonl`（事件），
  里面失败的那条带 traceback。`ZETTCODE_LOG_LEVEL=debug` 会加上请求和工具路径。先自己读一遍：消息正文不记，
  traceback 是照原样写的。
- **升级了但还是旧版本。** `zettcode --version` 和 `which zettcode` 说明你启动的是哪一份；可编辑的 checkout
  或者 `PYTHONPATH` 可能在供给代码，ZettCode 会说明一次，而不是再提示你升级。
- **对话和我发的不一样。** `@skill` 和图片这类 chip 会为请求展开，给你留的仍是 chip，所以恢复的会话显示的是
  chip。
- **会话恢复得不一样。** 标题和总量来自 metadata 索引，对话来自 JSONL 树；崩溃截断的最后一行会被忽略，其余的
  照常加载。
- **怎么退出？** `/quit`，或者在空输入框里按 `Ctrl-D`。`Ctrl-C` 是停请求，不是退出。

## 下一步

- [快速开始](/zh/guide/getting-started)：装好、加模型、开始干活。
- [认识界面](/zh/guide/interface)：屏幕每一行是什么。
- [命令参考](/zh/guide/commands)：所有斜杠命令。
