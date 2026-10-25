---
title: VS Code 里的 ZettCode
---

# VS Code 里的 ZettCode

这个扩展把终端应用里的同一个 agent 放进编辑器的二级侧边栏：提出改动、看它动手、检查它碰过的文件，并且每一个
shell 命令都在你的控制之下。它通过 HTTP 和本机的 `zettcode-server` 说话，活儿由服务器来干。

- **提出要求，然后看着它做。** 回答逐字流出，代码高亮，表格、公式和图表都在。它读过的每个文件、每次编辑和每条
  命令都是一行，点开就能看到发生了什么；失败的那一行会直接展开并说明原因。
- **跳到代码。** 回答里的路径就是链接，点开就是那个文件的那一行。
- **看看改了什么。** 每次请求结束后有一张卡片，列出它改过的文件和增删行数，点开是 VS Code 自己的 diff。
- **保持控制。** shell 命令先问你，问题等你回答，请求运行中还可以插话改方向。
- **重新打开，图片还在。** 保存下来的会话会完整回来，包括图片。

## 安装

扩展已经上架 [Visual Studio Marketplace](https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode)，发布者
是 **zettcode**。

1. 打开扩展视图（`Ctrl/Cmd+Shift+X`），搜 **ZettCode**，安装。或者装 `.vsix`：

   ```bash
   code --install-extension zettcode-0.1.7.vsix
   ```

   [市场页面](https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode)上写着最新版本；
   [releases 页面](https://github.com/Chang-LeHung/zettcode/releases)上的 `.vsix` 可能更新。

2. 打开一个文件夹。一个窗口服务一个文件夹；多根工作区用第一个。
3. 点右侧二级侧边栏里的 ZettCode 图标，或者运行 **ZettCode: Focus Chat**。想放左边？把图标拖过去。
4. **不用另外装东西。** 聊天第一次启动时，扩展会先找 `PATH` 上或文件夹 `.venv` 里的 `zettcode-server`；找不到就
   用自己的目录（`globalStorage/server/venv`）装一个，用 `uv` 或你的 `python3`。它和终端用的 agent 是同一个包，只是
   装在单独的目录里，跟你的项目分开。想自己装：

   ```bash
   uv tool install zettcode
   ```

   不想让它自动装，就把 `zettcode.server.autoInstall` 关掉。

5. **加一个模型**：在欢迎卡片里填模型 id，API key 可以不填。终端应用里配置好的模型直接可用，因为用的是同一个配置文件。
6. 问点什么，比如 *给我讲讲这个代码库*。

VS Code 会先请你信任这个文件夹：agent 要在里面跑命令、改文件。

## 提出要求

| 你想做 | 怎么做 |
| --- | --- |
| 发送 | `Enter`；换行用 `Shift+Enter` |
| 它干活时插一句话 | `Enter` 排一条后续消息；`Ctrl/Cmd+Enter` 插进正在跑的请求 |
| 停止 | `Esc`，或停止按钮 |
| 在对话里查找 | 光标在聊天里时按 `Ctrl/Cmd+F`；`Enter` / `Shift+Enter` 跳到下一处和上一处，`Esc` 关闭 |
| 提到一个文件 | 输入 `@` 再选 |
| 附一张图 | 粘贴、拖到视图里，或者点回形针 |
| 附别的东西 | 点回形针选择：PDF、压缩包之类会以**路径**写进消息，agent 用工具自己打开 |
| 粘贴复制的文件 | 在资源管理器或文件管理器里复制文件再粘贴，写进输入框的是完整**路径**，不再是单独的文件名。网页拿得到文件名和内容，拿不到路径，所以插件直接向系统剪贴板要真实路径（macOS、Windows、Linux；任意大小、任意位置的文件都行，比如桌面上的 PDF）。要不到时，用工作区里内容完全相同的那个文件，再不行就把内容在插件自己的存储里存一份；超过 10 MB 的文件只能按名字查找。远程窗口（SSH、WSL、容器）里的剪贴板不是你复制文件时的那个，所以直接用内容 |
| 运行命令 | 输入 `/`：`new`、`resume`、`continue`、`compact`、`fork`、`rename`、`export`、`model`、`effort`、`permission`、`harness`、`usage`、`context`、`doctor`、`btw` |
| 不加入对话地问一句 | `/btw 你的问题` |

附上的图片会发给能看图的模型，并随会话保存，所以重新打开会话时显示的是图片本身，而不是只数一数有几张。

### 在对话里移动

- **左侧的消息条**标着你发出的每一条消息。鼠标移上去，指针附近的条会变粗并显示那条消息；点一下就跳过去。条多到
  会挤在一起时，一条代表十条消息：点它会把这十条列在旁边，再从中挑一条。
- **Show earlier requests** 会把更早的消息一页一页加载进来，不打乱你的位置。
- **压缩**会出现在它发生的位置，点开就是它留下的摘要。

### 同时跑几个会话

你去看别的会话时，请求不会停。agent 干活的时候打开会话列表，新建一个会话或打开旧的都行：那边的活照常在跑，
列表里这个会话会有一个小转圈（还写着 *running*）。再打开它，对话就在跑到的地方，没跑完还在继续输出。
每个会话有自己的审批、提问和 steer，所以某个会话里等你确认的命令不会出现在另一个会话里；后台的会话
在等你回答或者跑完时，扩展会提示一声。

### 会话之间的消息

消息里写 `@名字`，就是让模型注意另一个 ZettCode 会话（终端，或另一个编辑器窗口）。模型会读到那是哪个会话，
并能用自己的工具给它发消息：发送会显示成一行 `send_message`，带正文和送达行，你自己的消息仍按你输入的样子显示。
别的会话发来的消息会作为一轮单独的请求出现，标着 *from @名字*，由 agent 在这里回答；
要让对方也听到，它会自己再发一条消息回去。

### 审批、提问与插话

shell 权限决定 agent 能自己跑什么：

| 级别 | 行为 |
| --- | --- |
| `deny` | 完全不跑 shell 命令。 |
| `ask` | 每条命令都等你批准。 |
| `safe` | 每条命令在只能写工作区和 `/tmp`、没有网络的沙箱里跑。 |
| `full` | 所有命令都用你自己的权限跑，不问。（`auto` 是旧名。） |

在聊天里选的级别会在工作区里下一次新会话时沿用。审批会等 `zettcode.answerTimeout` 秒，然后采用安全的答案；提问没有超时，会一直等你回答。

## 图片、图表与代码

栏里放不下的东西都在对话上方的一个弹窗（lightbox）里打开：图片、Mermaid 图、表格或代码块。能放多大，取决于它是什么。

| 对象 | 行为 |
| --- | --- |
| 你发的图片 | 点一下（消息里或输入框下面的缩略图）就会在对话上方打开，按窗口大小铺开 |
| Mermaid 图 | ```` ```mermaid ```` 围栏会被画出来，而不是当代码显示。点图本身或标题栏里的放大按钮，可以放大看 |
| 表格 | 角落里的放大按钮把它按整宽打开 |
| 代码块 | 标题栏里的放大按钮把它按整宽打开，不再受栏宽限制 |

放大后的弹窗里，滚轮以指针为中心缩放，`+` / `−` 缩放，`0` 重新适应窗口，拖动可以平移，双击在适应窗口和原始大小
之间切换。`Esc` 关闭它，而且这个按键不会传到输入框，所以不会顺手停掉后面正在跑的请求。画不出来的图会保留代码并
在第一行说明原因；任何图的源码都只差一次点击。

## 模型、effort 与权限

输入框下面那排 chip 用来选模型、推理 effort 和 shell 权限；命令面板里对应的是 **Select Model**、**Select
Reasoning Effort** 和 **Select Shell Permission**。**Add Model** 会往终端应用用的同一个 `config.toml` 里写新条目。

添加模型的表单和终端的 `/config` 用同样的键。只有**模型 id** 是必填的；**API key** 对本地服务器（Ollama、LM Studio、vLLM）
可以留空，也可以改用环境变量 `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`。**API** 在 **Chat completions**（写成 `chat = true`）、
**Responses API** 和 **Anthropic Messages API** 三者里选一个。**Temperature** 是 0 到 2 的数字（Anthropic 为 0 到 1），
留空就不发送。**Web search** 让供应商替模型联网搜索，**tool name** 可以覆盖各 API 默认发送的类型
（`web_search`；Anthropic 用 `web_search_20260318`；DeepSeek 用 `web_search_20250305`）；DeepSeek 只在 Anthropic API 下接受，
表单会在发出之前就告诉你。**Edit Model** 可以改已有模型的这些项：换一种 API 会把旧的标记从文件里删掉，而不是留下 `anthropic = false`；
清空 temperature 或关掉搜索会删掉这个键。

## 花了多少

**ZettCode: Usage** 打开一页，带终端里的三个标签——模型、会话、日历——而且**只算这个工作区**：每个文件夹有自己的
账本，别的项目的花费不在里面。页面标题下面会写明是哪个文件夹。

## 设置

在设置里搜 *ZettCode*：

| 设置 | 默认 | 含义 |
| --- | --- | --- |
| `zettcode.permission` | `ask` | 没有手动选过时，会话启动用的 shell 权限：`deny`、`ask`、`safe`（沙箱）或 `full` |
| `zettcode.harness` | `false` | 启动时就打开工具 harness：模型可以自己写小的 Python 工具并运行，不受 shell 权限管辖。`/harness on` 或 `/harness off` 在一个会话里切换 |
| `zettcode.restoreSession` | `true` | 重新打开这个文件夹上次的会话 |
| `zettcode.autoTitle` | `true` | 让模型在第一次回答后给没有标题的会话起名 |
| `zettcode.answerTimeout` | `90` | 审批等待的秒数 |
| `zettcode.historyLimit` | `50` | **Recent Sessions** 列出的历史会话条数 |
| `zettcode.server.command` | `zettcode-server` | 服务器在哪，如果不在 `PATH` 或文件夹 `.venv` 里 |
| `zettcode.server.args` | `[]` | 给它的额外参数 |
| `zettcode.server.port` | `0` | 固定端口；`0` 表示挑一个空闲的 |
| `zettcode.server.autoStart` | `true` | 随聊天启动服务器 |
| `zettcode.server.autoInstall` | `true` | 找不到服务器时装进扩展自己的环境 |
| `zettcode.server.externalUrl` | 空 | 用你自己启动的服务器，而不是另起一个 |
| `zettcode.server.externalToken` | 空 | 它需要的 token |
| `zettcode.server.useToken` | `true` | 扩展启动的服务器每个窗口用一个 token 保护 |

Skills、MCP 服务器和 `AGENTS.md` 在编辑器里和终端里完全一样：见 [Skills 与 MCP](/zh/guide/skills-and-mcp) 和
[项目指令](/zh/guide/instructions)。`<workspace>/.agents/skills`、`~/.agents/skills` 以及对应的 `mcp.json` 也会被
读取，所以为别的编码 agent 写的 skill 不用复制就能用。

## 出问题时

| 你看到的 | 怎么办 |
| --- | --- |
| 聊天说服务器没跑起来 | **ZettCode: Show Server Log** 里有原因；处理好之后用 **ZettCode: Restart Server** |
| 没有模型 | **ZettCode: Add Model**，或者把 `~/.zettcode/config.toml` 里的 `[[models]]` 条目抄过来 |
| 命令被拒绝 | shell 权限是 `deny`；在输入框下面选 `ask`、`safe` 或 `full` |
| 图提示画不出来 | 那段围栏不是合法的 Mermaid；代码就在块里，原因在第一行 |

## 只有终端才有

`/theme`、`/pet` 和整套全屏界面属于终端应用。编辑器有它自己的主题和快捷键。
