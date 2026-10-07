# 配置参考

先配好一个能工作的模型，再按需要添加其他设置。ZettCode 启动时读取
`~/.zettcode/config.toml`，不需要把所有段落都写出来：省略的可选项会使用默认值。

这篇用 DeepSeek 举例。连接仍然走 **OpenAI 兼容 API**，不需要也不支持 `provider` 设置。

## 文件分别管什么，什么时候生效

| 文件 | 用途 | 修改后何时生效 |
| --- | --- | --- |
| `~/.zettcode/config.toml` | 模型连接和可选功能 | 重启 ZettCode。 |
| `~/.zettcode/theme.toml` | 自定义颜色 | 重启；运行中可用 `/theme` 选择内置主题。 |
| `~/.zettcode/mcp.json` | 外部工具服务器 | 修改服务器定义后重启。 |
| 工作区或上层目录的 `AGENTS.md` | 项目约定和测试命令 | 下一次请求重新读取。 |

`~` 表示用户主目录，Windows 上通常是 `C:\Users\<用户名>`。
工作区和配置文件是两个概念：用 `zettcode -w /path/to/project` 指定工作目录，
或者进入项目目录后直接运行 `zettcode`。

想试一份配置，又不改动平时使用的文件，可以这样启动：

::: code-group

```bash [macOS / Linux]
ZETTCODE_CONFIG="$HOME/.zettcode/deepseek.toml" zettcode -w /path/to/project
```

```powershell [Windows]
$env:ZETTCODE_CONFIG = "$HOME/.zettcode/deepseek.toml"
zettcode -w C:\projects\api
# 试用结束后移除覆盖设置。
Remove-Item Env:ZETTCODE_CONFIG
```

:::

这份文件会**替代**默认配置，不会和默认配置合并。命令行中的相对工作区路径，
以启动 ZettCode 时所在的目录为基准。

## 模型连接 {#models}

### 一份可以照着配置的 DeepSeek 示例

在 [DeepSeek 开放平台](https://platform.deepseek.com/)创建 API key。
如果没有 `~/.zettcode/` 目录，先创建它，再把下面的内容保存为 `config.toml`：

```toml
[[models]]
model = "deepseek-v4-pro"             # API 识别的模型 id，不是显示标签
display_model = "DeepSeek Pro"        # 头部和 /model 列表里显示的名字
token = "sk-..."                      # 替换成你的 DeepSeek API key
base_url = "https://api.deepseek.com"  # API 根地址，不是聊天网页
responses_api = false                 # 使用 Chat Completions，不走 /responses
multimodal = false                    # Pro 只接受文本
context_window = 1000000               # token 上限，以接口当前说明为准
compact_percent = 80                  # 达到窗口的 80% 时压缩
```

示例依据 DeepSeek 的[当前模型说明](https://api-docs.deepseek.com/quick_start/pricing)。
模型 id、窗口大小和图片能力会变化，第三方网关也可能给出不同限制。应以实际接入点公布的信息
为准，不能通过把 `context_window` 写大来让远端模型接受更多 token。

::: warning 不要泄露密钥
`sk-...` 是占位符。不要把真实 key 提交到 Git，也不要放进截图、导出的对话或问题反馈。
聊天产品的订阅或登录信息不等于 API key。macOS/Linux 上可以用
`chmod 600 ~/.zettcode/config.toml` 限制文件访问权限。
:::

### 每一个模型参数的含义

| 参数 | 类型 | 默认值 | 应该怎么填写 |
| --- | --- | --- | --- |
| `model` | 字符串 | 必填 | API 支持的精确模型 id，例如 `deepseek-v4-pro`，不能为空。 |
| `display_model` | 字符串 | 模型 id | 自己起的易读名称，例如 `DeepSeek Pro`。不会作为模型 id 发给 API。 |
| `token` | 字符串 | `OPENAI_API_KEY` | 这个接入点的 API key。文件中的非空值优先于环境变量。 |
| `base_url` | 字符串 | `https://api.openai.com/v1` | API 根地址。使用 DeepSeek 或其他非 OpenAI 接口时应显式填写。 |
| `responses_api` | 布尔值 | `false` | `false` 使用 Chat Completions；`true` 使用 Responses。选择接入点支持的协议。 |
| `multimodal` | 布尔值 | `false` | 只有模型和接口都支持图片输入时才开启。 |
| `context_window` | 整数 | `128000` | 正整数，表示上下文窗口的 token 数，不是字符数，也不是最大输出长度。 |
| `compact_percent` | 数值 | `80` | 自动压缩触发百分比，大于 `0` 且不超过 `100`。支持 `75.5` 这样的小数。 |

`base_url` 后面不要加 `/chat/completions` 或 `/responses`，客户端会自动加接口路径。
示例中的 DeepSeek 根地址不需要 `/v1`，但其他服务可能需要。按供应商示例填写 **API 根地址**，
不要根据聊天网页的 URL 猜。

`multimodal = false` 时，提交图片会在本地被拒绝并显示错误，模型也不会拿到 `view_image`
工具。把它改成 `true` 不会让纯文本模型获得视觉能力。
具体操作见[图片与粘贴](/zh/guide/interface#图片与粘贴)。

### 用环境变量保存密钥 {#keeping-the-key-out-of-the-file}

删除模型配置中的 `token` 这一行，再在准备启动程序的终端中设置 key：

::: code-group

```bash [macOS / Linux]
export OPENAI_API_KEY="your-deepseek-api-key"
zettcode
```

```powershell [Windows]
$env:OPENAI_API_KEY = "your-deepseek-api-key"
zettcode
```

:::

即使连接的是 DeepSeek，变量名也叫 `OPENAI_API_KEY`。ZettCode 不读取 `DEEPSEEK_API_KEY`，
也不会展开 TOML 字符串中的 `${VARIABLE}`。上面的设置只影响当前终端及其启动的进程，
不会自动影响之后打开的其他终端。这些命令也可能被 shell 历史记录保存，在共享机器上应使用
自己习惯的安全密钥管理方式。

多个模型都省略 `token` 时，会使用同一个环境变量。如果不同接入点使用不同 key，
应为每个模型分别填写 `token`，或者拆成不同配置文件。

### 配置多个模型

每一个 `[[models]]` 都开启一个新的模型配置，**不会继承上一项**的参数。
因此需要重复填写接入点、key 和限制：

```toml
[[models]]
model = "deepseek-v4-pro"
display_model = "DeepSeek Pro"
token = "sk-..."
base_url = "https://api.deepseek.com"
context_window = 1000000
compact_percent = 80
multimodal = false

[[models]]
model = "deepseek-flash"
display_model = "DeepSeek Flash"
token = "sk-..."
base_url = "https://api.deepseek.com"
context_window = 1000000
compact_percent = 80
multimodal = true
```

DeepSeek 当前的 Flash 模型接受图片，Pro 不接受。如果网关没有开放 Flash 的图片能力，
那一项也应该保持 `multimodal = false`。

启动时选择第一项。运行中输入 `/model` 从列表选择，或者直接输入 `/model DeepSeek Flash`。
切换只影响后续请求，不创建新会话，也不打断正在执行的请求。编辑文件后需要重启才能读到新增项。

### 压缩百分比应该怎么选

`context_window = 1000000`、`compact_percent = 80` 时，自动压缩触发线约为
**800,000 token**。改成 `60`，触发线约为 **600,000 token**。
调低可以为较长的工具结果和下一条回答留出余量，但也可能更早产生摘要，增加模型调用。
`100` 没有安全余量，通常更适合留出一些空间。

这是估算的触发线，不是保证请求永远不会超限：供应商的计数方式和突然返回的大段工具输出
都可能带来偏差。想提前整理上下文，可以直接运行 `/compact`。
压缩会保留哪些内容，见[模型与上下文](/zh/guide/models)。

## 可选功能

### 把默认值写全的一份完整配置

这是一份**完整文件**，不是直接追加到现有模型后面的片段。替换 key 后，可以删除不需要的
可选段落。下面所有可选功能的值都是默认值。

```toml
[[models]]
model = "deepseek-v4-pro"
display_model = "DeepSeek Pro"
token = "sk-..."
base_url = "https://api.deepseek.com"
responses_api = false
multimodal = false
context_window = 1000000
compact_percent = 80

[transcript]
max_entries = 1024             # 显示的对话块数量，不是终端行数

[agents_md]
enabled = true                 # 使用项目指令

[ask_user]
enabled = true                 # 允许模型询问用户

[skills]
enabled = true
roots = []                     # 在 ~/.zettcode/skills 之前搜索的额外目录

[mcp]
enabled = true
config = "~/.zettcode/mcp.json" # 服务器定义文件，不是本 TOML 文件

[plugins]
enabled = true                 # 加载已安装的第三方插件
disable = []                   # 要跳过的 entry-point 名称

[update]
enabled = true                 # 后台检查 PyPI 新版本
```

这些顶层段落应该像示例一样放在模型表之外。TOML 的键属于最近的表头：如果直接在
`[[models]]` 下写 `enabled`，它会被当作不支持的模型参数，而不是功能开关。

### 可选参数参考

| 段落 / 参数 | 默认值 | 效果与限制 |
| --- | --- | --- |
| `transcript.max_entries` | `1024` | 正整数。限制可回看的对话块，旧块移出界面，但不会删除持久化历史或模型上下文。 |
| `agents_md.enabled` | `true` | 读取工作区及其上层目录的 `AGENTS.md`，见[项目指令](/zh/guide/instructions)。 |
| `ask_user.enabled` | `true` | 允许单选、多选和自由输入的提问面板。`false` 移除这个工具，不代表禁止模型在普通回答里提出问题。 |
| `skills.enabled` | `true` | 发现 skill 名称和描述，并允许按需加载正文。 |
| `skills.roots` | `[]` | 目录字符串数组。按顺序搜索，再搜索 `~/.zettcode/skills`；同名 skill 取最先找到的。 |
| `mcp.enabled` | `true` | 有服务器配置时启用 MCP 工具；默认文件不存在时不加载服务器。 |
| `mcp.config` | `~/.zettcode/mcp.json` | JSON 服务器配置路径。建议用绝对路径或 `~`，避免位置不明确。 |
| `plugins.enabled` | `true` | 加载已安装的第三方插件；关闭后内置 UI 功能仍可使用。 |
| `plugins.disable` | `[]` | 要跳过的插件 **entry-point 名称**数组，不一定等于 pip 包名。 |
| `update.enabled` | `true` | 后台检查 PyPI，并在之后启动时提示新版本，不会自动安装。 |

例如，减少回看内容、添加项目内 skills，再关闭远程工具服务器：

```toml
[transcript]
max_entries = 256

[skills]
roots = [".zettcode/skills", "~/team-skills"]

[mcp]
enabled = false
```

把这个片段合入现有文件时，应修改已有的对应段落，不要重复定义同一张表。
相对 skill 路径以**工作区**为基准：`zettcode -w ~/projects/api` 中的 `.zettcode/skills`
指向 `~/projects/api/.zettcode/skills`。

## 颜色

没有主题文件时，ZettCode 会尝试检测终端背景，选择匹配的深色或浅色主题。两个内置主题
都使用终端本身的页面背景。`/theme dark` 或 `/theme light` 只切换本次运行，不修改文件。

需要持久化自定义配色时，创建 `~/.zettcode/theme.toml`。
这是**另一个文件**，不要把下面的段落放进 `config.toml`：

```toml
base = "dark"                  # dark 或 light，默认 dark

[ui]
accent = "#a7c080"
accent_bright = "#83c092"
surface_side = "#393a44"       # /btw 消息背景
# background = "#232a2e"      # 保持注释，继续使用终端背景

[tools]
read = "#b8a6e0"
shell = "#7fbbb3"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"            # Markdown `行内代码`
```

只覆盖写出的颜色，其余来自 `base`。主题文件优先于自动深浅色检测；运行中仍然可以用
`/theme` 选择内置主题，但不会改写自定义文件。

| 段落 | 颜色参数 |
| --- | --- |
| `ui` | `background`, `surface`, `surface_alt`, `surface_side`, `text`, `muted`, `subtle`, `accent`, `accent_bright`, `warning`, `error`, `border`, `focus`, `selection` |
| `tools` | `read`, `search`, `image`, `write`, `delete`, `shell`, `plan`, `subagent` |
| `code` | `inline`, `text`, `keyword`, `string`, `comment`, `number`, `function`, `builtin`, `operator`, `punctuator` |

颜色使用带引号的六位十六进制，例如 `"#83c092"`。不能填 `"green"`、三位十六进制，
也不能用 TOML 字符串 `"None"` 表示透明；省略 `background` 就会保留终端背景。
修改背景色后，同时检查正文和提示文字是否还有足够对比度。

## 环境变量

| 变量 | 效果 |
| --- | --- |
| `ZETTCODE_CONFIG` | 选择另一份完整配置文件。 |
| `OPENAI_API_KEY` | 模型没有非空 `token` 时使用的 key。 |
| `ZETTCODE_REDUCED_MOTION` | 设置为 `1`，抑制装饰性的扫光动画。 |
| `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY` | 模型 HTTP 客户端使用的标准代理设置。 |

会话固定保存在 `~/.zettcode/sessions`，按工作区分组。
不要往配置文件加 `store`、`session`、`provider`、`theme` 或 `reasoning_effort`，这些都不是
支持的键。恢复会话用 `-r` 或 `/resume`，推理程度用 `/effort`，颜色用 `theme.toml`。

## 检查连接 {#checking-the-connection}

启动校验只检查键名、类型和必填值，**不会请求 API** 来验证 key 或模型 id。
模型连接在首次使用时创建，因此 `zettcode --dry-run` 不是 API 连通性检查。

如果第一条消息失败，按这个顺序排查：

1. 确认选中的 `model` 是接入点实际提供的 id。
2. 对照供应商示例检查 `base_url`，包括是否需要 `/v1`。
3. 确认 key 属于这个接入点，账号有 API 权限和余额。
4. 确认请求协议和图片支持与接入点一致。

想绕过 TUI 单独测试 DeepSeek，先按上面的例子设置 `OPENAI_API_KEY`，再运行：

::: code-group

```bash [macOS / Linux]
curl https://api.deepseek.com/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"Reply with OK."}]}'
```

```powershell [Windows]
$headers = @{ Authorization = "Bearer $env:OPENAI_API_KEY" }
$body = @{
    model = "deepseek-v4-pro"
    messages = @(@{ role = "user"; content = "Reply with OK." })
} | ConvertTo-Json -Depth 5
Invoke-RestMethod -Uri "https://api.deepseek.com/chat/completions" `
    -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

:::

这会发送一个小型的计费 API 请求。反馈问题时不要贴出授权请求头或包含密钥的 shell 历史。

## 常见配置错误

| 现象 | 检查什么 |
| --- | --- |
| `No models configured` | 创建实际选中的配置文件，并添加至少一项 `[[models]]`。 |
| `Missing token for model ...` | 填写 `token` 或在启动终端中设置 `OPENAI_API_KEY`。占位符是非空字符串，通常要到 API 调用时才会报错。 |
| `Unknown config keys ...` | 只使用本页列出的键，例如 `model_name` 应该改成 `model`。 |
| `must be bool` / `must be int` | 用 `true` 而不是 `"true"`；用 `1000000` 而不是 `"1000000"`。 |
| `Invalid config file ...` | 检查引号、表头和重复键。TOML 语法错误会包含解析器的位置信息。 |
| API 拒绝模型或协议 | 检查模型 id 和 `responses_api`，显示标签不是 API id。 |
| 图片输入被拒绝 | 选择支持图片的模型，并且只为对应项启用 `multimodal`。 |

修改 `config.toml` 后重启。如果是会话、显示或 MCP 问题，继续看[常见问题](/zh/guide/faq)。
