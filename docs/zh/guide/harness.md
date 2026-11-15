# JIT harness

开启 harness 后，模型可以为眼前的任务写一个小的 Python 工具，加载它，并在同一轮里调用。它默认开启。

## 会发生什么

1. 模型把工具写进 `~/.zettcode/harness/<工作区>/<会话 id>/`。
2. 它用 `repo_load` 加载工具。代码在子进程里导入，所以崩溃或卡死不会影响你的会话。
3. 它像其他工具一样调用它。每一步都是可以展开的行。

一个会话保留一个仓库，之后复用它。

## 打开或关闭

| 方式 | 效果 |
| --- | --- |
| `[harness] jit = false` | 每次运行都以关闭状态启动。 |
| `/plugins` | 为下次启动切换开关。 |
| `/harness gen [描述]` | 为本次运行打开它，让模型为这个工作区造一个工具。 |
| `/harness reset` | 为本次运行关掉它，不会删除任何东西。 |

```toml
# ~/.zettcode/config.toml
[harness]
jit = false
```

```text
/harness gen 列出这个仓库里的 TODO 注释，按文件分组
```

`gen` 把你的描述作为要求交给模型，同时告诉它把写入限制在 harness 目录、不要改你的项目——这是指示，不是沙箱。
请求进行中不接受这条命令。

`/harness` 打开机器上所有 harness 的只读表格。`Tab` 在 harness、工具和文件之间切换；`Enter` 把别的会话的
harness 借给当前对话。

## 代码在哪里运行

| shell 级别 | harness 代码 |
| --- | --- |
| `full` | 拥有你自己的权限。 |
| `safe`、`ask` | 在 `safe` 沙箱里。 |
| `deny` | 仍然运行，在 `safe` 沙箱里：它不是 shell 命令。 |

机器上没有可用的沙箱时，harness 会在每个会话里说一次。

## 仓库

harness 仓库要在 `__init__.py` 旁边放一个 `MANIFEST`：名字、版本、描述，以及它声明的工具。`BAN_TOOLS` 文件
列出这个仓库不允许定义的工具名。`profile_tools` 报告每个工具用得怎么样——调用次数、成功率、耗时、输入输出
大小、最近的错误——从保存的对话里读取，所以重启后还在。

## 限制

- 在 `full` 下它不是沙箱：代码拥有你的权限。
- `/harness reset` 只是让之后的请求不再使用这些工具，不删除文件。
- 会话被另一个 ZettCode 进程持有时，那边的 `gen` 什么也不改。

设置：[`harness.jit`](/zh/guide/config#可选参数参考)。命令：[命令参考](/zh/guide/commands)。
