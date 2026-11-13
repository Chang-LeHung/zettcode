<p align="center">
  <img src="clients/vscode/media/logo.svg" width="120" alt="ZettCode 吉祥物：骑着剑飞过月亮的机器人" />
</p>
<h1 align="center">ZettCode</h1>
<p align="center"><strong>缺什么工具，就自己造什么工具的编码智能体。</strong></p>
<p align="center">即时（JIT）Harness：任务需要一个你没有的工具时，智能体当场写好、加载、运行——在沙箱子进程里，过程公开，由你掌控。</p>
<p align="center">
  <a href="README.md">English</a> · <strong>简体中文</strong><br />
  <a href="https://chang-lehung.github.io/zettcode/zh/guide/getting-started">快速开始</a> ·
  <a href="https://chang-lehung.github.io/zettcode/zh/">使用文档</a> ·
  <a href="https://chang-lehung.github.io/zettcode/zh/guide/commands">命令参考</a> ·
  <a href="https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode">VS Code 扩展</a>
</p>

<p align="center">
  <img src="docs/public/terminal.svg" width="1000" alt="ZettCode 依次展示任务、思考、读文件、改代码、通过的测试和 Markdown 回答" />
</p>
<p align="center"><sub>示例对话由 ZettCode 的实际终端组件渲染。</sub></p>

## JIT Harness

多数智能体只带一套固定工具，ZettCode 让模型自己长出工具。开启 harness 后，模型可以新建一个小型 Python 仓库，
写入工具，`repo_load` 之后在同一轮里直接调用：

1. **写**：工具就是普通 Python，放在 `~/.zettcode/harness/<工作区>/<会话>/`，由 `MANIFEST` 声明。
2. **载**：`repo_load` 在**子进程**中导入，崩溃或卡死不会拖垮你的会话。
3. **跑**：模型像调用其他工具一样调用它，每一步都是可展开查看的行。
4. **受限**：低于 `full` 权限时，它与 `safe` 使用同一个沙箱；`BAN_TOOLS` 文件可以禁止某些工具名。

```toml
# ~/.zettcode/config.toml
[harness]
jit = true
```

也可以用 `/harness gen` 只在这一次运行中试用。详见[配置参考](https://chang-lehung.github.io/zettcode/zh/guide/config)。

### 后台运行智能体，在群里和它们对话

智能体不必待在你的终端里。启动一个 **daemon**（后台会话），在网关网页里观察它：下图中它被要求造一个
`find_todos` 工具，写下 `kit/todos.py`、加载并在项目上运行，随后又回答了追问。

<p align="center">
  <img src="docs/public/demo/daemon.gif" width="800" alt="后台智能体构建、加载并运行 find_todos 工具，再回答追问" />
</p>

把会话和智能体（包括通过 `zettcode-code-agents` 插件接入的 Codex 与 Claude Code）拉进一个**群**，用 `@名字` 呼叫。
成员、邀请和在线状态都在同一个页面里。

<p align="center">
  <img src="docs/public/demo/group.gif" width="800" alt="新建群、@builder 智能体并读到它的回复" />
</p>

```bash
python -m zettcode daemon spawn --name builder --title "tool builder" --permission safe
```

## 先跑起来

需要 **Python 3.10+**、支持 UTF-8 的终端和 **OpenAI 兼容接口**（或 Anthropic 的 **Messages API**）。
支持 macOS、Linux 和 Windows（请使用 Windows Terminal）。

### 1. 安装

```bash
uv tool install zettcode
# 或者：pip install zettcode
```

### 2. 连接模型

创建 `~/.zettcode/config.toml`（以及父目录），先配置一个模型：

```toml
[[models]]
model = "deepseek-v4-pro"             # 发给 DeepSeek 的模型 id
display_model = "DeepSeek Pro"        # ZettCode 界面中显示的名字
token = "sk-..."                      # 替换成你的 DeepSeek API key
base_url = "https://api.deepseek.com"  # DeepSeek 的 OpenAI 兼容接口根地址
context_window = 1000000               # 以接入点当前公布的实际限制为准
multimodal = false                    # 这个模型接受文本，不接受图片
```

在 [DeepSeek 开放平台](https://platform.deepseek.com/)创建 API key，不是聊天网页的登录信息。
也可以省略 `token`，改用 `OPENAI_API_KEY` 环境变量保存这个 key。
添加更多 `[[models]]`，就能用 `/model` 切换；启动时默认选择第一项。
完整示例、默认值和排错步骤见[配置参考](https://chang-lehung.github.io/zettcode/zh/guide/config)。

### 3. 发出任务

```bash
cd /path/to/project
zettcode
# 或者：zettcode --workspace /path/to/project
```

描述要改什么，按 **Enter**。`/` 打开命令菜单，`@` 引用 skill，**Ctrl-C** 停止请求。
输入框为空时按 **Ctrl-D** 退出，终端会打印恢复当前会话的命令。

## 按你的方式工作

| | |
| --- | --- |
| **看清每一步** | 思考、回答和工具调用实时呈现为可读的行，不是原始 JSON。 |
| **决定权在你手上** | 执行 shell 命令前先审阅；智能体需要你的决定时，可以选选项，也可以打字回答。 |
| **工作不中断** | 回复过程中直接输入并选择：立刻引导，或排成可用 `Option`+`↑`/`↓` 调整顺序、可编辑可删除的后续消息；用 `/btw` 问一句，不让它进入后续上下文。 |
| **随时接着做** | `/resume` 恢复对话，`/export` 导出便于阅读的 HTML。 |
| **看懂上下文** | 查看 token 与缓存统计，用 `/context` 检查占用，在需要时压缩。 |
| **接入你的工具** | 使用项目 `AGENTS.md` 指令、skills、MCP 服务器和 Python 插件。 |

主题跟随终端背景，也可以使用你自己的 `theme.toml`。
选中复制文字、滚动查看回答；模型支持多模态时，还能粘贴图片。

## 找到你的下一步

**[用户指南](https://chang-lehung.github.io/zettcode/zh/guide/overview)** 提供简体中文与
[English](https://chang-lehung.github.io/zettcode/guide/overview) 两个版本。

| 第一次使用 | 日常使用 | 配置与扩展 |
| --- | --- | --- |
| [快速开始](https://chang-lehung.github.io/zettcode/zh/guide/getting-started) | [快捷键与鼠标](https://chang-lehung.github.io/zettcode/zh/guide/keys) | [配置参考](https://chang-lehung.github.io/zettcode/zh/guide/config) |
| [认识界面](https://chang-lehung.github.io/zettcode/zh/guide/interface) | [命令参考](https://chang-lehung.github.io/zettcode/zh/guide/commands) | [模型与上下文](https://chang-lehung.github.io/zettcode/zh/guide/models) |
| [常见问题](https://chang-lehung.github.io/zettcode/zh/guide/faq) | [会话管理](https://chang-lehung.github.io/zettcode/zh/guide/sessions) | [项目指令](https://chang-lehung.github.io/zettcode/zh/guide/instructions) |
| | | [Skills 与 MCP](https://chang-lehung.github.io/zettcode/zh/guide/skills-and-mcp) · [插件](https://chang-lehung.github.io/zettcode/zh/guide/plugins) |

嵌入到别处:[**SDK**](https://chang-lehung.github.io/zettcode/zh/sdk/) 用 Python 驱动代理,
[**服务器**](https://chang-lehung.github.io/zettcode/zh/server/) 把它放到 HTTP 后面 —— 运行中的 prompt 流式返回,
包含会话、审批、steer 和模型切换。

```bash
uv tool install zettcode          # 一次安装,两个命令:zettcode 和 zettcode-server
zettcode-server --workspace ~/projects/api --port 8000
```

VS Code 用户在扩展市场安装[扩展](https://marketplace.visualstudio.com/items?itemName=zettcode.zettcode),
它是在同一个服务器和客户端之上的侧边栏对话:流式回合、串联的工具调用、可点击的文件、审批、模型/effort/权限切换和
最近会话历史。源码在 [`clients/vscode/`](clients/vscode/README.md),`make vscode` 会构建并测试它;
指南里有[它的一页](https://chang-lehung.github.io/zettcode/zh/vscode/)。

## 开发

```bash
uv sync                          # 安装这个包
make check                      # Ruff、mypy、测试与 VS Code 扩展
make client                     # 构建并测试 TypeScript 客户端
make vscode                     # 类型检查、测试并构建 VS Code 扩展
make hooks                      # 每次提交前强制检查 mypy
make demo                       # 浏览终端组件
make docs                       # 本地预览使用文档
uv run zettcode --workspace .    # 从源码运行
```

ZettCode 提供终端应用和它的 HTTP 服务器;智能体运行时来自
[`zett-agent`](https://github.com/Chang-LeHung/zett-agent)。仓库是一个 uv workspace:`packages/` 下每个子系统一个发行包
—— 读者安装的那个程序、它依赖的 engine、控件框架、broker、SDK、server 与 gateway、终端应用,以及插件 API ——
它们共享同一个 `zettcode` 命名空间;插件(`/monitor`、`/recap`,用 `zettcode[all]` 安装)也在这里发布。
`clients/typescript/` 是服务器的 TypeScript 客户端,`clients/vscode/` 是基于该客户端的
VS Code 侧边栏。贡献者约定和不变量放在
[`AGENTS.md`](AGENTS.md) 与 [`docs/internal/`](docs/internal/)，不进入用户指南。
本地预览、重新生成效果图的方法见
[`docs/internal/site-design.md`](docs/internal/site-design.md)。

## 许可证

MIT，见 [`LICENSE`](LICENSE)。
