# Stockit 全市场基础行情批量入库任务清单

对应需求文档:`../prd/bulk-daily-quotes-sync-plan.md`。每个任务 = 一个 MR,独立可验证。

---

## Phase 1:数据库 helper

### TS1.1 新增 `get_active_stock_codes` 函数
- 修改 `server/db_client.py`
- 新增 `get_active_stock_codes(batch_size=1000) -> list[str]`:
  1. `client.table("stocks").select("code").eq("is_active", True).range(offset, offset+batch_size-1).execute()` 分页
  2. 逐页收集 `code`,当某页行数 < `batch_size` 时停止
  3. 去重保序返回
- 复用 `get_client()` 单例;**不触碰** `upsert_daily_quotes` / `stock_daily_data`
**验证:** `cd server && uv run python -c "from db_client import get_active_stock_codes"` 无报错;空表返回 `[]`;分页 + `is_active` 过滤测试通过

### TS1.2 FakeClient 支持 `.range()` 分页
- 修改 `server/tests/conftest.py`
- `_QueryBuilder` 增加 `range(low, high)` 方法与 `_range` 状态;`execute()` select 分支按 `[low, high+1]`(PostgREST 闭区间)切片
**验证:** `test_get_active_stock_codes_paginates_and_filters_active` 通过

---

## Phase 2:API 路由

### TS2.1 新增 `BulkDailyQuotesSyncRequest` 模型
- 修改 `server/stocks.py`
- 新增 Pydantic 模型:`start_date`/`end_date`(`date`)
- `@model_validator(mode="after")` 校验 `start_date <= end_date` 且 `(end_date - start_date).days <= 5`,违例 `ValueError` -> `422`
- **不复用** `DailyQuotesSyncRequest`(避免 5 天护栏污染单股端点)
**验证:** `cd server && uv run python -c "from stocks import BulkDailyQuotesSyncRequest"` 无报错;区间 6 天 / 倒置 -> 422;5 天 -> 通过

### TS2.2 新增任务态 + 后台 fan-out
- 修改 `server/stocks.py`
- `@dataclass BulkSyncJob`(job_id, status, start_date, end_date, total_stocks, upserted, empty, failed, failed_codes, started_at, finished_at, elapsed_ms, error)+ `to_dict()`
- 模块级 `_BULK_JOBS: dict[str, BulkSyncJob]` + `_BULK_JOBS_LOCK = threading.Lock()`;常量 `_BULK_CONCURRENCY=4`、`_BULK_RETRIES=2`、`_BULK_PROGRESS_EVERY=500`
- `_sync_one_stock(code, start_str, end_str) -> (kind, n)`:`_sina_prefix`+`ak.stock_zh_a_daily(adjust="qfq")`+`db_client.upsert_daily_quotes`,2 次线性退避重试;空 df -> `("empty",0)`
- `_run_bulk_sync(job_id, start, end)`:整体 try/except 兜底;`ThreadPoolExecutor` 并发 + `as_completed` 聚合;每 500 只加锁回写进度;收尾置 `completed`
**验证:** `cd server && uv run python -c "from stocks import _run_bulk_sync, BulkSyncJob"` 无报错

### TS2.3 实现两端点
- 修改 `server/stocks.py`
- `@router.post("/stocks/daily-quotes/sync")` `sync_bulk_daily_quotes(body, background_tasks)`:生成 `uuid4().hex` job_id,登记 pending,`background_tasks.add_task(_run_bulk_sync, ...)`,返回 `JSONResponse(202, {job_id, status, status_url})`
- `@router.get("/stocks/daily-quotes/sync/{job_id}")` `get_bulk_sync_status(job_id)`:查 `_BULK_JOBS`,无则 `404`,有则 `job.to_dict()`
- 由 `main.py` 路由级 `Depends(get_current_user)` 自动鉴权
**验证:** `grep -n 'daily-quotes/sync' server/stocks.py` 匹配到两条路由;不带 token -> 401;未知 job_id -> 404

---

## Phase 3:测试

### TS3.1 API 端到端测试
- 新增 `server/tests/test_stocks_bulk_daily_quotes_sync.py`
- 复用 `client` / `auth_headers` / `fake_db` 夹具;autouse 隔离 `_BULK_JOBS` 并 stub `ak.stock_zh_a_daily` + `time.sleep`
- 新增测试:
  - `test_bulk_sync_requires_token` — 不带 token -> 401
  - `test_bulk_sync_rejects_inverted_dates` / `test_bulk_sync_rejects_range_over_5_days` / `test_bulk_sync_accepts_5_day_range`
  - `test_bulk_sync_returns_202_and_pending_status` — 202 + job_id + status_url;未知 job_id -> 404
  - `test_bulk_sync_happy_path_completes` — 2 只股票,completed,upserted=2,行数正确
  - `test_bulk_sync_partial_failure_still_completes` — 688981 持续抛错进 failed_codes,其余成功
  - `test_bulk_sync_empty_df_counts_as_empty` — 空 df -> empty=1
  - `test_single_stock_endpoint_unaffected_by_5_day_cap` — 单股仍接受 >5 天区间(回归)
**验证:** `cd server && uv run pytest tests/test_stocks_bulk_daily_quotes_sync.py -q` 全部通过

---

## Phase 4:回归 & 端到端

### TS4.1 回归测试
- 运行:`cd server && uv run pytest tests/ -q`
- 覆盖:`test_stocks.py`、`test_stocks_daily_quotes_sync.py`、`test_db_client*.py`、`test_auth.py`、`test_main.py`、`test_stocks_models.py` 均不回归
**验证:** 全量测试通过,无现有用例失败

### TS4.2 端到端冒烟
- 启动:`cd server && uv run uvicorn main:app --reload`
- 前置:`POST /svc/api/stocks/sync`(Bearer token)确保 `stocks` 表有活跃代码
- 触发:`POST /svc/api/stocks/daily-quotes/sync` `{"start_date":"2026-07-24","end_date":"2026-07-24"}` -> 202 + job_id
- 轮询:`GET /svc/api/stocks/daily-quotes/sync/<job_id>` 直至 `completed`,核对 upserted/empty/failed
- 验证:`SELECT count(*), count(distinct code) FROM stock_daily_quotes WHERE trade_date='2026-07-24'` ≈ 5500
- 错误路径:倒置/6 天跨度 -> 422;不带 token -> 401;伪造 job_id -> 404
**验证:** 全流程通过;`stock_daily_quotes` 新增数据;`stock_daily_data` 与 `stocks` 不受影响

---

## 完成标准

- [ ] `server/db_client.get_active_stock_codes()` 分页读取活跃股票,不触碰其它表
- [ ] `BulkDailyQuotesSyncRequest` 校验 `start<=end` 且 `end-start<=5` 天,护栏不作用于单股端点
- [ ] `POST /svc/api/stocks/daily-quotes/sync` 受 JWT 保护,立即返回 202 + job_id,后台 fan-out 写入 `stock_daily_quotes`
- [ ] `GET /svc/api/stocks/daily-quotes/sync/{job_id}` 返回任务态,未知 job_id -> 404
- [ ] 单股失败聚合 `failed_codes`,任务以 `completed` 结束(不整体 500)
- [ ] 复用 `stock_daily_quotes` / `upsert_daily_quotes`,不新增表、不改 schema
- [ ] 单股 `POST /stocks/{code}/daily-quotes/sync` 与 `/stocks/sync` 等现有端点行为不变
- [ ] 全量测试通过
