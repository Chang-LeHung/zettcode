# 模型与上下文

ZettCode 能对接任何 OpenAI 兼容的接入点：云上的 API、聚了多家 provider 的网关，或者跑在你自己机器上的模型。
某一项写了 `anthropic = true`，就走 Anthropic 的 Messages API。需要填什么在
[配置参考](/zh/guide/config#models)。

## 切换

`/model` 在对话之上打开选择面板。`Enter` 选的是**之后**的请求 —— 正在跑的那次不受影响 —— 头部立刻显示新名字。
`/model DeepSeek Pro` 也行，显示名和模型 id 都能匹配，适合你已经清楚要哪个的时候。

![`/model` 选择页：DeepSeek Pro 标为当前，下面依次是 Claude Sonnet 4.5、GPT-5 和本地 Qwen3 Coder，每行都写了来源和所讲的 API](/screens/models.svg)

每行开头写模型来自哪里：`file`，或者插件提供的 `plugin <host>`。敲 `/model ` 后的补全菜单里，每个名字旁边也带着
同样的来源和协议。`zettcode[models]` 这个 extra 为环境里的每个厂商 key 提供一个官方模型；见
[插件](/zh/guide/plugins#official-models)。它们不在配置文件里：插件描述 host，runtime 在构建时从插件指定的
环境变量里读一次 token。某行写着 `needs $ACME_API_KEY`，说明当时那个变量没设：导出它，再重启会话。`/config`
只列出文件里的模型。

每个模型有自己的 token、接入点和窗口，所以在本地服务和云服务之间切换只要按一个键，不用改配置再重启。

例如按[双模型配置](/zh/guide/config#配置多个模型)加好 `DeepSeek Pro` 和 `DeepSeek Flash`，再试：

```text
/model DeepSeek Pro
先解释这个模块的设计取舍，再动手改。
/model DeepSeek Flash
看这张截图，说明这条错误信息是什么意思。
```

截图请求要真的附上图片，模型也要配了 `multimodal = true`；切换模型不会替你附图。切换时对话不变，想从空白
开始用 `/new`。

## 推理强度

`/effort` 决定模型回答前愿意想多久：

| 档位 | 适合什么 |
| --- | --- |
| `off` | 请求不做刻意思考，实际取决于接入点支持。 |
| `minimal` | 一点点思考，最快。 |
| `low` | 小改动时的快速回答。 |
| `medium` | 默认的平衡点。 |
| `high` | 难题多想一些。 |
| `xhigh` | 难题上长时间思考。 |
| `max` | provider 能接受的最高预算。 |
| `ultra` | 请求最高档位，是否可用取决于接入点。 |

这个选择对之后的请求生效，并且随会话记录下来：恢复那个会话就把档位放回去。它不是 `config.toml` 里的设置
—— 新会话从配置的 `reasoning_effort` 开始。例如：

```text
/effort low
解释这个正则表达式匹配什么。
/effort high
检查这段加锁代码会不会死锁或竞争，先不要改。
```

实际预算由接入点决定。不是所有接入点都支持所有档位，网关可能直接拒绝不支持的值，而不是替它映射。DeepSeek
当前的映射见 [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)。在这个客户端里，Chat
Completions 配 `/effort off` 只是不发 `reasoning_effort`，不会去发 DeepSeek 单独的 `thinking` 开关，所以它
不保证关掉一个默认就开着思考的 provider。

## 会话恢复什么 {#what-a-session-restores}

会话记着它上次用的模型和推理档位。恢复它 —— `/resume`、`/fork` 或 `zettcode -r` —— 两样都放回去，并在对话里
说明。

- 只用 `/model` 切换不记录；在那个模型上跑一轮才记。`/btw` 旁路提问不记录。
- 没有记录的会话，保持你打开它时选中的模型。
- 记录的模型已不在配置里，或者两个条目重名，ZettCode 留在当前模型并说明。
- 当前模型不接受的档位，挪到最接近它接受的那一档；会话自己的记录不变。
- daemon 的 `--effort` 只作用于那个进程，不写进会话。

## 上下文窗口

每个模型一次能读多少是有限的，ZettCode 把请求保持在窗口之内：状态行里的 `ctx 34.0%` 是它有多满，`/context` 是
完整的图景，请求在溢出之前就按窗口的 `compact_percent` 压缩。窗口和触发线的设置见
[配置参考](/zh/guide/config#models)。

`/context` 上每个数字的含义、token 去了哪里、压缩的代价，以及怎么让请求保持小，都在
[上下文窗口](/zh/guide/context)。这里有两件事值得记住：

- 状态行的 `ctx` 是请求占**窗口**的比例；`/context` 的一行是某个来源占**请求**的比例。分母不同，一行可能占前者
  60%、占后者 30%。
- `compact_percent` 是窗口的一部分，不是剩下的那部分：设为 80% 时，200,000 的窗口到 160,000 就压缩。

## 读懂状态行 {#读懂状态行}

`↑18.4k ↓900 · 71.2% cached · 74 tok/s · ctx 12.3%` —— 依次是：发出的 token、生成的 token、输入里由 provider
缓存提供的比例、每秒生成的 token，以及最新一次请求时窗口有多满。输入输出总量在整个会话内累加；上下文占用是
快照，不是累加出来的百分比。

| 字段 | 怎么读 |
| --- | --- |
| `↑` / `↓` | provider 上报的累计输入和输出 token。历史上下文每发一次都算一次输入。 |
| `cached` | 累计命中输入的 token ÷ 累计输入 token。100,000 里命中 60,000 就是 `60.0%`。provider 没报告缓存读取时不显示——那和未命中不是一回事。 |
| `tok/s` | 输出 token 除以从第一个 token 到回复结束的时间；不含等第一个 token 的时间，也不含工具、审批和阅读答案的时间。随第一个 token 到达的 token 也算进去，所以数字略偏高。 |
| `ctx` | 最新一次上下文占用相对于所选模型配置窗口的比例。provider 不上报输入 token 时，改用它最后上报的数加上此后追加的内容来测。 |

不上报缓存命中的接入点，在这里给不出有意义的命中率。这些数字不是账单，实际收费看 provider 的控制台。

缓存这一项值得弄明白，时间和钱都花在这里。provider 缓存的是请求的**前缀**：一次请求的开头和上一次逐字节相同，
那一段就更便宜、更快。所以系统提示只写日期不写时间、项目指令按固定顺序读、两轮之间随手打开 `/context` 也没
关系 —— 稳定的前缀有助于复用缓存。不存在通用的“好”百分比：换模型、压缩、工具定义变化和 provider 的缓存
有效期都会让它下降。新生成的输出，只有在之后的请求里发回去，才可能成为命中的输入。
