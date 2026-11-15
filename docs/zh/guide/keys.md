# 快捷键与鼠标

输入框和 Readline 一样。按键属于拿到焦点的东西：面板里的 `Enter` 是选一行，不是发送草稿；`Esc` 先关面板。每个
面板都会在自己下面印出它的按键。

## 发送

| 按键 | 作用 |
| --- | --- |
| <kbd>Enter</kbd> | 发送草稿，或执行斜杠命令。 |
| <kbd>Alt</kbd>+<kbd>Enter</kbd>、<kbd>Shift</kbd>+<kbd>Enter</kbd> | 插入换行。`Alt-Enter` 到处都能用；`Shift-Enter` 要终端肯上报才行。 |
| <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> | 补全斜杠命令。 |

## 编辑

| 按键 | 作用 |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> / <kbd>Ctrl</kbd>+<kbd>E</kbd>、<kbd>Home</kbd> / <kbd>End</kbd> | 行首 / 行尾。 |
| <kbd>Ctrl</kbd>+<kbd>B</kbd> / <kbd>Ctrl</kbd>+<kbd>F</kbd>、<kbd>←</kbd> / <kbd>→</kbd> | 移动一个字符。 |
| <kbd>Alt</kbd>+<kbd>B</kbd> / <kbd>Alt</kbd>+<kbd>F</kbd>、<kbd>Ctrl</kbd>+<kbd>←</kbd> / <kbd>Ctrl</kbd>+<kbd>→</kbd> | 移动一个词。 |
| <kbd>Ctrl</kbd>+<kbd>Home</kbd> / <kbd>Ctrl</kbd>+<kbd>End</kbd>、<kbd>Alt</kbd>+<kbd>&lt;</kbd> / <kbd>Alt</kbd>+<kbd>&gt;</kbd> | 整段草稿的开头 / 结尾。 |
| <kbd>Ctrl</kbd>+<kbd>U</kbd> / <kbd>Ctrl</kbd>+<kbd>K</kbd> | 删到行首 / 行尾。 |
| <kbd>Ctrl</kbd>+<kbd>W</kbd> / <kbd>Alt</kbd>+<kbd>Backspace</kbd>、<kbd>Alt</kbd>+<kbd>D</kbd> | 删除前一个 / 后一个词。 |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>_</kbd> | 撤销最近一次编辑。 |
| <kbd>↑</kbd> / <kbd>↓</kbd> | 先在多行草稿里移动，再翻已发送的输入。 |
| <kbd>Ctrl</kbd>+<kbd>P</kbd> / <kbd>Ctrl</kbd>+<kbd>N</kbd> | 直接翻已发送的输入。 |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | 在已发送的输入里向后搜索。 |

## 外壳

| 按键 | 作用 |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> | 复制并清除选中内容；没有选中时停止请求；草稿为空时清空草稿。 |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | 删除后一个字符，输入框为空且没有任务在跑时则退出。 |
| <kbd>Ctrl</kbd>+<kbd>L</kbd> | 重画屏幕，终端内容被冲掉时用。 |
| <kbd>Ctrl</kbd>+<kbd>T</kbd> | 展开 / 收起最新的一段思考。 |
| <kbd>Ctrl</kbd>+<kbd>V</kbd> | 从剪贴板附上一张图片。粘贴文本用终端自己的键。 |
| <kbd>Page Up</kbd> / <kbd>Page Down</kbd> | 滚动对话，输入框保持聚焦。 |
| <kbd>Alt</kbd>+<kbd>Up</kbd> / <kbd>Alt</kbd>+<kbd>Down</kbd>（也可用 <kbd>Ctrl</kbd>+<kbd>Up</kbd> / <kbd>Ctrl</kbd>+<kbd>Down</kbd>） | 跳到你上一条或下一条消息，让它停在视图顶部；有后续消息在等时，改为在那个列表里移动。 |
| <kbd>Esc</kbd> | 停止请求；或者先做这些：回到最新一行、关闭面板或菜单、取消高亮的后续消息。 |
| <kbd>Tab</kbd> | 接受面板或命令菜单里高亮的那一项。 |

## 请求运行时

请求运行期间输入，会问这条消息是引导它还是在它之后跟进。`Option` 就是 Mac 上的 `⌥` 键，其他键盘上是 `Alt`。

| 按键 | 作用 |
| --- | --- |
| <kbd>Enter</kbd> | 询问这条消息算什么；在提问里，采用高亮的那一行。 |
| <kbd>F</kbd> / <kbd>S</kbd> | 在提问里：直接选 **f**ollow up（后续）或 **s**teer（引导）。`Esc` 保留草稿。 |
| <kbd>Option</kbd>+<kbd>↑</kbd> / <kbd>Option</kbd>+<kbd>↓</kbd> | 没有高亮时进入后续消息列表；有消息高亮时把它**前移或后移**一位。 |
| <kbd>↑</kbd> / <kbd>↓</kbd> | 有后续消息高亮时移动高亮；在最后一行再按 `↓` 回到输入框。 |
| <kbd>Enter</kbd> | 有后续消息高亮时取回输入框；再次发送会放回原处。 |
| <kbd>Delete</kbd> / <kbd>Backspace</kbd> | 有后续消息高亮时删除它。 |
| <kbd>Esc</kbd> | 有后续消息高亮时取消高亮；否则停止请求，后续消息保留到你的下一条回复。 |

引导消息发出后不能再改。[请求运行时输入](/zh/guide/interface#请求运行时输入)里有其余说明。

## 回答提问

| 按键 | 作用 |
| --- | --- |
| <kbd>↑</kbd> / <kbd>↓</kbd> | 在模型给出的选项之间移动。 |
| <kbd>Enter</kbd> | 对高亮那行生效：选中、勾选 / 取消勾选，或收尾多选；你打过字时发送你写的内容。 |
| 直接打字 | 编辑回答行；打字期间选项折起来，`↑` / `↓` 叫回来。 |
| <kbd>Esc</kbd>、<kbd>Ctrl</kbd>+<kbd>C</kbd> | 不回答：模型会收到「问题被取消」。 |

## 鼠标

| 操作 | 作用 |
| --- | --- |
| 滚轮 | 滚动对话。 |
| 单击 Thinking 或 Tool 行 | 展开 / 收起。 |
| 在对话区拖动 | 选中文字，松开即复制，并有提示确认；拖到边缘之外会继续扩大。 |
| 在面板、头部或状态行上拖动 | 复制画在那里的文字。 |
| 双击 | 选中整行。 |
| <kbd>Shift</kbd>+单击 | 扩大当前选区。 |

想用终端自己的选择功能，按住它的修饰键（通常是 <kbd>Shift</kbd> 或 <kbd>Alt</kbd>）再拖。
