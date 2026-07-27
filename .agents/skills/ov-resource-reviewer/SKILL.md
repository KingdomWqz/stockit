---
name: ov-resource-reviewer
description: 审查 OpenViking Resource 目录结构与索引质量的只读 reviewer。Use when the user asks to review, audit, check, or diagnose OpenViking Resource documents, directories, naming, dedup, or index health — produces a report only, never mutates resources.
---

# OpenViking Resource Reviewer

官方设计文档：<https://docs.volcengine.com/docs/84313/2375493?lang=zh>（页面需登录/动态渲染，若拉取不到以 `ov --help` 与子命令 `--help` 为准）。
本地工具：`ov` CLI（以 `ov --version` 实测为准，本 Skill 撰写时为 v0.4.11）。

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

> L0/L1 由系统在「新增数据」或「session 归档」时**自底向上聚合**自动生成（叶子节点先有，再聚合到父级）；多模态内容也会生成文本描述用于统一检索。其生成与一致性属系统职责，本 Skill 不审查（详见 §1）。

## 3. 审查维度 / Review Checklist

逐项检查，每项有发现则写入报告：

| 维度 | 检查点 |
|------|--------|
| **目录语义规范性** | 目录名是否承载明确业务语义？是否存在中文长后缀、临时名、`(1)`/`_copy`/`__3more_xxxx`/时间戳等自动生成痕迹？ |
| **重复资源** | 是否出现内容完全相同的重复文件（`diff` 一致），或同名带后缀的重复目录？官方现象：全量导入时同名目录已存在，系统自动建带后缀新目录，旧目录内容不完整。 |
| **目录层级与归属** | 是否挂在正确的 scope / 父目录下？一个 Resource 目录是否对应一个项目/一套文档/一个主题？命名风格是否在同一层内统一（kebab-case / 中文长名混用？）？ |
| **索引健康** | 语义/向量是否可被检索（`find` 能否命中预期关键词）？资源是否设置了显式 `set-tags`（影响显式检索命中权重）？ |
| **关系**（可选） | `relations` / `.relations.json` 是否合理、有无失效链接？ |

## 4. 审查工作流（只读命令链）

全部使用只读命令。先侦察再下结论。

```bash
# 1. 侦察：看目录树
ov tree viking://resources/<root> -L 4

# 2. 看元数据
ov ls <uri>
ov stat <uri>

# 3. 读目录摘要，判断目录语义与是否为重复资源
ov abstract <uri>      # 取目录/文件的摘要文字，用于语义对比
ov overview <uri>      # 取概览，辅助理解目录构成

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

- **本 Skill 严格只读**：只跑 `tree` / `ls` / `stat` / `abstract` / `overview` / `find` / `grep` / `glob` / `relations` / `health` / `status` / `task list` / `task status`。
- **变更命令只进报告，不进执行**：`mkdir` / `mv` / `rm` / `reindex` / `write` / `link` / `unlink` 一律只作为「建议命令」写入报告。
- **本地源文档路径不动**：连建议也只针对 OpenViking 端资源路径，不改本地文件。
- **不可逆操作加护栏**：报告里凡涉及 `rm --recursive` 的建议，必须附「先 `ov tree <uri>` 核对范围」的前置步骤提示。

## 7. 命令速查表

所有只读命令均可加 `-o json` 输出机器可读结果，便于批量比对与下游消费。

| 只读（本 Skill 可直接跑） | 变更（只在报告里建议，本 Skill 不执行） |
|---|---|
| `ov tree <uri> -L <n>` | `ov mkdir <uri> --description "<desc>"` |
| `ov ls <uri>` | `ov mv <from-uri> <to-uri>` |
| `ov stat <uri>` | `ov rm <uri> --recursive --wait` |
| `ov abstract <uri>` | `ov reindex <uri> --mode semantic_and_vectors --wait true` |
| `ov overview <uri>` | `ov wait --timeout <s>` |
| `ov find "<query>" -u <uri> [-L 0,1,2] [-n <n>] [-t <score>]` | `ov link <from-uri> [to-uri]... --reason "<text>"` |
| `ov grep "<pattern>" <uri>` | `ov unlink <from-uri> <to-uri>` |
| `ov glob "<pattern>" -u <uri>` | |
| `ov relations <uri>` | |
| `ov health` / `ov status` | |
| `ov task list` / `ov task status <id>` | |

> `find` 常用 flag：`-L 0,1,2` 限定结果层级、`-n/--node-limit` 限制返回数、`-t/--threshold` 分数阈值、`--context-type memory|resource|skill` 按类型过滤。审查「索引健康」时可用 `-L 0,1` 仅看摘要命中，节省 token。

## 8. 示例：审查 stockit/docs

以知识库 `viking://resources/stockit/docs` 为对象演示一次完整审查。

**侦察**（`ov tree viking://resources/stockit/docs -L 4`）实测结构：

```
viking://resources/stockit/docs/
├── adr/0001-sync-stocks-to-db/0001-sync-stocks-to-db.md
├── database/database-design/
│   ├── 01-architecture-and-schema.md
│   └── 03-cleanup-and-sdk.md
├── frontend-spec/frontend-spec.md
├── frontend-tasks/frontend-tasks.md
├── sql/schema.sql
├── stock-sync-spec/stock-sync-spec.md
└── stock-sync-tasks/stock-sync-tasks.md
```

**审查流程：**

1. `ov tree viking://resources/stockit/docs -L 4` 侦察整体结构。
2. `ov abstract viking://resources/stockit/docs/database/database-design` 取摘要，判断目录语义是否清晰。
3. `ov find "数据库 schema 设计" -u viking://resources/stockit/docs -L 0,1` 校验索引能否命中 `database-design/` 而非误命中旧路径。
4. `ov grep "docs/sql/schema.sql" viking://resources/stockit/docs` 检查文档内是否残留已迁移的旧路径引用。
5. `ov task list` 确认异步处理是否完成，决定结论是否需标注「索引可能未刷新」。

**报告片段**（只建议，不执行）：

```
- 维度：目录层级与归属
- URI：viking://resources/stockit/docs
- 现状：docs/ 下混合 adr/database/frontend-spec/frontend-tasks/sql/stock-sync-spec/stock-sync-tasks
  七个并列主题目录，未按「需求/设计/接口/任务」等语义分组
- 风险：主题并列难以体现文档间关系（如 spec 与 tasks 的配对），随文档增长更难导航
- 建议（需维护流程执行）：按 prd/design/api/schema/tasks 等主题二级分组，
  例如 ov mv .../stock-sync-spec .../prd/stock-sync-spec

- 维度：索引健康
- 现状：ov find "数据库 schema 设计" 命中 database-design/，未命中旧路径
- 结论：索引已刷新，无需 ov wait

## 已通过校验项（无问题）
- viking://resources/stockit/docs/database/database-design：目录语义清晰、无重复
- viking://resources/stockit/docs/adr/0001-sync-stocks-to-db：命名规范、归属正确
```

> 上述「建议」仅为示例形态，实际结论以审查时实测为准；本 Skill 绝不执行 `ov mv`，只写入报告。
