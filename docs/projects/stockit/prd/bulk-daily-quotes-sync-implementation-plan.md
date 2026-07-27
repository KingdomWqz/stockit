# 全市场基础行情批量入库接口 实施计划

## Context（背景与动机）

本项目（选股器 Stockit）已实现**单股**基础行情入库接口 `POST /svc/api/stocks/{code}/daily-quotes/sync`（PRD: `docs/projects/stockit/prd/daily-quotes-sync-plan.md`，标题即「基础行情入库 API 实施计划」）。该 PRD §7 明确将「全市场批量同步」列为**不做范围**，§8「后续扩展」将「全市场批量入库」列为紧接着的下一步。

本次需求「增加一个拉取基础行情数据的接口，全量股票的」即对应 PRD §8 这一下一步：把现有单股 qfq 日线同步扩展为**全市场批量**版本，复用同一张 `stock_daily_quotes` 表与同一套 `upsert_daily_quotes` 写库逻辑，对 `stocks` 表中全部活跃股票批量拉取并入库。

> 项目自有词汇界定（消除歧义的关键依据）：`schema.sql` 表注释「由基础行情入库 API 写入」+ PRD 标题「基础行情入库 API」→ 在本项目里「基础行情」= qfq 日线 OHLCV（存于 `stock_daily_quotes`），**不是**实时现价快照。故本计划不复用 `ak.stock_zh_a_spot_em`，也不新增 spot 表。

### 用户已确认的两项设计决策

1. **日期范围**：复用 `start_date`/`end_date`（必填、`start≤end`、且 `end - start ≤ 5 天`），作用于全部活跃股票。日常盘后刷新把两个日期都传当天；历史回补分 ≤5 天/批多次触发。**新增** `BulkDailyQuotesSyncRequest`（镜像 `DailyQuotesSyncRequest` 校验 + 5 天上限），不复用单股模型以免把上限强加给单股端点。零新 schema。
2. **执行模型**：后台任务立即返回 `202 + job_id`，新增 `GET` 状态端点轮询进度。全市场单日约 5–10 分钟（直连 akshare、并发 4、无 HTTP 跳），不宜阻塞 HTTP 请求。

## 设计概览

```text
POST /svc/api/stocks/daily-quotes/sync  {start_date, end_date}
      |  (JWT, 复用 DailyQuotesSyncRequest)
      v
生成 job_id，登记 _BULK_JOBS[job_id]=pending
      |
      +-- BackgroundTasks.add_task(_run_bulk_sync, job_id, start, end)
      |
      `-- 立即返回 202 {job_id, status:"pending", status_url}

后台任务 _run_bulk_sync(job_id, start, end):
      |
      +-- db_client.get_active_stock_codes()   # 分页读 stocks where is_active=true
      +-- ThreadPoolExecutor(max_workers=4) 逐股:
      |       symbol = _sina_prefix(code) + code
      |       重试2次(线性退避) ak.stock_zh_a_daily(symbol, start, end, adjust="qfq")
      |       db_client.upsert_daily_quotes(df, code, adjust="qfq")  # 复用,不改
      |       累加 upserted/empty/failed，每500只回写一次进度(加锁)
      `-- 收尾: status=completed, failed_codes=[...], elapsed_ms

GET /svc/api/stocks/daily-quotes/sync/{job_id}  → 读 _BULK_JOBS 返回快照
```

**关键约束**：无新表、无 schema 变更（`stock_daily_quotes` 已就绪，`upsert_daily_quotes` 已处理 `volume`→`int` 的 BIGINT `22P02` 问题，直接复用）。复用 `stocks.py` 既有 `_sina_prefix`、`_DAILY_QUOTES_ADJUST="qfq"`、`DailyQuotesSyncRequest`。

## 新增端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/svc/api/stocks/daily-quotes/sync` | 创建批量任务，返回 202 |
| GET | `/svc/api/stocks/daily-quotes/sync/{job_id}` | 查询任务状态 |

> 路径无冲突：现有 4 段路由是 `POST /stocks/{code}/daily-quotes/sync`；新 3 段 `POST /stocks/daily-quotes/sync` 与现有 3 段 `GET /stocks/{code}/kline` 第三段不同（`sync`≠`kline`），且方法/段数均不撞。JWT 鉴权沿用 `main.py:18` 路由级 `Depends(get_current_user)`，无需逐路由加。

**请求体**（新增 `BulkDailyQuotesSyncRequest`，镜像 `DailyQuotesSyncRequest`(`stocks.py:43-56`) 的 `start≤end` 校验 + 增 `end - start ≤ 5 天` 校验，违例→422）：
```json
{ "start_date": "2026-07-24", "end_date": "2026-07-24" }
```

**202 响应**：
```json
{ "job_id": "<hex>", "status": "pending",
  "status_url": "/svc/api/stocks/daily-quotes/sync/<job_id>" }
```

**状态响应**（GET，未知 job_id → 404）：
```json
{ "job_id": "...", "status": "running|completed|failed",
  "start_date": "2026-07-24", "end_date": "2026-07-24",
  "total_stocks": 5530, "upserted": 5524, "empty": 5, "failed": 1,
  "failed_codes": ["689009"], "started_at": "...", "finished_at": "...",
  "elapsed_ms": 283000, "error": null }
```

部分失败语义：单股 akshare/DB 异常**不**让整个任务 500，计入 `failed`+`failed_codes`，其余继续（对标 benchmark 实测：5530 中 6 只缺失为暂停/北交所）。`empty` = akshare 返回空（暂停股）。

## 文件改动

### 1. `server/db_client.py` — 新增活跃代码读取helper
仿照 `scripts/bench_daily_quotes_sync.py:35-47` 的分页 select，新增：
```python
def get_active_stock_codes(batch_size: int = 1000) -> list[str]:
    # client.table("stocks").select("code").eq("is_active", True)
    # 分页 .range(offset, offset+batch-1) 直至无更多；返回去重后的 code 列表
```
复用 `get_client()` 单例。`upsert_daily_quotes`（`db_client.py:180-230`）**不改**。

### 2. `server/stocks.py` — 新增批量端点 + 后台任务
- 顶部加 `import`：`from fastapi import BackgroundTasks`、`import threading`、`from dataclasses import dataclass, field`、`from uuid import uuid4`、`from concurrent.futures import ThreadPoolExecutor, as_completed`、`import time`。
- 模块级常量：`_BULK_CONCURRENCY = 4`、`_BULK_RETRIES = 2`、`_BULK_PROGRESS_EVERY = 500`。
- 模块级 `_BULK_JOBS: dict[str, BulkSyncJob] = {}` + `_BULK_JOBS_LOCK = threading.Lock()`。
- `@dataclass BulkSyncJob`：字段如上状态响应（`job_id, status, start_date, end_date, total_stocks, upserted, empty, failed, failed_codes, started_at, finished_at, elapsed_ms, error`）。
- 新增 `BulkDailyQuotesSyncRequest(BaseModel)`：字段 `start_date`/`end_date`（`date`），`@model_validator(mode="after")` 校验 `start≤end` 且 `(end-start).days ≤ 5`，违例 `ValueError`→422。**不复用** `DailyQuotesSyncRequest`，避免把 5 天上限强加给单股端点。
- `_run_bulk_sync(job_id, start_date, end_date)`：整体 try/except 兜底（置 `status="failed"`+`error`，永不冒泡杀进程）；内部 `ThreadPoolExecutor(max_workers=_BULK_CONCURRENCY)`，逐股 worker 逻辑镜像单股端点（`_sina_prefix`+`ak.stock_zh_a_daily(adjust=_DAILY_QUOTES_ADJUST)`+`db_client.upsert_daily_quotes`），含 2 次线性退避重试（`time.sleep(1.0*(attempt+1))`，对标 bench 脚本 `:81-103`）；每完成 `_BULK_PROGRESS_EVERY` 只在锁内回写 `_BULK_JOBS[job_id]` 进度。
- `@router.post("/stocks/daily-quotes/sync")` `def sync_bulk_daily_quotes(body: BulkDailyQuotesSyncRequest, background_tasks: BackgroundTasks)`：生成 `job_id=uuid4().hex`，登记 pending，`background_tasks.add_task(_run_bulk_sync, job_id, body.start_date, body.end_date)`，返回 202 + `status_url`。
- `@router.get("/stocks/daily-quotes/sync/{job_id}")` `def get_bulk_sync_status(job_id: str)`：查 `_BULK_JOBS`，无则 404，有则返回快照 dict。

> 实现注记：选用 FastAPI `BackgroundTasks`（用户已选）。任务在 `def`（非 async）端点的线程池里跑；单任务占用一个线程池 worker ~5–10 分钟，对个人单用户工具可接受。若实测遇线程池压力，可改 `threading.Thread(daemon=True)` 启动（语义等价）。**任务态存于进程内存**，进程重启即丢——本计划接受此权衡（个人手动触发场景）。

### 3. 测试 `server/tests/test_stocks_bulk_daily_quotes_sync.py`（新增，仿 `test_stocks_daily_quotes_sync.py`）
- 401 未携带 token。
- 422 日期倒置；422 区间超 5 天（如 `start` 与 `end` 相差 6 天）。
- POST 返回 202、含 `job_id` 与 `status_url`；后台任务（mock `_run_bulk_sync` 或直接 mock akshare+db）跑完后状态 `completed`。
- GET 未知 job_id → 404；已知 → 返回 running/completed 统计。
- happy path：mock `get_active_stock_codes`→`["600519","000001"]`，mock `ak.stock_zh_a_daily` 返回小 df，mock `upsert_daily_quotes`；断言逐股调用、最终 `upserted=2`。
- 部分失败：一股 akshare 持续抛错→进 `failed_codes`，另一股成功，状态 `completed`。
- 空数据：akshare 返回空 df→`empty` 计数、`upserted=0`。
- 回归：单股 `POST /stocks/{code}/daily-quotes/sync` 与 `/stocks/sync` 不受影响。
- `server/tests/test_db_client*.py` 增 `get_active_stock_codes` 分页 + `is_active=True` 过滤用例（用 `fake_db` fixture，仿 `conftest.py:158-163`）。

> 记忆提示（`fakeclient-misses-postgres-types.md`）：FakeClient 抓不到 Postgres 类型错误。本计划**未新增表/列**、`upsert_daily_quotes` 已处理 `volume` BIGINT 强转，故类型风险低；但全量入库路径仍需**真实 Supabase 联调**冒烟（见验证）。

### 4. 文档（仿现有 daily-quotes 文档结构，四层知识模型）
- **ADR**：`docs/projects/stockit/design/adr/0002-bulk-daily-quotes-sync.md` — 决策：复用 `stock_daily_quotes`+`upsert_daily_quotes`（不开新表）、后台执行 + 进程内任务态、并发4+重试、部分失败聚合、内存态重启丢失权衡。
- **Spec**：`docs/projects/stockit/prd/bulk-daily-quotes-sync-plan.md` — 镜像 `daily-quotes-sync-plan.md` 八节结构（目标/API设计/数据库设计(无新表)/后端实现/测试计划/与单股接口协同/不做范围/后续扩展）。§数据库设计 明确「不新增表，复用 `stock_daily_quotes`」。
- **Tasks**：`docs/projects/stockit/changelog/bulk-daily-quotes-sync-tasks.md` — Phase 1 后端 fan-out+任务态 / Phase 2 API 路由(POST+GET) / Phase 3 测试 / Phase 4 端到端 / 完成标准，每任务 `TS N.N` + 修改文件 + **验证**。
- **更新**：`docs/projects/stockit/api/api-contract.md` 增补上述两端点（请求/响应/错误语义 202/404/422/401/502/500）。
- PRD `daily-quotes-sync-plan.md` §8 不改（新 spec 即其后续扩展的落地）。

## 不做范围

- 不新增数据库表/列、不动 schema。
- 不做定时调度/cron/队列（沿用「手动触发」语义，与 PRD §7 一致）。
- 不做前端入口（现有 `POST /stocks/sync`、单股 daily-quotes/sync 均无前端触发 UI，`web/src/hooks/use-stocks.ts` 未调用任何 sync 端点——保持一致）。
- 不做实时现价 spot 同步（`ak.stock_zh_a_spot_em`）——非本需求。
- 不做 `stock_daily_quotes` 滚动清理（benchmark 报告曾提议，独立议题，不在本次）。

## 风控与使用建议

- **调用次数与日期跨度无关**：`ak.stock_zh_a_daily` 按股票调用，一次返回该股区间内全部日线；全市场调用次数恒为活跃股票数（~5500），多日不增风控压力。
- **benchmark 实测结论**：并发 8 出现的是 Supabase PostgREST HTTP 断连（多为虚假 500），非 sina/akshare 风控；并发 ≤4 + 2 次重试稳定。未观测到数据源限流。
- **多日的真实代价**：写入行数/磁盘/耗时线性增长（1 天 ≈ 5500 行 ≈ 1.34 MB）。
- **使用建议**：日常盘后用单日（`start=end=当天`）刷新；历史回补分小批次（每次 ≤5 天）触发多个 job，分散密度并缩短单任务时长。
- **护栏（必做）**：`end - start ≤ 5 天`，由 `BulkDailyQuotesSyncRequest` 校验、超限返回 422；防误触发超长/超重批量任务。
- **不确定性**：benchmark 仅测单日；极长区间（如数年）行为需小范围冒烟验证后再大范围跑。

## 验证（端到端）

1. **单测**：`cd server && uv run pytest -q`（新增测试 + 回归全绿）。
2. **起服务**：`cd server && uv run uvicorn main:app --reload`（前端反代 `next.config.ts` 已把 `/svc/api/*`→`127.0.0.1:8000`）。
3. **前置**：先 `POST /svc/api/stocks/sync`（Bearer token）确保 `stocks` 表有活跃代码（FK 依赖）。
4. **触发批量**：
   ```bash
   curl -X POST /svc/api/stocks/daily-quotes/sync \
     -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
     -d '{"start_date":"2026-07-24","end_date":"2026-07-24"}'
   # 期望 202 + {job_id, status:"pending", status_url}
   ```
5. **轮询**：`GET /svc/api/stocks/daily-quotes/sync/<job_id>` 直至 `status=completed`，核对 `upserted/empty/failed/failed_codes` 合理。
6. **真实 Supabase 冒烟**（用 MCP `execute_sql` 或 SQL Editor）：
   ```sql
   select count(*), count(distinct code) from stock_daily_quotes
   where trade_date='2026-07-24';
   -- 期望 ~5500（与 benchmark 5524 量级一致）
   ```
7. **错误路径**：传 `start_date>end_date`→422；传 6 天跨度→422；不带 token→401；伪造 job_id→404。
