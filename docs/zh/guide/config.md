# 配置参考

先配好一个能工作的模型，再按需要添加其他设置。ZettCode 启动时读取
`~/.zettcode/config.toml`，不需要把所有段落都写出来：省略的可选项会使用默认值。

这篇用 DeepSeek 举例。默认走 **OpenAI 兼容 API**；如果某一项写了 `anthropic = true`，
它就走 Anthropic 的 **Messages API**。两种情况下都不需要也不支持 `provider` 设置。

## 文件分别管什么，什么时候生效

| 文件 | 用途 | 修改后何时生效 |
| --- | --- | --- |
| `~/.zettcode/config.toml` | 模型连接和可选功能 | 重启 ZettCode。 |
| `~/.zettcode/theme.toml` | 一组自定义颜色，叠在当前主题之上 | 重启；运行中可用 `/theme` 选择主题。 |
| `~/.zettcode/themes/<name>.toml` | 你自己的主题，按名字选用 | 下次使用 `/theme` 时就能看到。 |
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

### 用 /config 添加模型 {#adding-models-with-config}

添加模型不必改文件。`/config` 会在对话上方打开一个面板：

```text
Models
~/.zettcode/config.toml
 ▸ 1. DeepSeek Pro (current)   deepseek-v4-pro · chat · https://api.deepseek.com
   2. DeepSeek Flash           deepseek-flash · chat · https://api.deepseek.com
   + Add a model               from a provider, or any endpoint
```

**Add a model** 先问你选哪个 provider，再只问这个 provider 没有说明的部分。provider 是已知的服务商
—— 地址和 API 已经填好，你只需要给出**模型 id** 和 **token**：

| Provider | API | 地址 |
| --- | --- | --- |
| `openai` | chat completions | `https://api.openai.com/v1` |
| `anthropic` | Messages API | `https://api.anthropic.com` |
| `deepseek` | chat completions | `https://api.deepseek.com` |
| `openrouter` | chat completions | `https://openrouter.ai/api/v1` |
| `groq` | chat completions | `https://api.groq.com/openai/v1` |
| `ollama` | chat completions | `http://localhost:11434/v1` |
| `custom` | **你选择** | **你填写** |

`custom` 是任何其他端点。它先在单独的列表里问它用哪种 **API**（`chat` 是 chat completions，`responses` 是
Responses API，`anthropic` 是 Messages API），然后显示下面的表单。Anthropic API 的端点没有地址这一行：
SDK 自带一个。插件可以往这个列表里添加 provider，见[插件](/zh/guide/plugins#providers)。

添加一个 provider 用的是**一个表单**，而不是一个一个地问：

```text
Add a model at DeepSeek

╭─ Model id * ────────────────────────────────────────╮
│ deepseek-chat                                  │
╰────────────────────────────────────────────────╯
╭─ Token ──────────────────────────────────────────╮
│ ••••••••••••••                                 │
╰────────────────────────────────────────────────╯
   … Address、Shown name 和 Temperature，各自一个方框
```

每一行都是一个**方框**，标签在上边框上，光标所在的那个框会变成亮绿色，一眼就能看出这是要输入的地方；点击方框的任何位置（包括边框）都会把光标放到那里。
表单大约需要 20 行；终端不够高时，每一行改成占一行、文字带底色，用法不变。

**Tab**（或 **↓**）移到下一行，**Shift-Tab**（或 **↑**）回到上一行，到尽头会绕回来；**Enter** 一次保存全部；表单下面的提示会解释光标所在的那一行。只有**模型 id** 是必填的
（`custom` 还要地址）。**token 可以留空**：本地服务器（Ollama、LM Studio、vLLM）不需要，环境里有 `OPENAI_API_KEY` 时就用它。
保存不了的那一行——比如不是 http 或 https 的地址、超出范围的温度——会在表单上方点名，光标跳到那一行，你输入过的内容都不会丢。

token 输入时显示为圆点，之后也不会再显示 —— 面板里没有，`/config list` 里没有，提示“已添加”的那一行
里也没有。**Escape 是退回上一步**：从表单退到 provider 列表（`custom` 退到 API 列表），从列表退到模型列表，只有在模型列表按 Escape 才会关闭。
在表单里按 Enter 之前什么都不会写入，所以退回去不会有任何损失。

在面板里选中一个模型，它的所有设置都在同一页上，左边是条目，右边是值：

```text
GPT-4o

› Token           unchanged
  API             ◉ chat   ○ responses   ○ anthropic
  Address         https://proxy.example.com/v1
  Model id *      gpt-4o
  Shown name      GPT-4o
  Images          ●───────── text only
  Web search      ━━━━━━━━━● on
  Search tool     the default: web_search
  Temperature     the provider's default
  Context window  128,000 tokens
  Compress at     80 (% of the window)

  Use this model  save any change, then switch to it now
  Remove          delete it from the file
```

要输入的条目是一行输入框；**Images** 和 **Web search** 是和 [`/statusline`](/zh/guide/commands) 里一样的滑动开关
（**←** / **→** 或 **空格** 切换）；**API** 是在 `chat`、`responses`、`anthropic` 里选一个，选中的会被标出（**←** / **→** 移动）。
**↑** / **↓**（或 **Tab**）在各行之间移动，到头会绕回来，鼠标点一行就把光标放进去。页面下方有一行说明解释当前所在的这一行。

**Enter 一次保存所有行**并关闭页面；**Escape** 关闭页面且什么都不写。只写入你改过的内容——没动过的行保持文件里原来的写法——
某一行留空会删掉对应的键，于是用默认值。**Token** 一行一开始是空的，因为当前的 token 永远不会显示：留空就是保留它。
保存不了的那一行（不是 http 或 https 的地址、小于 1,000 的窗口、在 DeepSeek 的 chat 接入点上开启联网搜索）会在标题下点名，
光标跳到那一行，你输入的内容都还在。

底部两行是要做的事：**Use this model** 先保存你改的内容再切换到这个模型，**Remove** 删除它（删除前会先确认，
Enter 默认的答案是 *Keep it*）。屏幕太矮放不下所有行时，页面会滚动，让光标所在的行始终可见。

有些行是关于模型能装多少的，改完立刻在当前会话里生效：

| 行 | 设置什么 | 怎么写 |
| --- | --- | --- |
| **Images** | 模型是否接受图片（`multimodal`）。关闭时，图片会在本地被拒绝，模型改用只返回文本的 `read_file` 读文件，而不是 `read`。 | 一个开关，默认停在当前答案上。 |
| **Web search** | 供应商是否替模型联网搜索（`web_search`）；**Search tool** 是搜索以什么工具类型发送（`web_search_name`）。见[联网搜索](#web-search)。 | 一个开关，加一行输入框填类型；留空用该 API 的默认值。 |
| **Context window** | 模型能装多少 token（`context_window`），`/context` 就是对着它衡量的。 | `128000`、`128,000`、`128k`、`1m` 或 `1.5m`。小于 1,000 会被拒绝，因为那几乎一定是按“千”写的窗口 —— 请写 `200k`。留空用 128,000。 |
| **Compress at** | 对话占到窗口的多少时，在下一次请求前先做摘要（`compact_percent`）。 | 大于 0、不超过 100 的百分比：`80` 或 `80%`。留空用 80。 |

窗口和比例合起来决定什么时候压缩 —— 窗口 200k、比例 75% 就是 150,000 token —— 设置之后面板会告诉你算出来是多少。
*添加*模型时不会问这些（provider 并不知道），添加之后在这里设置，或者在命令行里加 `--context` 和 `--compact`。

同样的事也可以写成一行，只会询问这一行没有给出的部分：

```text
/config add deepseek --model deepseek-chat --token sk-...
/config add custom --api chat --url https://llm.example/v1 --model my-model --token sk-... --name "My model"
/config add anthropic --model claude-sonnet-4-5          # 打开表单填其余的
/config remove 3          # 也可以用名字：/config remove "My model"
/config add custom --api chat --url https://llm.example/v1 --model big --token sk-... --context 1m --compact 60
/config add custom --api chat --url https://llm.example/v1 --model big --token sk-... --context 1m --compact 60
/config list              # 模型、它们接受什么、在哪里压缩，不显示 token
/config providers         # `add` 接受哪些 provider
```

| 选项 | 含义 |
| --- | --- |
| `--model ID` | provider 称呼这个模型的 id。 |
| `--token KEY` | 凭据。不写的话，表单里有一行隐藏输入的 token，也可以留空。 |
| `--url URL` | 地址，替换 provider 自带的。`custom` 必须给（`--api anthropic` 除外）。 |
| `--api chat\|responses\|anthropic` | 用哪种 API。provider 有自己的默认值，这里可以覆盖，例如 `openai --api responses`。 |
| `--name SHOWN` | 在标题栏和 `/model` 里显示的名字（`display_model`）。 |
| `--multimodal` | 模型接受图片。 |
| `--context TOKENS` | 上下文窗口：`200000`、`200k`、`1m`。 |
| `--compact PERCENT` | 达到窗口的这个比例时做摘要：`75` 或 `75%`。 |
| `--temperature T` | 采样温度，0 到 2（`anthropic` 为 0 到 1）。 |
| `--web-search` | 让供应商替模型联网搜索；DeepSeek 在 API 不是 `anthropic` 时会被拒绝。 |
| `--search-tool TYPE` | 搜索以什么工具类型发送（隐含 `--web-search`）；省略则用该 API 的默认值。 |

::: tip token 优先用面板输入
你输入过的一行会留在输入框的内存历史里，按 `↑` 能再看到它，直到退出。不写 `--token`，在隐藏提示里输入
token 更稳妥。
:::

`/config` 对文件做了什么：

- 它**只改 `[[models]]` 条目**。你的注释、其它表和排版保持原样，并且在保存前会检查结果：如果结果不恰好
  是要的那些模型、或者会改动别的东西，就什么也不写。
- 添加的模型**立刻可用**，不用重启。添加不等于切换：正在用的模型不变。删除正在用的那个，会切到它相邻
  的一个并说明。
- 文件的权限保持不变。新建的文件只有你自己可读，因为里面有密钥。
- `/config` 每次都重新读文件，所以你启动之后手动加的模型也会显示在里面。
- 你编辑的那个模型**内部**的注释不会保留（它上面和其他地方的注释都保留）。
- 用别的写法写模型的文件 —— 比如内联的 `models = [ … ]` 数组 —— 会原样保留并提示你手动编辑；最后
  一个模型不能删除。

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
| `model` | 字符串 | 必填 | API 支持的精确模型 id，例如 `deepseek-v4-pro`，不能为空；这是模型唯一必须有的键。 |
| `display_model` | 字符串 | 模型 id | 自己起的易读名称，例如 `DeepSeek Pro`。不会作为模型 id 发给 API。它就是 `/model` 接受、会话记录的名字，所以**不能有两个条目用同一个名字显示** —— 也包括某个条目的 id 正好是另一个条目的名字。读取配置时发现重名会直接报错，并说出是哪个名字。 |
| `token` | 字符串 | `OPENAI_API_KEY`，否则没有 | 这个接入点的 API key。文件中的非空值优先于环境变量；`anthropic` 项读的是 `ANTHROPIC_API_KEY`。可以不写：本地服务器（Ollama、LM Studio、vLLM）不需要 key，这时不带 key 调用模型；需要 key 的服务器会回 `401`。 |
| `base_url` | 字符串 | 供应商给出的地址 | 客户端在这个地址后拼接口路径。使用 DeepSeek 或其他非 OpenAI 接口时应显式填写。默认是 `https://api.openai.com/v1`，`anthropic` 项则是 `https://api.anthropic.com`。 |
| `anthropic` | 布尔值 | `false` | `true` 表示调用 Anthropic 的 Messages API，而不是 OpenAI 兼容接口。不能与 `responses_api` 或 `chat` 同时开启。 |
| `responses_api` | 布尔值 | `false` | `false` 使用 Chat Completions；`true` 使用 Responses。选择接入点支持的协议。`anthropic` 项没有这个选项。 |
| `chat` | 布尔值 | `false` | `true` 明确写出接入点使用 Chat Completions，这也是两个选项都没设置时本来的含义，只是方便读这个文件的人。不能与 `anthropic` 或 `responses_api` 同时开启。 |
| `temperature` | 数字 | 提供商自己的默认值 | 随每个请求发送的采样温度，从 `0`（最确定）到 `2`；`anthropic` 项最大为 `1`。不写就不发送。有些推理模型会拒绝温度参数，只给接受它的模型设置。 |
| `multimodal` | 布尔值 | `false` | 只有模型和接口都支持图片输入时才开启。 |
| `web_search` | 布尔值 | `false` | 让供应商替这个模型联网搜索。搜索由端点执行，ZettCode 不抓取任何东西。DeepSeek 只在 `anthropic = true` 时接受。见[联网搜索](#web-search)。 |
| `web_search_name` | 字符串 | 该 API 的默认值 | 端点对这个搜索期望的确切工具类型，给命名不同的供应商用。省略则发送该 API 的默认值。 |
| `context_window` | 整数 | `128000` | 正整数，表示上下文窗口的 token 数，不是字符数，也不是最大输出长度。 |
| `compact_percent` | 数值 | `80` | 自动压缩触发百分比，大于 `0` 且不超过 `100`。支持 `75.5` 这样的小数。 |
| `reasoning_efforts` | 字符串数组 | 全部档位 | 这个模型支持的推理档位，取自 `off`、`minimal`、`low`、`medium`、`high`、`xhigh`、`max`、`ultra`。接入点会拒绝其余档位时才需要填写；见[模型支持的推理档位](#reasoning-levels-a-model-takes)。 |

`base_url` 是客户端拼接口路径的那个地址：`/chat/completions`、`/responses`，
`anthropic` 项则是 `/v1/messages`——路由本身不属于它。把路由一起写进来是很常见的误解，
所以末尾那段会被自动去掉：两种写法请求到的都是 `…/v1/messages`，只拼一次，不会变成两遍。
路由之前的路径原样保留，把 API 挂在某个前缀下的网关（例如 `https://gw.example/anthropic`）照常可用。
示例中的 DeepSeek 地址不需要 `/v1`，但其他服务可能需要。按供应商说的 **API 根地址**填，
不要根据聊天网页的 URL 猜。

`multimodal = false` 时，提交图片会在本地被拒绝并显示错误，模型会用只返回文本的 `read_file`
代替也能返回图片的 `read`。把它改成 `true` 不会让纯文本模型获得视觉能力。
具体操作见[图片与粘贴](/zh/guide/interface#图片与粘贴)。

### 联网搜索 {#web-search}

模型条目里写 `web_search = true`，供应商就会替它联网搜索。搜索是**托管**的：由端点执行，模型根据结果作答，
ZettCode 自己不抓取任何东西，也不需要搜索 key。不同 API 对这个工具的叫法不同，所以每种都有默认值，
条目可以用 `web_search_name` 覆盖：

| 条目使用的协议 | 默认发送的类型 |
| --- | --- |
| Chat Completions 或 Responses API | `web_search` |
| Anthropic Messages API（`anthropic = true`） | `web_search_20260318` |
| DeepSeek 的 Anthropic 兼容端点 | `web_search_20250305` |

```toml
[[models]]
model = "claude-sonnet-4-5"
anthropic = true
web_search = true

[[models]]
model = "deepseek-v4-flash"
base_url = "https://api.deepseek.com/anthropic"
anthropic = true
web_search = true
web_search_name = "web_search_20250305"   # 可选：这已经是它的默认值
```

**DeepSeek 只在它的 Anthropic 兼容端点上支持搜索。** DeepSeek 模型（id 或地址里带 deepseek）如果写了
`web_search = true` 却没有 `anthropic = true`，读文件时、用 `/config` 添加时、通过服务器 HTTP API 时都会被拒绝，
并说明原因。这个设置跟着当前使用的模型走，所以 `/model` 切换后下一次请求就生效。

网关可能提供它的厂商没有的搜索，所以其他组合不会被提前拒绝：如果端点不认识这个工具类型，请求会带着它自己的
错误失败，这时用 `web_search_name` 给它它认识的那个。

搜索是在端点自己的回复里完成的，有时会**没有结果就结束**——供应商在工具报回结果之前就关掉了这次回复，Anthropic
在搜索循环到达上限时就是这样。这种调用显示为 `The provider did not report what this call returned`，它那一行也不会
被标成完成：调用结束了，但没有结果，上面的回答就是模型自己写下的那些。这一行只属于正在运行的这一轮：供应商的
block 存不下来（下一次请求会因为一个没有结果的调用被拒），所以重新打开的会话只能看到回答本身。

### 模型支持的推理档位 {#reasoning-levels-a-model-takes}

并不是每个接入点都接受所有推理档位，不支持的档位可能让整个请求失败。可以在模型项里写明它支持哪些：

```toml
[[models]]
model = "deepseek-v4-pro"
token = "sk-..."
base_url = "https://api.deepseek.com"
context_window = 1000000
compact_percent = 80
reasoning_efforts = ["low", "high", "max"]
```

不写这个参数就提供全部档位。写了以后：

- `/effort` 只显示这些档位；输入别的（例如 `/effort ultra`）会被拒绝，并列出该模型支持的档位，不会悄悄改成别的。
- 用 `/model` 切换模型时，当前档位会移到新模型支持的最接近的一档，所以请求不会带着接入点不认识的档位发出去。
  切换回来不会自动恢复原档位。
- 子 agent（`task` 工具）运行在发起它的那次请求所用的模型上，使用其档位的默认推理强度（`explore` 为 low，
  `coding` 为 medium，`reasoning` 为 high），并移到该模型支持的最接近的一档。模型还可以给 `task` 工具传
  `reasoning_effort`，自己决定这个子 agent 想多深；提供给它的只有当前模型支持的档位。

两个档位距离相同时取更便宜的那个。

### 子 agent 能做什么 {#what-a-child-agent-can-do}

`task` 工具会启动一个带独立上下文和会话日志的子 agent。它有三种，能力是有意做得不一样的：

| 子 agent | 工具 |
| --- | --- |
| `explore` | `read`、`glob`、`grep`，只读。 |
| `reasoning` | 没有工具，只凭任务描述推理。 |
| `coding` | 和主 agent 一样：`read`、`write_file`、`edit`、`bash`，以及你配置的 skills 和 MCP 服务器。 |

`coding` 子 agent 拥有主 agent 的全部能力，**除了** `task`（子 agent 不能再启动子 agent）、即时 harness、
`ask_user`（它靠自己手上的任务做完，不会中途打断你；它需要的信息必须写进父 agent 交给它的任务里）、
`todo_write`（它的计划没有人看），以及
`list_sessions` / `send_message`。在 `[harness]` 里设 `subagent_messaging = true` 可以把最后两个也给它。它和主
agent 一样没有 `glob` 和 `grep`，而是在 shell 里用 `rg`、`grep`、`find` 搜索。

它的 shell 受**你的权限级别**约束，和主 agent 完全一样：`ask` 时，子 agent 想运行的命令会在同一个面板里问你，
你的回答会回到子 agent；`safe` 时在沙箱里运行；`full` 时直接运行；`deny` 时被拒绝。`/permission` 对已经在工作
的子 agent 从它的下一条命令起生效。

### Anthropic 模型

`anthropic = true` 表示这个模型走 Anthropic 的 Messages API，而不是 OpenAI 兼容接口。
其余参数含义不变，`/model` 选择页会在每一行标出它用的是哪个 API：

```toml
[[models]]
model = "claude-sonnet-4-5"              # API 的模型 id，不是显示名
display_model = "Claude Sonnet 4.5"      # 顶部和 /model 选单里显示的名字
token = "sk-ant-..."                     # 换成你自己的 Anthropic API key
anthropic = true                         # Messages API，走 Anthropic 官方 SDK
# base_url = "https://api.anthropic.com"  # 用网关或代理时取消注释
context_window = 200000                  # 该模型的窗口，以模型页公布为准
compact_percent = 80                     # 达到窗口的 80% 时压缩
multimodal = true                        # Claude 支持图片
```

`base_url` 默认是 `https://api.anthropic.com`；`token` 缺省时读 `ANTHROPIC_API_KEY`，
而不是 `OPENAI_API_KEY`。如果网关说的是 Messages 协议但地址不同，就要自己填根地址。

`anthropic` 和 `responses_api` 不是叠加关系：Responses 属于 OpenAI 兼容接入点，
Messages API 没有这种模式。两项同时写上的配置会在启动时直接报错，
而不是默默选一个。

`/effort` 会变成 Anthropic 的思考预算：`medium` 及以上会在回答前先推理，`off` 则关闭。
和其他模型一样，窗口大小和 key 是否正确属于接入点的事，ZettCode 不会在第一次请求前替你验证。

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
也不会展开 TOML 字符串中的 `${VARIABLE}`；唯一例外是 `anthropic` 项，它读的是
`ANTHROPIC_API_KEY`。上面的设置只影响当前终端及其启动的进程，
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
切换只影响后续请求，不创建新会话，也不打断正在执行的请求。用 [`/config`](#adding-models-with-config)
添加的模型立刻可用；手动编辑文件之后需要重启才能读到新增项。

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
anthropic = false              # true 表示调用 Anthropic 的 Messages API
responses_api = false
multimodal = false
context_window = 1000000
compact_percent = 80

[transcript]
max_entries = 1024             # 显示的对话块数量，不是终端行数
mouse_scroll_speed = 1           # 一个滚轮事件滚动的行数
tips = true                    # Processing 下面的小提示

[agents_md]
enabled = true                 # 使用项目指令

[ask_user]
enabled = true                 # 允许模型询问用户

[skills]
enabled = true
roots = []                     # 在 scope 对应目录之前搜索的额外目录
scope = "both"                 # "both"、"workspace" 或 "global"，见 Skills 与 MCP

[mcp]
enabled = true
config = "~/.zettcode/mcp.json" # 服务器定义文件，不是本 TOML 文件
scope = "both"                 # "both"、"workspace" 或 "global"

[compaction]
self = false                   # 让模型自己压缩上下文；/plugins 或会话自己的选择可以覆盖

[plugins]
enabled = true                 # 加载已安装的第三方插件
disable = []                   # 要跳过的 entry-point 名称

[update]
enabled = true                 # 后台检查 PyPI 新版本

[ui]
# theme = "nord"               # 按名字指定启动主题（见“颜色”）；不设则跟随终端深浅
# pet = "cat"                  # 对话上方是哪只宠物（见“宠物”）；不设则是猫
# pet_position = [1.0, 0.5]    # 它站的位置，横向和纵向，都在 0 到 1 之间；拖动它时会自动写入

[statusline]
# 头部和状态行的每一部分默认都显示。写上名字设为 false 即隐藏；/statusline 会替你改这里。
# ctx = false
# speed = false

[sessions]
enabled = true                 # 会话之间可以互发消息；false 则不加入 broker

[shell]
network = false                # 让在 `safe` 档跑的命令可以访问网络；见“审批”

[harness]
subagent = true                # 提供 task 工具及其子 agent 档位
subagent_max_iterations = 512  # 一个子 agent 完成一个任务最多调用模型的次数
subagent_messaging = false     # 让 coding 子 agent 也有 list_sessions 和 send_message
todowrite = false              # 提供 todo_write，界面会画出计划面板
jit = false                    # 模型可以写并运行小的 Python 工具；/plugins
```

这些顶层段落应该像示例一样放在模型表之外。TOML 的键属于最近的表头：如果直接在
`[[models]]` 下写 `enabled`，它会被当作不支持的模型参数，而不是功能开关。

### 可选参数参考

| 段落 / 参数 | 默认值 | 效果与限制 |
| --- | --- | --- |
| `transcript.max_entries` | `1024` | 正整数。限制可回看的对话块，旧块移出界面，但不会删除持久化历史或模型上下文。 |
| `transcript.mouse_scroll_speed` | `1` | 一个鼠标滚轮事件滚动对话的行数，大于 0、最大 20；`0.5` 这样的小数表示每两个事件滚一行，`3` 表示一格三行。无论取值多少，单个画面最多只移动半屏。 |
| `transcript.tips` | `true` | 请求运行五秒后，在 `Processing` 行下面显示一条小提示。设为 `false` 关闭。 |
| `agents_md.enabled` | `true` | 读取工作区及其上层目录的 `AGENTS.md`，见[项目指令](/zh/guide/instructions)。 |
| `ask_user.enabled` | `true` | 允许单选、多选和自由输入的提问面板。`false` 移除这个工具，不代表禁止模型在普通回答里提出问题。 |
| `skills.enabled` | `true` | 发现 skill 名称和描述，并允许按需加载正文。 |
| `skills.roots` | `[]` | 目录字符串数组。先按顺序搜索这些目录，再搜索 scope 对应的目录；同名 skill 取最先找到的。 |
| `skills.scope` | `"both"` | skills 放在哪里：`"both"`（默认）同时读 `<工作区>/.zettcode/skills` 和 `~/.zettcode/skills`，先项目后个人，所以项目里的同名 skill 在该项目内优先；`"workspace"` 只读项目的，`"global"` 只读你自己的。见 [Skills 与 MCP](/zh/guide/skills-and-mcp#where-they-live)。 |
| `mcp.enabled` | `true` | 有服务器配置时启用 MCP 工具；默认文件不存在时不加载服务器。 |
| `mcp.config` | `~/.zettcode/mcp.json` | 用户自己的 JSON 服务器配置路径。建议用绝对路径或 `~`，避免位置不明确。 |
| `mcp.scope` | `"both"` | 读哪些服务器文件：`"both"`（默认）合并用户的文件和 `<工作区>/.zettcode/mcp.json`，同名服务器以项目的为准；`"workspace"` 或 `"global"` 只读其中一个。工作区文件相当于仓库要求你去运行的命令，不想启动某个仓库的服务器时请设为 `"global"`。 |
| `compaction.self` | `false` | 没有自己选择过的会话是否允许模型压缩自己的上下文。`/plugins` 里的 `self-compaction` 开关控制默认值；单个会话的选择从代码或 HTTP 设置。见[自我压缩](/zh/guide/commands#self-compaction)。 |
| `statusline.<部分>` | `true` | 把头部或状态行的某一部分设为 `false` 即隐藏；没写的部分都显示，只有 `pet`、`turn-calls` 和 `turn-tools` 例外，它们默认隐藏，设为 `true` 才出现。部分有 `app`、`session`、`handle`、`workspace`、`model`、`effort`、`state`、`mode`、`self-compact`、`tokens`、`cache`、`speed`、`ctx`、`keys`、请求结束行的各项（`turn-time`、`turn-clock`、`turn-tokens`、`turn-cache`、`turn-calls`、`turn-speed`、`turn-tools`；插件可以加名为 `turn-<something>` 的其他项）、`pet`（对话上方的宠物，见[宠物](/zh/guide/interface#the-pet)）；不认识的名字会报错。`/statusline` 会替你改这张表。见[选择显示哪些部分](/zh/guide/interface#choosing-what-is-shown)。 |
| `plugins.enabled` | `true` | 加载已安装的第三方插件；关闭后内置 UI 功能仍可使用。 |
| `plugins.disable` | `[]` | 要跳过的插件 **entry-point 名称**数组，不一定等于 pip 包名。 |
| `update.enabled` | `true` | 后台检查 PyPI，并在之后启动时提示新版本，不会自动安装。 |
| `sessions.enabled` | `true` | 向后台会话 broker 登记，使本会话可以被 `@名字` 发消息，也可以给其他会话发消息；模型会多出 `list_sessions` 和 `send_message` 两个工具。见[会话之间互发消息](/zh/guide/messaging)。 |
| `harness.subagent` | `true` | 提供 `task` 工具：模型可以把任务交给带独立上下文和会话日志的子 agent。 |
| `harness.subagent_max_iterations` | `512` | 一个子 agent 完成一个任务最多可以调用模型的次数。子 agent 在真实代码库里探索或修改要调用几十次（库自带的默认值 18 会让这类任务做到一半就结束）；这个值是防止它停不下来的上限，不是目标。子 agent 也会拿到你项目的 `AGENTS.md`。 |
| `harness.subagent_messaging` | `false` | 让 `coding` 子 agent 也拥有 `list_sessions` 和 `send_message`。默认关闭：子 agent 只为一个会话做一件事，和其他会话对话是那个会话自己的事。见[子 agent 能做什么](#what-a-child-agent-can-do)。 |
| `harness.todowrite` | `false` | 提供 `todo_write`，清单由界面画在计划面板里。维护计划要花轮次，所以默认关闭。 |
| `harness.jit` | `false` | 启动时就打开 just-in-time harness：模型可以自己写小的 Python 工具，存在 `~/.zettcode/harness/<工作区>/<会话 id>/` 里并运行它们。它写的代码跑在自己的子进程里 —— 崩溃或卡死不会带走窗口 —— 并且在 `full` 以下的每一档都跑在 `safe` 用的那个边界里，所以仍然默认关闭。`full` 下它拿到的是你自己的权限；没有沙箱的机器上，harness 会每个会话说一次，模型写的代码不会在你不知情的情况下失去边界。`/plugins` 在下次启动时打开或关闭它。只有**改了边界**（进或出 `full`）才会关掉那个子进程：下一次请求重新起一个，模型自己写的工具要再跑一次 `repo_load` 才回来；`ask` 和 `safe` 用的是同一个边界，在两者之间切换不花任何代价。仓库要在 `__init__.py` 旁边写一个 `MANIFEST`（name、version、description，以及可选的、它声明的 `tools`）才能加载；
同一目录下的 `BAN_TOOLS` 列出它不允许定义的工具名。`/harness` 只读这些文件、不导入代码，所以显示的是声明，不是
代码实际定义了什么。 |
| `shell.network` | `false` | 让在 `safe` 沙箱里跑的命令可以访问网络。默认关闭；`full` 永远有网络，没有沙箱的机器也一样。见[审批](/zh/guide/interface#审批)。 |

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

没有指定时，ZettCode 会尝试检测终端背景，选择匹配的深色或浅色主题；这两个主题
都使用终端本身的页面背景。

### 按名字选主题

其他主题都有名字，而名字就是文件。程序自带 16 个：

| 深色 | 浅色 |
| --- | --- |
| `catppuccin-mocha`, `tokyo-night`, `nord`, `gruvbox-dark`, `rose-pine`, `kanagawa`, `dracula`, `one-dark`, `solarized-dark`, `github-dimmed`, `ayu-mirage` | `catppuccin-latte`, `rose-pine-dawn`, `gruvbox-light`, `solarized-light`, `github-light` |

`/theme nord` 只切换本次运行。输入 `/theme ` 和一个空格会打开所有主题的菜单，而且**菜单会预览**：
用 `↑` `↓` 移动高亮时，整个界面（包括你眼前的对话）都会用那套配色重绘。`Enter` 保留它；
`Esc` 或者删掉输入，就恢复成之前的。这些主题自己绘制页面背景，所以在任何终端里看起来都一样；按名字选 `dark` 和 `light` 时也一样，只有启动时的自动选择才把页面留给终端。

**选择会被记住。**`/theme nord` 会在 `config.toml` 的 `[ui]` 下写上 `theme = "nord"`（只改这一行，文件其余部分不动），
下次启动就用它。用方向键在菜单里移动不会记住任何东西，只有 `Enter` 或者输入完整名字才会。如果 `config.toml`
写不了这一行（文件不存在，或者 `[ui]` 的写法无法安全编辑），配色仍然会切换，并提示你它不会保留。

想启动就用某个主题，在 `config.toml` 里写上它的名字：

```toml
[ui]
theme = "nord"
```

外壳构建出来之前画的那一帧就已经是这套配色，所以浅色主题不会先闪一下深色。只有插件提供的主题没法这么早拿到，
它晚一帧随外壳一起出现。

### 加上你自己的

把一个文件放进 `~/.zettcode/themes/`，文件名就是主题名：`~/.zettcode/themes/sunset.toml` 就是
`/theme sunset`，下次打开菜单就在里面，不用重启。文件格式和下面的 `theme.toml` 相同，另外可以加一行
`description`，显示在名字旁边：

```toml
description = "warm and low-contrast"
base = "dark"            # 没写的颜色从这里来

[ui]
surface_alt = "#3a322b"          # 不写 `background` 就继续用终端自己的页面背景
accent = "#e0a458"
```

和自带主题同名的文件会替换它，调整自带主题就是这样用：复制一份，改掉不满意的，名字不变。`dark` 和 `light`
不能被替换。名字是一个词（字母、数字、`.`、`_`、`-`）。读不了的文件仍会列在菜单里，选它的时候会告诉你原因。

自带主题以及每个组件在其中的样子，可以用 `make palettes` 生成到 `docs/internal/palettes.html`。
这个页面是产物、不在仓库里：改了配色或主题相关代码后重新生成一次。

### 叠在任何主题之上的一个文件

需要持久化自定义配色时，创建 `~/.zettcode/theme.toml`。
这是**另一个文件**，不要把下面的段落放进 `config.toml`：

```toml
base = "dark"                  # dark 或 light，默认 dark

[ui]
accent = "#a7c080"
accent_bright = "#83c092"
surface_side = "#393a44"       # /btw 消息背景
surface_peer = "#313244"       # 会话之间互发消息的背景
# background = "#232a2e"      # 保持注释，继续使用终端背景

[tools]
read = "#89b4fa"
shell = "#fab387"

[code]
keyword = "#e58fa8"
string = "#9bddad"
comment = "#6d7a70"
number = "#d8b46a"
function = "#7fb7d8"
builtin = "#b8a6e0"
inline = "#9bddad"            # Markdown `行内代码`
```

只覆盖写出的颜色，其余来自 `base`，或者来自 `[ui] theme` 所指定的主题（文件叠在它上面）。主题文件优先于自动深浅色检测；运行中仍然可以用
`/theme` 选择主题，但不会改写任何文件。

| 段落 | 颜色参数 |
| --- | --- |
| `ui` | `background`, `surface`, `surface_alt`, `surface_side`, `surface_peer`, `text`, `muted`, `subtle`, `accent`, `accent_bright`, `warning`, `error`, `diff_added`, `diff_removed`, `diff_added_fill`, `diff_removed_fill`, `border`, `focus`, `selection` |
| `tools` | `read`, `search`, `image`, `write`, `delete`, `shell`, `plan`, `subagent`, `message`, `web-search`, `ask-user` |
| `code` | `inline`, `text`, `keyword`, `string`, `comment`, `number`, `function`, `builtin`, `operator`, `punctuator` |

`diff_added` 和 `diff_removed` 给编辑 diff 的行和文件旁边的 `+N -M` 上色。不写时分别跟随 `accent` 和 `error`，
所以改了这两个，diff 也会跟着变；想让 diff 单独换颜色就设置它们。`diff_added_fill` 和 `diff_removed_fill` 是这些行后面的底色；
不写时就是行的颜色混进页面底色得到的，所以底色会跟着配色走。

颜色使用带引号的六位十六进制，例如 `"#83c092"`。不能填 `"green"`、三位十六进制，
也不能用 TOML 字符串 `"None"` 表示透明；省略 `background` 就会保留终端背景。
修改背景色后，同时检查正文和提示文字是否还有足够对比度。

## 环境变量

| 变量 | 效果 |
| --- | --- |
| `ZETTCODE_CONFIG` | 选择另一份完整配置文件。 |
| `OPENAI_API_KEY` | 模型没有非空 `token` 时使用的 key。 |
| `ANTHROPIC_API_KEY` | `anthropic` 项没有非空 `token` 时使用的 key。 |
| `TIKTOKEN_CACHE_DIR` | 分词器下载的词表缓存位置。默认 `~/.zettcode/cache/tiktoken`；放在系统临时目录里迟早会被清掉，而重新下载要好几秒。 |
| `ZETTCODE_REDUCED_MOTION` | 设置为 `1`，抑制装饰性的扫光动画。 |
| `ZETTCODE_BROKER_DIR` | 会话 broker 存放文件的目录，默认 `~/.zettcode/broker`。 |
| `ZETTCODE_BROKER_IDLE` | 最后一个会话离开后 broker 保留的秒数，默认 `30`。 |
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
| `No models configured` | 添加一项 `[[models]]`。终端没有模型也能启动，`/config` 会写下第一项；`zettcode ask` 与 `zettcode doctor` 在文件里还没有时会拒绝。 |
| `Missing token for model ...` | 填写 `token`，或在启动终端中设置该 API 对应的变量：`OPENAI_API_KEY`，`anthropic` 项则是 `ANTHROPIC_API_KEY`。占位符是非空字符串，通常要到 API 调用时才会报错。 |
| `Unknown config keys ...` | 只使用本页列出的键，例如 `model_name` 应该改成 `model`。 |
| `must be bool` / `must be int` | 用 `true` 而不是 `"true"`；用 `1000000` 而不是 `"1000000"`。 |
| `Invalid config file ...` | 检查引号、表头和重复键。TOML 语法错误会包含解析器的位置信息。 |
| `cannot use both APIs` | 同一项同时写了 `anthropic` 和 `responses_api`。只能留一个：它们是两种不同的协议，不是同一件事的两半。 |
| 报错里出现 `HTTP 401` / `HTTP 403` | 服务端拒绝了 token。检查这一项的 `token`，或它所属 API 的环境变量。状态码后面是服务端给出的原话。 |
| 报错里出现 `HTTP 404` | 这个端点上模型 id 或地址不对。检查 `model` 和 `base_url`。 |
| 报错里出现 `HTTP 429` / `HTTP 5xx` | 是 provider 在限流或出故障，不是 ZettCode。报错之前已经自动重试过几次。 |
| `Processing` 旁边出现 `nothing from the model for …` | 模型有一阵子没说话了。推理模型沉默很久是正常的；觉得不对就按 `Esc` 停掉。 |
| API 拒绝模型或协议 | 检查模型 id 和协议开关：OpenAI 兼容接口看 `responses_api`，Messages API 看 `anthropic`。显示标签不是 API id。 |
| 图片输入被拒绝 | 选择支持图片的模型，并且只为对应项启用 `multimodal`。 |

修改 `config.toml` 后重启。如果是会话、显示或 MCP 问题，继续看[常见问题](/zh/guide/faq)。
