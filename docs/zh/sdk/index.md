---
title: ZettCode SDK
---

# ZettCode SDK

ZettCode SDK 让你在 Python 程序里直接驱动编码 agent，不需要终端。终端应用能做的一切——运行 prompt、流式获取进度、回答审批、管理会话、切换模型、压缩上下文、导出——都能在代码里完成，背后是同一个 agent、同一套工具、插件、MCP 服务器、skills 和项目指令。

## 它能做什么

```python
import zettcode.sdk as zc

result = await zc.prompt("fix the failing test", workspace=".", permission="safe")
print(result.text)
```

- **运行 prompt**，直接拿结果，或者按事件流式接收进度
- **回答审批和提问**：用处理函数，或者直接在事件上作答
- **管理会话**：新建、继续、分叉、导出、读取历史
- **在对话中途切换模型和权限级别**
- **从中断处恢复请求**
- **以编程方式压缩上下文、度量上下文、查看用量**

同一个会话可以在代码里开始、在终端里继续，反过来也一样——SDK 用的是同一个会话存储。

## 适合谁

- 需要无人值守运行 agent 的**脚本**：测试夹具、CI 流水线、批处理
- 嵌入 ZettCode 的**工具**：编辑器、IDE、自动化框架
- 想要 agent 但不想要终端界面的**自定义 UI**
- 把对话当作数据的**研究与实验**

## 安装

```bash
pip install zettcode
```

SDK 是 `zettcode` 包的一部分。导入它几乎没有开销，agent 在创建 client 时才加载。

```python
import zettcode.sdk as zc
```

## 第一步

- [**快速上手**](./quickstart)：一次 prompt、一段对话、流式进度
- [**核心概念**](./concepts)：client、session、run、event 如何配合
- [**Client 与配置**](./client)：模型、设置、工作区

## 使用指南

- [**运行 Prompt**](./running)：`prompt()`、`run()`、`stream()` 及其返回值
- [**事件流**](./events)：`TextDelta`、`ToolStarted`、`ApprovalRequested` 等
- [**审批与提问**](./approvals)：处理函数、就地作答、权限级别
- [**会话**](./sessions)：创建、切换、分叉、历史、导出
- [**错误与超时**](./errors)：哪里会抛什么、如何重试、部分结果

## 示例

[**示例集**](./cookbook) 给出完整的程序：

- 带审批规则的无人值守脚本
- 进度显示与实时输出
- 多会话工作流
- 错误处理与重试
- 与现有代码集成

## 参考

[**API 参考**](./reference)：每个类、方法和属性

## 与终端的主要差别

- **默认不连 broker**：`sessions_enabled=False`，终端会话无法给 SDK client 发消息
- **不检查新版本**：`update_enabled=False`
- **工作目录**：创建 client 会把工作目录切到工作区，关闭最后一个 client 时恢复
- **一个进程一个工作区**：两个不同工作区的 client 不能同时打开

## 下一步

先看[**快速上手**](./quickstart)了解 SDK 的实际用法，再读[**核心概念**](./concepts)理解各部分如何配合。
