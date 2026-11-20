# JIT harness

开启 harness 后，模型可以为眼前的任务写它需要的工具（一个或几个，放在同一个 repository 里），用 `repo_load`
加载，并在同一轮里调用；重复出现的步骤就能交给工具，而不是一遍遍重读重敲。它默认开启。

![`/harness` 页面：每个会话一个 repository——loader-tools、pager-tools、parser-tools——当前会话被标出，旁边是 Tools 和 Files 两个标签页](/screens/harness.svg)

## 每个工作目录一份 harness

harness 属于它服务的那个项目。某个会话的目录是
`~/.zettcode/harness/<项目名>-<哈希>/<会话 id>/`，哈希取自项目完整路径：两个都叫 `app` 的 checkout 会得到
不同的目录，Windows 不接受的名字（`CON`）也能有一份。在这里工作的会话不会加载该项目目录之外的任何东西，
所以为一个仓库写的工具不会出现在另一个仓库里；而这个目录放在会话存储**旁边**而不是里面，清空会话不会删掉它。

借用是唯一的例外，而且是你主动要的：见下面的[页面](#the-page)。

## 会发生什么

1. 模型把工具写进 `~/.zettcode/harness/<项目名>-<哈希>/<会话 id>/`。
2. 它用 `repo_load` 加载工具。代码在子进程里导入，所以崩溃或卡死不会影响你的会话。
3. 它像其他工具一样调用它。每一步都是可以展开的行。

一个会话保留一个仓库，之后复用它。

## 打开或关闭

| 方式 | 效果 |
| --- | --- |
| `[harness] jit = false` | 每次运行都以关闭状态启动。 |
| `/plugins` | 为下次启动切换开关。 |
| `/harness gen [描述]` | 为本次运行打开它，让模型为这个工作区造工具。 |
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

## 页面

`/harness` 打开机器上所有 harness 的只读表格，就是本页顶部那张图：每个 repository 一行，写着造它的是哪个会话、
它是做什么的。`Tab` 在 harness、工具和文件之间切换，所以这页也回答了「它到底能做到什么」和「它记下了什么」。
在别的会话那行按 `Enter` 会把它借给当前对话——这是项目之外的工具有办法进来的唯一一条路；页面会在那一行的说明后面标上
「in use」。在你自己的那行按 `Enter` 就还回去；`/harness reset` 只是关掉 harness，借用不会结束；在借用期间，
`/harness gen` 会造在借来的文件夹里，而不是你自己的。借用或归还之后，对话里会写明是哪个 harness。借用会跟着这个对话保存：之后 resume 它（本窗口或以后的窗口），仍然在借来的 harness 里工作（除非那个文件夹已被删）。记录是 `~/.zettcode/harness/.borrowed/` 下的一个小文件，删掉它就忘掉这次借用。harness 开着时，这会改变
请求里的工具，所以下一次请求可能不会命中 prompt cache（见[模型](/zh/guide/models#读懂状态行)）；关着时没有挂载任何工具，
也就没有损失。`/harness reset` 关掉 harness 同样会把工具从下一次请求里拿掉，也可能不命中 cache。选中标着「in use」的
那行不会有任何变化，也不会有提示。

只有已经有 repository 的 harness 才会列出来：空的目录还不算一个 harness。

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
大小、最近的错误——从保存的对话里读取，所以重启后还在。它的 `calls` 参数决定统计多少：`0`（默认）表示上次压缩
之后的当前上下文，正数表示最近这么多次工具调用，`-1` 表示整段保存的对话，包含已经压缩掉的历史。

## 库

harness 不一定是模型在本次会话里写的。库按名字保存 harness，不属于任何会话，所有工作区的所有会话都能用。有两个命令
在管它，它们是两回事：

**在终端里**，`zettcode harness` 负责获取和保存仓库。它运行完就退出，不会启动会话。

```text
zettcode harness add acme/todos            # 从 GitHub 下载，展示内容，你确认后才保存
zettcode harness add acme/todos@v2 --as todos-v2
zettcode harness list                      # 名字、版本、工具、来源、commit、状态
zettcode harness show todos
zettcode harness update todos              # 重新拉取来源，展示改动，确认后替换
zettcode harness fork todos my-todos       # 复制一份自己的，没有上游，可以随便改
zettcode harness remove my-todos
```

**在 ZettCode 里面**（终端窗口和编辑器），`/harness` 作用在你当前的会话上：

```text
/harness use todos          # 当前窗口里所有会话都在这个库 harness 里工作，之后每次启动也是
/harness use --none         # 各个会话重新用自己的 harness
/harness save notes         # 把当前会话的 harness 以某个名字保存进库
/harness fork todos mine    # 复制一份库里的 harness，自己改自己的
```

`add` 需要 `git`（没有的话请先安装），接受 `owner/repo`、`owner/repo@分支-标签-或-commit`，或
`https://github.com/owner/repo` 地址。仓库必须符合[上面的格式](#仓库)：根目录有 `__init__.py` 和 `MANIFEST`。这是你
主动要的仓库，所以不做其他限制，检查时也不会 import 任何东西。保存之前会展示它的 manifest、工具和文件，并固定在你
看到的那个 commit：它不会自己更新，`update` 会先展示改了什么。它的代码在会话加载时运行在你的机器上，沙箱就是
权限等级给 harness 的那个（`full` 下没有），所以保存之前请先读一读。

用 `use` 之后，所有会话都在这个 harness 里工作，模型写的东西会进到里面，下一个会话也能找到。`/harness` 页面会把它
标上 `in use`，你自己会话那一行写着 `using library/<名字>`；在你自己的那行按 `Enter`，会放掉你借来的 harness，回到
这一个。`update` 不会覆盖安装之后做过的修改（状态列会显示 `changed`；安装被中途打断或 `SOURCE.json` 被改过时，显示 `repository missing` 或 `record damaged`，`update` 对这三种都会拒绝，除非先 `fork` 或加 `--force`，被打断的更新还会说明旧目录在哪），想保留这些修改就用 `fork` 复制一份。已经在
运行的会话保留着它已加载的模块，更新要到下一个会话才看得到。正在 `in use` 的 harness 不能 `remove`，先
`/harness use --none`。如果当前会话本来就在某个库 harness 里工作，`save` 没有意义（它已经在库里了），请改用 `fork`。

## 限制

- 在 `full` 下它不是沙箱：代码拥有你的权限。
- `/harness reset` 只是让之后的请求不再使用这些工具，不删除文件。
- 会话被另一个 ZettCode 进程持有时，那边的 `gen` 什么也不改。

设置：[`harness.jit`](/zh/guide/config#可选参数参考)。命令：[命令参考](/zh/guide/commands)。
