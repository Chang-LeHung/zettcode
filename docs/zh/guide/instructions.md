# 项目指令

`AGENTS.md` 告诉代理这个项目是怎么运转的：该跑哪些命令、哪些约定重要、什么不要碰。ZettCode 读取适用于当前
工作区的文件，直接交给模型，你不用粘贴。

## 会读哪些文件

从工作区一路向上找到文件系统根，所以仓库根和嵌套的子包都能贡献规则。外层先读，内层后读：

```
~/AGENTS.md
~/projects/AGENTS.md
~/projects/api/AGENTS.md
~/projects/api/service/AGENTS.md    最后读，冲突时以它为准
```

每个请求都会重读，改完下一轮就生效，不用重启。只有工作区自己的文件和它上层的目录算数：从
`~/projects/api` 启动，不会加载它下面各目录的 `AGENTS.md`。选与你手上那部分代码对应的工作区。

## 该写些什么

当成给新同事的交代来写：

```md
## 工具
- Python 3.12+ 和 `uv`；Ruff，`line-length = 120`。
- 交付前跑 `make check`。

## 范围
- `src/app/` 是服务，`tools/` 是一次性脚本。
- `src/app/api.py` 的对外接口保持稳定。
```

命令胜过形容：“交付前跑 `make check`” 可执行，“写好代码” 不可执行。把禁区里的文件和目录写出来。存成
`<项目>/AGENTS.md`，在那个目录里启动：

```bash
zettcode -w /path/to/project
```

文件是指导，不是保证：确认那条命令真的跑过，再看 diff。它也会发给你的模型接入点，别把秘密写进去。

## 它不是什么

项目指令是内容，不是授权。它们开不了权限，也覆盖不了 ZettCode 自己的指令，所以一个克隆来的仓库没法悄悄放宽
代理能做的事。

超过 32,000 字符的文件会被截断并留下标记，而不是丢弃；读不了的文件会被安静跳过。

## 关掉它

```toml
[agents_md]
enabled = false
```

`agents_md.enabled` 在[可选参数](/zh/guide/config#可选参数参考)里，和其他开关排在一起。

## 下一步

- [工作区记忆](/zh/guide/memory)：代理在会话之间记住了什么。
- [配置](/zh/guide/config)：`config.toml` 里的每一个开关。
