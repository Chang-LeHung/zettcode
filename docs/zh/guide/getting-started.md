# 快速开始

ZettCode 是一个终端程序：它读写一个**工作区**里的文件，在那里执行命令，并把对话画在你启动它
的那个屏幕上。请求需要的消息与工具结果会发给你配置的模型接口。Shell 命令会先请求审批；
文件编辑工具可能直接修改工作区，因此请使用版本控制，并在接受改动前检查 diff。

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
第一张表在启动时生效。先创建目录，再打开配置文件：

::: code-group

```bash [macOS / Linux]
mkdir -p ~/.zettcode
```

```powershell [Windows]
New-Item -ItemType Directory -Force "$HOME/.zettcode"
```

:::

我们用 **DeepSeek** 举例，它提供 OpenAI 兼容接口。
先在 [DeepSeek 开放平台](https://platform.deepseek.com/)创建 API key，
再把下面的内容保存到 `~/.zettcode/config.toml`。`sk-...` 是占位符，必须换成自己的 key。

```toml
# ~/.zettcode/config.toml
[[models]]
model = "deepseek-v4-pro"             # 发给 DeepSeek 的模型 id
display_model = "DeepSeek Pro"        # 可选：头部显示的名字
token = "sk-..."                      # 你的 DeepSeek API key
base_url = "https://api.deepseek.com"  # API 根地址，不是聊天网页
responses_api = false                 # 使用 Chat Completions 接口
context_window = 1000000               # token 数，以接口当前公布的限制为准
compact_percent = 80                  # 在上下文快满之前压缩
multimodal = false                    # DeepSeek Pro 不接受图片
```

这里先分清三个容易混淆的地方：

- `model` 是 API 识别的模型 id；`display_model` 只是界面上的标签。
- `base_url` 是 API 根地址，不能填 `https://chat.deepseek.com`，也不要在后面加
  `/chat/completions`。
- `multimodal = false` 表示这个模型不接受图片。要粘贴截图，需要另外配置支持图片的模型。

模型名称和能力会变化，示例依据 DeepSeek 的
[当前模型说明](https://api-docs.deepseek.com/quick_start/pricing)。如果通过第三方网关接入，
以网关提供的模型 id 和限制为准。

不想把 key 写进文件，可以删除 `token` 这一行，改用 `OPENAI_API_KEY` 环境变量。
即使是 DeepSeek 的 key，ZettCode 读取的变量名也仍然是 `OPENAI_API_KEY`。
具体命令见[用环境变量保存密钥](/zh/guide/config#keeping-the-key-out-of-the-file)。
[配置参考](/zh/guide/config)还会介绍多个模型和所有可选设置。
缺少设置或键名错误会在启动时报出对应项；TOML 语法错误会附上解析器提供的位置信息。

## 发出第一个任务

在你想要改动的目录里启动它：

```bash
cd ~/projects/api
zettcode
```

窗口会立刻出现 —— 设置和会话在 provider SDK 之前就准备好了 —— 状态行显示 `ready`。输入任务，
按 **Enter**：

> 给 GET /users 加上 limit/offset 分页，并补上测试

如果还不熟悉项目，可以先提出只读任务：

> 说明这个项目的入口在哪里，以及如何运行测试。先不要修改文件。

再给一个边界明确的改动：

> 为 users 返回空列表补一个测试，只修改 tests/test_users.py。

路径要换成项目中真实存在的文件。比起“优化一下项目”，明确改动范围和验证方式更容易审阅结果。

## 接下来会发生什么

1. 立刻出现一行 `Processing` 并带上已用时间，所以模型慢的时候不会被误认成卡死。它一直钉在对话
   区最下面：思考、工具调用、回答都出现在它上面。
2. 思考内容折叠在一行 `Thinking` 下面；工具调用读起来像日志 —— `Read src/app.py`、`Ran pwd`。
3. 模型要执行 shell 命令时，会先弹出一个面板：`y` 只跑这一次，`a` 放行本轮剩余命令，
   `p` 记住这条命令，`Esc` 拒绝。
4. 请求结束时（回答完、报错、或用 `Ctrl-C` 停掉），同一行变成灰色的收尾：
   `Processed for 12s · 09:41`。

它干活的时候你可以继续打字，这条消息会变成 **steering**（插话）：代理跑完手上那批工具后就会
读它。细节见[界面](/zh/guide/interface)。

## 离开与回来

在输入框为空时按 **Ctrl-D**（或 `/quit`）退出。退出时会打印恢复这个会话的命令，回来只需要
复制粘贴一次：

```
resume this session: zettcode --resume 01a10b75 --workspace ~/projects/api
```

## 检查结果

阅读回答，必要时展开工具输出。如果项目使用 Git，可以在另一个终端里检查改动：

```bash
git diff --stat
git diff
```

保留改动前，运行项目自己的测试。ZettCode 操作的是本地工作区，回答看起来正确不代表文件已经
验证过。如果第一条请求失败，按照[连接检查步骤](/zh/guide/config#checking-the-connection)排查。

接下来看[界面](/zh/guide/interface)，它会解释屏幕上每一行的含义；如果你更想先动手，直接看
[快捷键与鼠标](/zh/guide/keys)。
