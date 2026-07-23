---
name: organize-openviking-resources
description: 整理 OpenViking Resource 资源的工作流技能。Use when the user asks to organize, merge, rename, deduplicate, verify, or maintain OpenViking Resource documents, directories, indexes, or resource metadata.
---

# Organize OpenViking Resources

核心思路：把上下文当作文件系统来管理

- 统一资源管理：​每一份上下文和资源都有稳定的 URI 路径与归属，通过明确的目录组织，将分散的记忆、技能和数据整合进统一的目录树中。
- 显式语义边界：​每一个目录都表达一个明确的语义边界与上层任务关联，让 Agent 在命中局部内容时，能知晓其所属的项目、主题和上下文结构。
- 可追溯的渐进路由：每一次读取都遵循 “路径定位 - 目录理解 - 详情展开” 的渐进式跳转，检索结果能追溯到具体文件和父级目录。
- 按需加载的目录边界：依托 L0（摘要），L1（概览），L2（细节）的分层结构与目录边界实现按需精准读取，解决非必要 Token 的浪费。

Resource下的一个资源目录可以表示一个项目、一套文档或一个主题

例如：
viking://resources/payments/
├── .abstract.md
├── .overview.md
├── .relations.json
├── prd/
├── api/
└── faq/

这里的 payments/prd； payments/api 目录本身携带了明确的业务语义，当 Agent 当检索命中某个子文件时，能知道它在整体路径中的明确位置，通过对 L1 的快速阅读，判断是否值得展开读取。当目录之间存在关联关系时，系统可以据此递归扩展相关上下文:

L0 / .abstract.md：用一句话到一小段话回答“这是什么”
L1 / .overview.md：回答“里面大概有什么、重点是什么、建议先看哪里”
L2 / 原始文件和子目录：提供完整详情，供真正需要时再深入读取


- 项目整体设计文档
- 团队技术规范
- QA测试用例
- 接口契约
- 某个业务领域

目录本身携带了明确的业务语义，当 Agent 当检索命中某个子文件时，能知道它在整体路径中的明确位置，通过对 L1 的快速阅读，判断是否值得展开读取。当目录之间存在关联关系时，系统可以据此递归扩展相关上下文:

L0 / .abstract.md：用一句话到一小段话回答“这是什么”
L1 / .overview.md：回答“里面大概有什么、重点是什么、建议先看哪里”
L2 / 原始文件和子目录：提供完整详情，供真正需要时再深入读取
普通文件夹中，Agent 实际上只能“看到文件名”，很难快速理解这个目录的主题、重点和阅读路径
