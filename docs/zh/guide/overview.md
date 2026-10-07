# 找到你的下一步

ZettCode 在终端里工作，操作当前工作区中的文件。这份指南按你要做的事组织：开始第一个任务、
顺畅地继续一段对话，或配置适合项目的模型与工具。

## 第一次使用？

1. **[安装并连接模型](/zh/guide/getting-started)。** 需要 Python 3.10+、一个终端和
   OpenAI 兼容接口。快速开始带你从安装走到第一个任务。
2. **[认识界面](/zh/guide/interface)。** 看懂思考、工具输出、输入框和状态行。
3. **[记住常用操作](/zh/guide/keys)。** Enter 发送，Ctrl-C 停止请求，输入框为空时
   Ctrl-D 退出。

## 在项目里工作

| 我想…… | 去哪里看 |
| --- | --- |
| 切换模型、调整推理程度、问一个旁路问题 | [命令参考](/zh/guide/commands) |
| 选中文字、粘贴图片、翻回之前的回答 | [快捷键与鼠标](/zh/guide/keys) |
| 继续之前的会话、导出 HTML | [会话管理](/zh/guide/sessions) |
| 了解上下文占用、压缩与缓存 | [模型与上下文](/zh/guide/models) |

智能体工作时继续输入，会发送一条 **steering（引导）消息**，在下一个工具或模型边界采用。
如果你只想顺便问一句，不让答案进入后续请求的上下文，使用 `/btw <问题>`。
两者的用法都在[界面说明](/zh/guide/interface)中。

## 按你的方式配置

- **[配置参考](/zh/guide/config)：** 模型连接、可选能力与主题。想改设置，先看这里。
- **[项目指令](/zh/guide/instructions)：** 用 `AGENTS.md` 说明工作区的约定、测试命令和边界。
- **[Skills 与 MCP](/zh/guide/skills-and-mcp)：** 给智能体可复用的指令，或接入外部工具。
- **[插件](/zh/guide/plugins)：** 安装 Python 扩展，增加命令、定制界面。

## 遇到问题？

先看[常见问题](/zh/guide/faq)。如果能复现一个 bug，在
[GitHub 提交 issue](https://github.com/Chang-LeHung/zettcode/issues)。说明操作系统、终端、
ZettCode 版本和复现步骤；不要附上 API token 或私有会话内容。
