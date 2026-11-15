# 会话之间互发消息

一台机器上可以同时跑好几个 ZettCode 会话：一个修解析器，一个写文档，一个审分支。它们通过一个本机的 broker 互相找到、
互相传话。没有任何东西离开这台机器。

## 名字

每个会话登记时带一个名字，也就是你在 `@` 后面输入的那个。名字先取会话的标题（`Fix the parser` → `fix-the-parser`），
没有标题就取它所在的文件夹，再没有就是 `session-` 加 id 的后六位。后来的同名会话会接上自己 id 的末几位；
第一次回复之后写下的标题会改名。你自己的名字显示在标题栏后面。

输入 `@` 会列出会话：每一项写明它在做什么、是否在工作、在哪个文件夹。匹配顺序是名字、标题、文件夹、id 开头，名字优先。

## 发一条消息

```text
❯ @fix-the-parser 你看一下 tokenizer 现在还能处理 tab 吗？
```

`@name` 只是一个引用，和文件、skill 一样：草稿仍然发给本会话的模型，由它读出你指的是哪个会话，自己调用 `send_message`。
shell 什么都不发。这次调用在对话里是单独一行，显示收件人和结果（`Delivered to …`、`queued`，或没送达的原因）。
消息只有文字，最多 32,000 个字符。没人用的名字就是普通文本，模型不会被告知任何事。

## 收到消息

收到的消息画得和你自己输入的一样，只是颜色不同，上面一行写明来自哪个会话、是它的 agent 还是它的使用者写的。
模型会被告知是谁发的，并把它当作同事的请求：和你已经交代的事情对照着权衡，不会仅凭它做破坏性或不可逆的操作。

- **会话空闲时**，消息立刻开始一次请求。这会消耗 token，而且你没按回车；不想要这个功能就关掉它。
- **会话忙碌时**，`steer` 消息（默认）交给正在运行的请求，让它现在改变方向；`followup` 等这次请求结束。
  无法转向的消息——正在跑的是命令、转向次数到了上限——会作为后续消息等待，发送方会被告知它 `queued`。
  一个会话里最多排 64 条，再多时由 broker 保管（每个会话最多 500 条），有空位就投递。

回答显示给**你**。发消息的会话看不到，除非它的模型自己去回一条。

## 群聊

群是一组有名字的会话，写作 `#名字`。发给群的消息送达其他每个在线成员，每个成员都会被告知它来自哪个群。
只有成员能读历史或改动成员。用模型的 `manage_group` 工具创建，或者在网关的 Chats 页面点 **New group**。

上限：一个群 64 个会话，一个会话在 20 个群里，一台机器 200 个群；超出会被拒绝并说明原因。

## 模型能做什么

| 工具 | 作用 |
| --- | --- |
| `list_sessions` | 列出其他正在运行的会话，以及本会话所在的群。 |
| `send_message` | 给会话或群发文字。消息被收下就返回，不等回答。`mode` 是 `steer`（默认）或 `followup`。 |
| `message_history` | 读与某个会话、或某个群之前的消息。跨重启保留，只限你自己的对话和群。 |
| `manage_group` | 建群、增删成员、退群、删群。 |

旁问（`/btw`）可以用 `list_sessions` 和 `message_history`，不能发 `send_message`。

两个 agent 互相回复会停不下来，所以每条消息带一个"经过了多少个会话"的计数；broker 会拦下会成为第七跳的那一条。

## 从脚本发消息

broker 监听 `127.0.0.1`，端口和令牌在 `~/.zettcode/broker/broker.json`。读到这个文件的进程就能列出会话、发消息：

```sh
PORT=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.zettcode/broker/broker.json')))['port'])")
TOKEN=$(python -c "import json,os;print(json.load(open(os.path.expanduser('~/.zettcode/broker/broker.json')))['token'])")
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:$PORT/sessions
curl -s -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"to": "fix-the-parser", "text": "the build is red", "from": {"name": "ci"}}' \
  http://127.0.0.1:$PORT/messages
```

对方会把它显示成外部来源，并被告知发送者没有经过验证。用 Python 驱动 agent 的程序不必经过 broker：
`client.deliver("the build went red", mode="followup")` 直接把消息交给会话。协议写在
`packages/zettcode-broker/src/zettcode/broker/protocol.py`。

## 限制与注意

- 只限同一台机器、同一个用户。
- 消息送到终端之前会去掉转义序列和控制字符。
- 一个会话每分钟最多发 20 条。
- 对方的 agent 有自己的权限，一条消息不会让它得到更多。
- 每条消息都存在 `~/.zettcode/broker/broker.db`。要清空，先停 broker，再删这个文件。
- broker 卡住时，`zettcode broker restart` 会换掉它，连着的会话会自己重连。

```toml
# ~/.zettcode/config.toml
[sessions]
enabled = false
```

## 关系图

网关的 **Graph** 页面把每个会话画成一个节点，每个群画成一块区域，每条消息画成飞向收件人的光点。**Replay** 按存下来的
历史重画过去的一段时间，不会重新发送任何消息。见[网页网关](/zh/guide/gateway#页面能做什么)。

## 下一步

- [网页网关](/zh/guide/gateway)：查看会话和群，回放关系图。
- [后台 agent](/zh/guide/daemons)：没人坐在键盘前的会话。
- [Codex 与 Claude Code](/zh/guide/code-agents)：同一个群里的其他 agent。
