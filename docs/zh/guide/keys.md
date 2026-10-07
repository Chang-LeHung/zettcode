# 快捷键与鼠标

输入框的行为跟 Readline 一样，因为大家已经熟悉它；外壳只补上那些需要整块屏幕的按键。

## 可以先试这几个操作

- **输入多行任务：** 写完第一行，按 `Alt-Enter` 或 `Shift-Enter` 换行，最后按 `Enter`
  发送整个草稿。有些终端无法区分 `Shift-Enter`，这时改用 `Alt-Enter`。
- **修改行首：** `Ctrl-A` 到当前行开头，改完再用 `Ctrl-E` 回到行尾。这里是移动光标，不是全选。
- **复用之前的输入：** 空草稿中按 `↑` 或 `Ctrl-P` 找回提交过的输入，编辑后按 `Enter`
  作为新请求发送。`Ctrl-R` 搜索的是用户输入历史，不是助手回答。
- **回看回答：** 用滚轮或 `Page Up` 向上查看，`Esc` 返回底部，不会改变草稿。
- **粘贴文本或图片：** 文本使用终端本来的粘贴快捷键，macOS 常用 `Cmd-V`，其他终端常用
  `Ctrl-Shift-V`。ZettCode 内的 `Ctrl-V` 专门用于附加图片，不是文本粘贴。

快捷键会随焦点变化：例如列表里的 `Enter` 是选择一行，不是发送草稿；`Esc` 会先关闭面板。
审批和提问面板以底部显示的提示为准。

## 发送

| 按键 | 作用 |
| --- | --- |
| <kbd>Enter</kbd> | 发送草稿，或执行斜杠命令。 |
| <kbd>Alt</kbd>+<kbd>Enter</kbd>、<kbd>Shift</kbd>+<kbd>Enter</kbd> | 插入换行。 |
| <kbd>Tab</kbd> / <kbd>Shift</kbd>+<kbd>Tab</kbd> | 补全正在输入的斜杠命令。 |

## 编辑

| 按键 | 作用 |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>A</kbd> / <kbd>Ctrl</kbd>+<kbd>E</kbd>、<kbd>Home</kbd> / <kbd>End</kbd> | 行首 / 行尾。 |
| <kbd>Ctrl</kbd>+<kbd>B</kbd> / <kbd>Ctrl</kbd>+<kbd>F</kbd>、<kbd>←</kbd> / <kbd>→</kbd> | 移动一个字符。 |
| <kbd>Alt</kbd>+<kbd>B</kbd> / <kbd>Alt</kbd>+<kbd>F</kbd>、<kbd>Ctrl</kbd>+<kbd>←</kbd> / <kbd>Ctrl</kbd>+<kbd>→</kbd> | 移动一个词。 |
| <kbd>Ctrl</kbd>+<kbd>Home</kbd> / <kbd>Ctrl</kbd>+<kbd>End</kbd>、<kbd>Alt</kbd>+<kbd>&lt;</kbd> / <kbd>Alt</kbd>+<kbd>&gt;</kbd> | 整段草稿的开头 / 结尾。 |
| <kbd>Ctrl</kbd>+<kbd>U</kbd> / <kbd>Ctrl</kbd>+<kbd>K</kbd> | 删到行首 / 行尾。 |
| <kbd>Ctrl</kbd>+<kbd>W</kbd> / <kbd>Alt</kbd>+<kbd>Backspace</kbd>、<kbd>Alt</kbd>+<kbd>D</kbd> | 删除前一个 / 后一个词。 |
| <kbd>Ctrl</kbd>+<kbd>Y</kbd> | 粘回上一次被整行或整词删掉的内容。 |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> / <kbd>Ctrl</kbd>+<kbd>_</kbd> | 撤销最近一次编辑。 |
| <kbd>↑</kbd> / <kbd>↓</kbd> | 先在多行草稿里移动，然后在已发送的输入历史里翻。 |
| <kbd>Ctrl</kbd>+<kbd>P</kbd> / <kbd>Ctrl</kbd>+<kbd>N</kbd> | 直接在输入历史里翻。 |
| <kbd>Ctrl</kbd>+<kbd>R</kbd> | 在输入历史里向后搜索。 |

## 外壳

| 按键 | 作用 |
| --- | --- |
| <kbd>Ctrl</kbd>+<kbd>C</kbd> | 复制并清除选中内容；没有选中时停止正在跑的请求；请求也是空的时清空草稿。 |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | 删除后一个字符 —— 输入框为空且没有任务在跑时则退出。 |
| <kbd>Ctrl</kbd>+<kbd>L</kbd> | 重画屏幕，终端内容被冲掉时用。 |
| <kbd>Ctrl</kbd>+<kbd>T</kbd> | 展开 / 收起最新的一段思考。 |
| <kbd>Ctrl</kbd>+<kbd>V</kbd> | 从剪贴板附上一张图片。 |
| <kbd>Page Up</kbd> / <kbd>Page Down</kbd> | 滚动对话，输入框仍然保持聚焦。 |
| <kbd>Esc</kbd> | 向上滚动时跳回最新一行；关闭弹窗；关闭命令菜单。 |
| <kbd>Tab</kbd> | 接受弹窗或命令菜单里高亮的那一项。 |

## 回答提问

模型在等你回答时，这些按键属于它弹出的面板：

| 按键 | 作用 |
| --- | --- |
| <kbd>↑</kbd> / <kbd>↓</kbd> | 在模型给出的选项之间移动。 |
| <kbd>Enter</kbd> | 对高亮的那一行生效：选中它（单选会直接发出）、勾选／取消勾选，或在 `send` 行上收尾；如果你是在打字，则发送你输入的内容。 |
| 直接打字 | 编辑回答行，发给模型的就是这里的内容；打字期间选项会折起来，按 `↑` / `↓` 可以叫回来。 |
| <kbd>Esc</kbd>、<kbd>Ctrl</kbd>+<kbd>C</kbd> | 不回答：模型会收到「问题被取消」。 |

## 鼠标

| 操作 | 作用 |
| --- | --- |
| 滚轮 | 滚动对话。 |
| 单击 Thinking 或 Tool 行 | 展开 / 收起。 |
| 在对话区拖动 | 选中文字，松开即复制；拖到边缘之外会继续扩大选区。 |
| 在弹窗、头部或状态行上拖动 | 复制画在那里的文字 —— 这些区域以前本来没有可选中文本。 |
| 双击 | 选中整行。 |
| <kbd>Shift</kbd>+单击 | 扩大当前选区。 |

如果你想用终端自己的选择功能，按住终端的修饰键（通常是 <kbd>Shift</kbd> 或 <kbd>Alt</kbd>）
再拖。
