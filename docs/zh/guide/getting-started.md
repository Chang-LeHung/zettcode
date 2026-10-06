# 快速开始

ZettCode 是一个终端程序：它读写一个**工作区**里的文件，在那里执行命令，并把对话画在你启动它
的那个屏幕上。除了发出请求所需的内容，什么都不上传；没有你的同意，它不会改你的项目。

## 环境要求

- Python 3.10 或更新版本，macOS / Linux / Windows 都可以。
- 支持 UTF-8、至少 256 色的终端。Windows 上请用 Windows Terminal，老的 console host 不够用。
- 一个 OpenAI 兼容的接入点（云上的 API 或本地起的服务）以及它的 token。

## 安装

::: code-group

```bash [uv]
uv tool install zettcode
```

```bash [pip]
pip install zettcode
```

:::

两种方式都会得到 `zettcode` 命令。`zettcode --help` 会列出命令行参数，我们刻意让它们保持很少：

| 参数 | 作用 |
| --- | --- |
| `-w`、`--workspace DIR` | 工作的目录，默认是当前目录。 |
| `-r`、`--resume SESSION` | 打开一个已保存的会话，而不是新建一个。 |
| `--dry-run` | 跑完启动流程、画一帧就退出，用来做性能分析。 |

如果你想从源码跑：

```bash
uv sync
uv run zettcode -w /path/to/project
```

## 先配一个模型

除了工作区，其他设置都在 `~/.zettcode/config.toml` 里。唯一必须有的是一组模型 —— 每个一张表，
第一张表在启动时生效：

```toml
# ~/.zettcode/config.toml
[[models]]
model = "gpt-4o"                       # 发给接入点的模型 id
display_model = "GPT-4o"               # 可选：头部显示的名字
token = "sk-..."                       # 也可以改用 OPENAI_API_KEY
base_url = "http://localhost:8787/v1"  # OpenAI 兼容的 API 根地址
context_window = 200000                # 这个模型能装多少 token
multimodal = true                      # 除文本外还接受图片
```

完整的键位说明、以及文件里其他段落，见[配置文件](/zh/guide/config)。文件缺失或写错时会在启动
时指出具体哪一行有问题，而不是被默默忽略。

## 发出第一个任务

在你想要改动的目录里启动它：

```bash
cd ~/projects/api
zettcode
```

窗口会立刻出现 —— 设置和会话在 provider SDK 之前就准备好了 —— 状态行显示 `ready`。输入任务，
按 **Enter**：

> 给 GET /users 加上 limit/offset 分页，并补上测试

## 接下来会发生什么

1. 立刻出现一行 `Processing` 并带上已用时间，所以模型慢的时候不会被误认成卡死。
2. 思考内容折叠在一行 `Thinking` 下面；回答和工具调用按顺序出现在它下面。
3. 模型要执行 shell 命令时，会先弹出一个面板：`y` 只跑这一次，`a` 放行本轮剩余命令，
   `p` 记住这条命令，`Esc` 拒绝。
4. 一轮结束时，会有一行灰色的收尾：`Processed for 12s · 09:41`。

它干活的时候你可以继续打字，这条消息会变成 **steering**（插话）：代理跑完手上那批工具后就会
读它。细节见[界面](/zh/guide/interface)。

## 离开与回来

在输入框为空时按 **Ctrl-D**（或 `/quit`）退出。退出时会打印恢复这个会话的命令，回来只需要
复制粘贴一次：

```
resume this session: zettcode --resume 01a10b75 --workspace ~/projects/api
```

接下来看[界面](/zh/guide/interface)，它会解释屏幕上每一行的含义；如果你更想先动手，直接看
[快捷键与鼠标](/zh/guide/keys)。
