# ZettCode

[English](README.md) · **简体中文**

一个专注的终端编码智能体。指向一个工作区，说清楚要改什么，然后看着它把活干出来 —— 读文件、
等你批准命令、改代码、跑测试 —— 整个过程是一段可以滚动、选中、复制的对话。

终端界面就是本仓库；模型循环在
[`zett-agent`](https://github.com/Chang-LeHung/zett-agent)，单独发布。

## 安装

需要 Python 3.10 或更新版本，PyPI 包名是 `zettcode`：

```bash
uv tool install zettcode
# 或者
pip install zettcode
```

## 配置

除了工作区，其他设置都在 `~/.zettcode/config.toml`。至少要有一个模型，第一张表在启动时生效：

```toml
[[models]]
model = "gpt-4o"
token = "sk-..."                       # 也可以设置 OPENAI_API_KEY
base_url = "http://localhost:8787/v1"  # 任何 OpenAI 兼容的接入点
context_window = 200000                # 这个模型能装多少 token
multimodal = true                      # 除文本外还接受图片
```

项目里的 `AGENTS.md`、[skills](https://chang-lehung.github.io/zettcode/zh/guide/skills-and-mcp)、
MCP 服务器、插件、配色等等都在同一个文件里，完整的键见
[配置文件](https://chang-lehung.github.io/zettcode/zh/guide/config)。

## 运行

```bash
cd ~/projects/api
zettcode                                    # 工作区默认是当前目录
zettcode -w /path/to/project                # 在别处工作
zettcode --resume <session-id>              # 重新打开一个已保存的会话
zettcode --dry-run                          # 只测启动耗时后退出
```

输入任务并按 **Enter**。`/` 打开命令菜单，`@` 引用 skill，`Ctrl-C` 停止请求，输入框为空时
`Ctrl-D` 退出 —— 退出时会打印把会话找回来的命令。

## 它能做什么

- **流式地呈现对话，而不是丢一堆数据。** 思考、回答、工具调用按顺序各占一行；工具输出读起来像
  日志 —— `Read src/app.py`、`Ran pytest -q` —— 永远不会甩出原始 JSON。
- **动手之前先问你。** 每条 shell 命令都要先确认，`a` 放行本轮剩余命令，`p` 记住某一条；
  当模型需要它猜不出的决定时，会弹面板向你提问并等待 —— 既能选选项，也能用自己的话回答。
- **把上下文讲清楚。** 状态行显示 token、缓存命中率和窗口占用；`/context` 拆开当前请求，
  压缩会在窗口溢出之前完成。
- **记住项目。** 从工作区逐级向上的 `AGENTS.md` 会变成项目指令；skills 和 MCP 服务器扩展模型
  能做的事。
- **尊重终端。** 鼠标选中与滚动、用面板做选择、粘贴图片、`Ctrl-L`，以及跟随终端背景的配色 ——
  也可以用你自己的 `theme.toml`。

## 文档

用户指南发布在 **<https://chang-lehung.github.io/zettcode/zh/>**（
[English](https://chang-lehung.github.io/zettcode/) 与之并列）：

| | |
| --- | --- |
| [快速开始](https://chang-lehung.github.io/zettcode/zh/guide/getting-started) | 安装、第一个任务、第一次审批。 |
| [界面](https://chang-lehung.github.io/zettcode/zh/guide/interface) | 屏幕上每一行在说什么。 |
| [快捷键与鼠标](https://chang-lehung.github.io/zettcode/zh/guide/keys) | 完整对照表。 |
| [命令](https://chang-lehung.github.io/zettcode/zh/guide/commands) | 所有 `/命令` 与 `@资源`。 |
| [会话](https://chang-lehung.github.io/zettcode/zh/guide/sessions) | 恢复、命名、导出。 |
| [配置文件](https://chang-lehung.github.io/zettcode/zh/guide/config) | 一个文件，所有键。 |
| [模型与上下文](https://chang-lehung.github.io/zettcode/zh/guide/models) | 推理档位、压缩、缓存、图片。 |
| [项目指令](https://chang-lehung.github.io/zettcode/zh/guide/instructions) | 怎么写出好用的 `AGENTS.md`。 |
| [Skills 与 MCP](https://chang-lehung.github.io/zettcode/zh/guide/skills-and-mcp) | 接入你自己的工具。 |
| [插件](https://chang-lehung.github.io/zettcode/zh/guide/plugins) | 用 Python 添加命令和界面行。 |
| [常见问题](https://chang-lehung.github.io/zettcode/zh/guide/faq) | 出问题的时候。 |

## 开发

```bash
uv sync                       # 安装环境
make check                    # ruff、mypy、pytest
make hooks                    # 每次提交前跑 mypy
make demo                     # 交互式浏览所有组件
uv run zettcode -w .          # 用源码运行
```

仓库内部的约定 —— 分层、不变量清单、平台适配 —— 见 [`AGENTS.md`](AGENTS.md) 和
[`docs/internal/`](docs/internal/)。文档站在 `docs/`，构建命令是
`npm ci --prefix docs && npm run docs:build --prefix docs`。

## 许可证

MIT，见 [`LICENSE`](LICENSE)。
