# 整理 docs/ 目录结构（四层知识模型）

## 目标

按更新后的 `项目知识库设计.md` 四层知识模型重组 `docs/`：
- `team-rule/` (Layer 0-T)、`team-tech/` (Layer 1)：stockit docs/ 无此类内容，**不建**
- `business/{domain}/` (Layer 2)：仅 CONTEXT.md 业务术语表 → `business/a-stock/`
- `projects/{app}/` (Layer 3)：其余全部项目文档 → `projects/stockit/`

## 目标结构

```
docs/
├── business/
│   └── a-stock/                          # Layer 2 业务知识：A股领域
│       ├── .abstract.md                  # 新建 L0
│       ├── .overview.md                  # 新建 L1
│       └── glossary/
│           └── CONTEXT.md                # Stock/Market/Active/Inactive 术语表
│
└── projects/
    └── stockit/                          # Layer 3 项目知识
        ├── .abstract.md                  # 新建 L0
        ├── .overview.md                  # 新建 L1
        ├── prd/                          # 需求文档
        │   ├── stock-sync-spec.md
        │   ├── daily-quotes-sync-plan.md
        │   └── frontend-spec.md
        ├── design/                       # 系统设计
        │   ├── architecture.md
        │   ├── daily-job-flow.md
        │   ├── adr/
        │   │   └── 0001-sync-stocks-to-db.md
        │   └── database-design/          # 由 database.md 拆分
        │       ├── 01-architecture-and-schema.md   # §1+§2
        │       └── 03-cleanup-and-sdk.md           # §3+§4
        ├── api/                          # 接口契约
        │   └── api-contract.md
        ├── schema/                       # DDL
        │   └── schema.sql                # 原 docs/sql/schema.sql
        ├── changelog/                    # 任务清单/交付追踪
        │   ├── stock-sync-tasks.md
        │   ├── daily-quotes-sync-tasks.md
        │   └── frontend-tasks.md
        └── incidents/                    # 试点结论/基准报告
            └── daily-quotes-sync-benchmark.md
```

## 步骤

1. **移动文件**（`git mv` 保留历史）
   - `CONTEXT.md` → `business/a-stock/glossary/CONTEXT.md`
   - `architecture.md` → `projects/stockit/design/architecture.md`
   - `daily-job-flow.md` → `projects/stockit/design/daily-job-flow.md`
   - `adr/0001-sync-stocks-to-db.md` → `projects/stockit/design/adr/0001-sync-stocks-to-db.md`
   - `api-contract.md` → `projects/stockit/api/api-contract.md`
   - `sql/schema.sql` → `projects/stockit/schema/schema.sql`
   - `stock-sync-spec.md` → `projects/stockit/prd/stock-sync-spec.md`
   - `daily-quotes-sync-plan.md` → `projects/stockit/prd/daily-quotes-sync-plan.md`
   - `frontend-spec.md` → `projects/stockit/prd/frontend-spec.md`
   - `stock-sync-tasks.md` → `projects/stockit/changelog/stock-sync-tasks.md`
   - `daily-quotes-sync-tasks.md` → `projects/stockit/changelog/daily-quotes-sync-tasks.md`
   - `frontend-tasks.md` → `projects/stockit/changelog/frontend-tasks.md`
   - `daily-quotes-sync-benchmark.md` → `projects/stockit/incidents/daily-quotes-sync-benchmark.md`
   - 移动后删除空目录 `docs/sql/`、`docs/adr/`（git mv 后自动空）

2. **拆分 `database.md`** → `projects/stockit/design/database-design/`
   - `01-architecture-and-schema.md`：标题 + 引言 + §1 存储架构 + §2 Schema 与索引 SQL
   - `03-cleanup-and-sdk.md`：§3 清理存储过程 + §4 SDK 模块（无 H1，与知识库一致）
   - 拆分后删除原 `database.md`

3. **修正内部交叉引用**（移动后路径变化，统一用相对路径 `../`）
   - `design/architecture.md`「相关文档」段：
     - `./api-contract.md` → `../api/api-contract.md`
     - `./database.md` → `./database-design/01-architecture-and-schema.md`
     - `./sql/schema.sql` → `../schema/schema.sql`
     - `./frontend-spec.md` → `../prd/frontend-spec.md`
     - `./stock-sync-spec.md` → `../prd/stock-sync-spec.md`
     - `./adr/0001-sync-stocks-to-db.md` → `./adr/0001-sync-stocks-to-db.md`（同 design/ 下，不变）
     - 正文 `docs/frontend-spec.md`/`docs/stock-sync-spec.md`/`docs/sql/schema.sql` 字面引用改为新路径
   - `api/api-contract.md`「相关文档」段：
     - `./architecture.md` → `../design/architecture.md`
     - `./database.md` → `../design/database-design/01-architecture-and-schema.md`
     - `./sql/schema.sql` → `../schema/schema.sql`
     - `./frontend-spec.md` → `../prd/frontend-spec.md`
     - `./stock-sync-spec.md` → `../prd/stock-sync-spec.md`
     - 正文 `docs/frontend-spec.md` 字面引用改路径
   - `prd/frontend-spec.md`：`[frontend-tasks.md](./frontend-tasks.md)` → `../changelog/frontend-tasks.md`
   - `changelog/stock-sync-tasks.md`：`docs/stock-sync-spec.md` → `../prd/stock-sync-spec.md`
   - `changelog/daily-quotes-sync-tasks.md`：`docs/daily-quotes-sync-plan.md` → `../prd/daily-quotes-sync-plan.md`；`docs/sql/schema.sql` → `../schema/schema.sql`
   - `prd/daily-quotes-sync-plan.md`：`docs/sql/schema.sql` → `../schema/schema.sql`
   - `prd/stock-sync-spec.md`：`docs/sql/schema.sql` → `../schema/schema.sql`
   - `incidents/daily-quotes-sync-benchmark.md`：`docs/database.md` → `../design/database-design/01-architecture-and-schema.md`；`docs/daily-quotes-sync-plan.md` → `../prd/daily-quotes-sync-plan.md`

4. **修正仓库内引用**
   - `server/tests/test_db_client_upsert_daily_quotes.py`、`server/tests/test_stocks_daily_quotes_sync.py`：注释里 `docs/daily-quotes-sync-plan.md` → `docs/projects/stockit/prd/daily-quotes-sync-plan.md`
   - `README.md` 第 17 行 `docs/` 说明：保持（仍准确）
   - `AGENTS.md` 第 20 行：保持

5. **新建索引文件**（设计文档要求 L0/L1）
   - `docs/business/a-stock/.abstract.md`：一句话说明 A股领域知识库
   - `docs/business/a-stock/.overview.md`：glossary 用途、建议阅读
   - `docs/projects/stockit/.abstract.md`：一句话说明 Stockit 项目知识库
   - `docs/projects/stockit/.overview.md`：各子目录导航 + 建议阅读顺序

6. **验证**：`git status`、`find docs` 核对结构、`grep` 残留旧路径（`docs/sql`、`docs/database.md`、`docs/frontend-spec` 等）、确认无断链

## 不做的事
- 不建空的 `team-rule/`、`team-tech/`（无内容，待将来有团队级内容再补）
- 不改动知识库 viking:// 资源（仅整理本地仓库）
- 不拆分 database.md 以外的单文件文档
- adr 保持扁平（`design/adr/0001-...`），不采用每文档一目录
- CONTEXT.md 文件名保留（维持 git 历史），不重命名为 domain-terms.md
