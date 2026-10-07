# 配置文件

除了工作区，其他设置都在一个文件里：`~/.zettcode/config.toml`。未知的键和错误的类型会在启动时
带着出错的键一起报出来（`zettcode: Config key 'models[2] key 'model'' must be str`），而不是
被忽略。

```bash
ZETTCODE_CONFIG=/path/to/other.toml zettcode   # 换一个配置文件
```

## 模型

至少要有一张 `[[models]]` 表；第一张在启动时生效，`/model` 用来切换后续请求使用的模型。

```toml
[[models]]
model = "gpt-4o"                       # 必填：发给接入点的模型 id
token = "sk-..."                       # 必填：也可以设置 OPENAI_API_KEY
display_model = "GPT-4o"               # 可选：头部显示的名字
base_url = "http://localhost:8787/v1"  # 可选：OpenAI 兼容的 API 根地址
responses_api = false                  # 改用 Responses API
multimodal = true                      # 除文本外还接受图片
context_window = 200000                # 这个模型能装多少 token
compact_percent = 80                   # 请求占到窗口这个比例时压缩
```

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `model` | — | 必填，空白会被拒绝。 |
| `token` | `$OPENAI_API_KEY` | 最终必须有：来自这里或环境变量。 |
| `display_model` | 等于模型 id | 头部和选择面板里显示的名字。 |
| `base_url` | 客户端默认值 | 任何 OpenAI 兼容的网关。 |
| `responses_api` | `false` | 接入点说 `/responses` 时打开。 |
| `multimodal` | `false` | 关闭时，附图片会被拒绝，而不是发出去。 |
| `context_window` | `128000` | `/context` 用它做分母。 |
| `compact_percent` | `80` | 触发压缩的窗口占用比例。 |

`context_window` 和 `compact_percent` 值得填成真实值：能装 200k 却按 128k 配的模型会更早压缩，
而配得比实际大的模型会在接入点那里失败。详见[模型与上下文](/zh/guide/models)。

## 文件的其他段落

```toml
[transcript]
max_entries = 1024             # 屏幕上保留的对话行数

[agents_md]
enabled = true                 # 从工作区向上读取 AGENTS.md

[ask_user]
enabled = true                 # 允许模型在一轮中向你提问

[skills]
enabled = true
roots = ["~/team-skills"]      # 先于 ~/.zettcode/skills 搜索

[mcp]
enabled = true
config = "~/.zettcode/mcp.json"

[plugins]
enabled = true
disable = ["greeter"]          # 不加载的 entry point 名

[update]
enabled = true                 # 后台检查是否有新版本
```

| 段落 | 键 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `transcript` | `max_entries` | `1024` | 只限制屏幕上的回看深度，会话文件保留全部内容。 |
| `agents_md` | `enabled` | `true` | 见[项目指令](/zh/guide/instructions)。 |
| `ask_user` | `enabled` | `true` | 给模型 `ask_user` 工具，让它能暂停当前轮向你提问。 |
| `skills` | `enabled` | `true` | 见[Skills 与 MCP](/zh/guide/skills-and-mcp)。 |
| `skills` | `roots` | `[]` | 相对路径按工作区解析。 |
| `mcp` | `enabled` | `true` | 见[Skills 与 MCP](/zh/guide/skills-and-mcp)。 |
| `mcp` | `config` | `~/.zettcode/mcp.json` | 描述服务器的 JSON 文件。 |
| `plugins` | `enabled` | `true` | 见[插件](/zh/guide/plugins)。 |
| `plugins` | `disable` | `[]` | 不卸载也能关掉某个插件。 |
| `update` | `enabled` | `true` | 在后台向 PyPI 查询新版本，并在之后启动时提示。 |

会话存储刻意**不**做成可配置的：会话属于写下它的那个工作区，`~/.zettcode/sessions` 是所有
工作区共同查找的地方。

## 配色

配色单独放在 `~/.zettcode/theme.toml`，因为它是个人的、而不是按项目的。建了这个文件，外壳就
不再猜；所有键都是可选的，只有你写的那些会改变。

```toml
base = "dark"                  # dark | light —— 从哪套配色出发

[ui]
accent = "#a7c080"
accent_bright = "#83c092"
background = "#232a2e"         # 不写就用终端自己的背景色
surface_side = "#393a44"       # `/btw` 那一行的底色：它不是一轮对话

[tools]                        # 所有角色默认同一种紫色
read = "#b8a6e0"
shell = "#7fbbb3"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"
```

启动时，外壳只问终端一个问题 —— 你的背景色是什么？ —— 然后据此选深色或浅色配色。有了主题
文件就不再问：挑颜色是一个决定，文件怎么写就怎么用。`/theme` 在任何情况下都能临时覆盖，
直到本次运行结束。

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `ZETTCODE_CONFIG` | 使用另一个配置文件。 |
| `OPENAI_API_KEY` | 给没写 token 的模型提供凭据。 |
| `ZETTCODE_REDUCED_MOTION` | 关掉装饰性动画。 |
| `NO_COLOR`、`TERM`、`COLORTERM` | 常见的终端提示，用于判断颜色深度。 |

## ZettCode 会写哪些文件

| 路径 | 是什么 |
| --- | --- |
| `~/.zettcode/config.toml` | 就是本页这个文件。 |
| `~/.zettcode/theme.toml` | 可选的配色文件，存在才读。 |
| `~/.zettcode/sessions/` | 会话及其索引。 |
| `~/.zettcode/log/tui.log` | 界面占用屏幕期间，任何写到 stderr 的内容。 |
| `~/.zettcode/skills/` | skills，一个目录一个。 |
| `~/.zettcode/mcp.json` | MCP 服务器（除非你指向别处）。 |
| `~/.zettcode/update.json` | 版本检查的结果，以及你选择跳过的版本。 |

那个日志文件存在的原因是：子进程（比如一个自报家门的 MCP 服务器）不可能知道屏幕已经被占用，
直接画上去会把画面弄坏，所以它的输出进文件。
