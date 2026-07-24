---
name: ov-resource-reviewer
description: 审查 OpenViking Resource 目录结构与索引质量的只读 reviewer。Use when the user asks to review, audit, check, or diagnose OpenViking Resource documents, directories, naming, dedup, or index health — produces a report only, never mutates resources.
---

# OpenViking Resource Reviewer

官方设计文档：<https://docs.volcengine.com/docs/84313/2375493?lang=zh>
本地工具：`ov` CLI（v0.4.9）。

## 1. 角色 / Role

本 Skill 是 OpenViking **Resource 的 reviewer**：对 `viking://resources/...` 下的目录结构、命名、重复、层级归属、索引健康做**只读审查**，输出一份**审查报告**。

- **只出报告，不动手**：本 Skill 绝不执行任何变更命令（`mv` / `rm` / `mkdir` / `reindex` / `write` / `link` / `unlink`）。这些命令只作为「建议」写入报告，由用户或维护流程执行。
- **不做检索**：纯粹的 `find`/`search` 语义检索不归本 Skill；本 Skill 用 `find`/`grep` 仅作为「校验索引是否可被命中」的诊断手段。
- **不审 L0/L1**：resource 下每级目录的 L0（`.abstract.md`）和 L1（`.overview.md`）由 ov 在「新增数据」或「session 归档」时**自底向上聚合自动生成与维护**，属系统行为，**不在本 Skill 审查范围内**。本 Skill 不检查 L0/L1 是否生成、内容是否一致、是否漂移——这些由系统负责。

## 2. 核心设计理念（来自官方文档）

把上下文当作文件系统来管理，是审查的判断依据：

- **统一资源管理**：`viking://{scope}/{path}`。四个 scope：`resources/`（外部知识与规则）、`user/`（关于用户的长期认知）、`agent/`（技能与经验）、`session/`（临时与归档上下文）。路径 = 稳定标识，目录 = 语义边界，文件 = 内容单元。
- **显式语义边界**：目录名本身携带明确业务语义（如 `payments/prd`、`payments/api`）。一个 Resource 目录代表一个项目 / 一套文档 / 一个主题。
- **可追溯渐进路由**：读取遵循「路径定位 → 目录理解(L1) → 详情展开(L2)」，检索结果可追溯到具体文件与父级目录。
- **按需加载 L0/L1/L2**：
  - L0 `.abstract.md`（~100 token）：一句话到一小段回答「这是什么」，用于向量检索与快速过滤。
  - L1 `.overview.md`（~1k–2k token）：回答「里面大概有什么、重点是什么、建议先看哪里」，用于 rerank 与导航。
  - L2 原始文件与子目录：完整详情。
  - ⚠️ **L0/L1 由系统自动生成维护，不在审查范围**：这些特殊文件在「新增数据」或「session 归档」时由系统**自底向上聚合**自动生成（叶子节点先有，再聚合到父级）；多模态内容（图片/视频）也会生成文本描述用于统一检索。本 Skill 不审查 L0/L1 的生成与一致性。

## 3. 审查维度 / Review Checklist

逐项检查，每项有发现则写入报告：

| 维度 | 检查点 |
|------|--------|
| **目录语义规范性** | 目录名是否承载明确业务语义？是否存在中文长后缀、临时名、`(1)`/`_copy`/`__3more_xxxx`/时间戳等自动生成痕迹？ |
| **重复资源** | 是否出现内容完全相同的重复文件（`diff` 一致），或同名带后缀的重复目录？官方现象：全量导入时同名目录已存在，系统自动建带后缀新目录，旧目录内容不完整。 |
| **目录层级与归属** | 是否挂在正确的 scope / 父目录下？一个 Resource 目录是否对应一个项目/一套文档/一个主题？命名风格是否在同一层内统一（kebab-case / 中文长名混用？）？ |
| **索引健康** | 语义/向量是否可被检索（`find` 能否命中预期关键词）？资源是否设置了显式 `set-tags`（影响显式检索命中权重）？ |
| **关系**（可选） | `relations` / `.relations.json` 是否合理、有无失效链接？ |

> ❌ **不在审查范围**：L0 `.abstract.md` / L1 `.overview.md` 的生成、内容、一致性、漂移——这些由 ov 系统自动维护，本 Skill 不审查。`ov abstract` / `ov overview` 仅作为读取手段用于判断**目录语义**与**重复资源**，不用于评估 L0/L1 本身的健康度。

## 4. 审查工作流（只读命令链）

全部使用只读命令。先侦察再下结论。

```bash
# 1. 侦察：看目录树
ov tree viking://resources/<root> -L 4

# 2. 看元数据
ov ls <uri>
ov stat <uri>

# 3. 读目录摘要，判断目录语义与是否为重复资源（不评估 L0/L1 健康度）
ov abstract <uri>      # 取目录/文件的摘要文字，用于语义对比
ov overview <uri>      # 同上，用于辅助理解

# 4. 定位内容重复（文件级 diff 判断是否冗余副本）
ov find "<主题>" -u <uri>
ov grep "<pattern>" <uri>

# 5. 校验索引是否可被命中
ov find "<关键词>" -u <uri>

# 6. 查关系
ov relations <uri>

# 7. 后端健康与异步任务状态（影响索引可信度）
ov health
ov status
ov task list
```

> **读取预算**：遵循 L0 → L1 → L2 的渐进加载。先扫多个目录的摘要文字过滤，再读最相关的 overview，最后才按需 read L2 原文，避免直接全量读 L2 浪费 token。

> **异步状态提示**：若 `ov task list` 显示有未完成的异步处理，索引可能尚未刷新，此时审查结论必须标注「索引可能未刷新，建议 `ov wait` 后再审」。

> **不审 L0/L1**：上面的 `ov abstract` / `ov overview` 仅是**读取手段**，用于对比目录语义和发现重复资源；**不要**评估 `.abstract.md` / `.overview.md` 是否生成、是否漂移、是否一致——这是系统职责。

## 5. 审查报告格式 / Report Format

固定输出结构，便于人读与下游流程消费：

```
# OpenViking Resource 审查报告

## 概述
- 审查根 URI：viking://resources/...
- 范围：...
- 基线：（实测，省略时间戳则注明）

## 问题清单
每条：
- 维度：<目录语义/重复资源/层级归属/索引健康/关系>
  （注意：L0/L1 不在维度列表内，系统自动维护，不予审查）
- URI：viking://...
- 现状：...
- 风险：...
- 建议（只建议，不执行）：<ov 命令，需用户/维护流程执行>
  - 若涉及 rm --recursive，附「先 ov tree <uri> 核对范围」前置步骤

## 已通过校验项（无问题）
- <URI>：<通过的维度>

## 索引 / 异步状态
- ov task list / ov health 结论
- 是否需等待刷新后再审
```

> **避免沉默即成功**：必须列出「已通过校验项」，否则无问题项与「没查」无法区分。

## 6. 不可变边界与安全约定

- **本 Skill 严格只读**：只跑 `tree` / `ls` / `stat` / `abstract` / `overview` / `find` / `grep` / `glob` / `relations` / `health` / `status` / `task list`。
- **变更命令只进报告，不进执行**：`mkdir` / `mv` / `rm` / `reindex` / `write` / `link` / `unlink` 一律只作为「建议命令」写入报告。
- **本地源文档路径不动**：连建议也只针对 OpenViking 端资源路径，不改本地文件。
- **不可逆操作加护栏**：报告里凡涉及 `rm --recursive` 的建议，必须附「先 `ov tree <uri>` 核对范围」的前置步骤提示。

## 7. 命令速查表

| 只读（本 Skill 可直接跑） | 变更（只在报告里建议，本 Skill 不执行） |
|---|---|
| `ov tree <uri> -L <n>` | `ov mkdir <uri> --description "<desc>"` |
| `ov ls <uri>` | `ov mv <from-uri> <to-uri>` |
| `ov stat <uri>` | `ov rm <uri> -r --recursive --wait` |
| `ov abstract <uri>`（取摘要，判断语义/重复，不审 L0 健康度） | `ov reindex <uri> --mode semantic_and_vectors --wait true` |
| `ov overview <uri>`（取概览，辅助判断，不审 L1 健康度） | `ov wait --timeout <s>` |
| `ov find "<query>" -u <uri>` | `ov link <from-uri> [to-uri]... --reason "<text>"` |
| `ov grep "<pattern>" <uri>` | `ov unlink <from-uri> <to-uri>` |
| `ov glob "<pattern>" -u <uri>` | |
| `ov relations <uri>` | |
| `ov health` / `ov status` | |
| `ov task list` | |

## 8. 示例：审查 stockit/docs

实测当前状态（审查基线）：

```
viking://resources/stockit/docs/
├── adr/0001-sync-stocks-to-db/
├── database/股票指标数据库设计与维护技术文档_Supabase_个人本地版/   ← 带中文长后缀
├── frontend-spec/frontend-spec.md
├── frontend-tasks/frontend-tasks.md
├── sql/schema.sql
├── stock-sync-spec/stock-sync-spec.md
└── stock-sync-tasks/stock-sync-tasks.md
```

审查流程：

1. `ov tree viking://resources/stockit/docs -L 4` 侦察。
2. `ov abstract viking://resources/stockit/docs/database/股票指标...个人本地版` 取摘要文字，判断目录语义与是否为重复资源（不评估 L0 健康度）。
3. `ov find "数据库设计" -u viking://resources/stockit/docs` 看是否同时命中重复的两份。

报告片段（只建议，不执行）：

```
- 维度：目录语义规范性
- URI：viking://resources/stockit/docs/database/股票指标数据库设计与维护技术文档_Supabase_个人本地版
- 现状：目录名含中文长后缀「_Supabase_个人本地版」，疑似导入时自动生成
- 风险：目录名不承载简洁业务语义，检索命中后难以快速定位所属
- 建议（需维护流程执行）：ov mv <该 URI> viking://resources/stockit/docs/database/schema-design

- 维度：索引 / 异步状态
- ov task list 结论：<填入实测>
- 若有未完成任务：建议 ov wait 后再审
```
