# Stockit 基础行情入库任务清单

对应需求文档：`../prd/daily-quotes-sync-plan.md`。每个任务 = 一个 MR，独立可验证。

---

## Phase 1：数据库

### TS1.1 在 `schema.sql` 中新增 `stock_daily_quotes` 表
- 修改 `../schema/schema.sql`
- 追加 `CREATE TABLE IF NOT EXISTS public.stock_daily_quotes (...)`，字段、外键 (`REFERENCES public.stocks(code)`)、`UNIQUE (code, trade_date, adjust)` 与 `daily-quotes-sync-plan.md` 第 3 节保持一致
- 追加 `CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_daily_quotes_code_date_adjust ON public.stock_daily_quotes (code, trade_date DESC, adjust)`
- 追加 `CREATE INDEX IF NOT EXISTS idx_stock_daily_quotes_date_code ON public.stock_daily_quotes (trade_date DESC, code)`
- `ALTER TABLE public.stock_daily_quotes DISABLE ROW LEVEL SECURITY`（与现有两张表保持一致，个人单用户场景）
- **不动** `stock_daily_data` 及其 `clean_old_stock_data` 存储过程
**验证：** 在 Supabase 重新执行 `schema.sql` 不报错；`\d stock_daily_quotes` 字段、唯一键、索引齐全；`stock_daily_data` 表结构未变

---

## Phase 2：数据库 helper

### TS2.1 新增 `upsert_daily_quotes` 函数
- 修改 `server/db_client.py`
- 新增 `upsert_daily_quotes(df_quotes, adjust="qfq", batch_size=500) -> dict`：
  1. 校验 `df_quotes` 至少含 `date` 列；缺失抛 `ValueError("缺少必要字段: date")`
  2. 字段映射：`date -> trade_date`、其余按 plan 第 4 节表格映射
  3. `trade_date` 统一转 `YYYY-MM-DD` 字符串；`NaN` 替换为 `None`
  4. 强制写入 `adjust` 列（默认 `"qfq"`），按 `batch_size` 分批 `client.table("stock_daily_quotes").upsert(records, on_conflict="code,trade_date,adjust").execute()`
  5. 返回 `{"total": int, "upserted": int}`
- 不触碰 `stock_daily_data`，不引入新的 client
**验证：** `cd server && uv run python -c "from db_client import upsert_daily_quotes"` 无报错；空 DataFrame 返回 `{"total": 0, "upserted": 0}`；缺 `date` 列抛 `ValueError`

### TS2.2 `upsert_daily_quotes` 幂等覆盖测试
- 修改 `server/tests/conftest.py`、`server/tests/test_db_client.py`
- `FakeClient.tables` 增加 `"stock_daily_quotes": []`；`_QueryBuilder` 当前已支持 `upsert(on_conflict=...)`，无需大改
- 新增测试：
  - `test_upsert_daily_quotes_writes_new_rows` — 输入 3 行 qfq 行情，全部写入
  - `test_upsert_daily_quotes_overwrites_same_key` — 同一 `(code, trade_date, adjust)` 二次写入，`close` 被覆盖、不产生重复行
  - `test_upsert_daily_quotes_empty_df` — 空 DataFrame 不写库、返回 `{"total": 0, "upserted": 0}`
  - `test_upsert_daily_quotes_missing_date_column` — 缺少 `date` 列抛 `ValueError`，且消息含 `"date"`
  - `test_upsert_daily_quotes_batches_small_batch_size` — `batch_size=2`，5 行正确分批
  - `test_upsert_daily_quotes_does_not_touch_daily_data` — 调用前后 `stock_daily_data` 行数与内容不变
**验证：** `cd server && uv run pytest tests/test_db_client.py -q` 全部通过；旧测试 (`test_sync_stock_list_*`) 不回归

---

## Phase 3：API 路由

### TS3.1 新增 `DailyQuotesSyncRequest` 模型
- 修改 `server/stocks.py`
- 新增 Pydantic 模型：
  - `start_date: date`、`end_date: date`
  - 自定义校验：`start_date <= end_date`，否则 `ValueError("start_date 不得晚于 end_date")`
- 不暴露 `adjust` 字段，固定 `qfq`
**验证：** `cd server && uv run python -c "from stocks import DailyQuotesSyncRequest"` 无报错

### TS3.2 校验股票代码格式
- 修改 `server/stocks.py`
- 新增 `_validate_stock_code(code: str) -> None`：`code` 必须 6 位数字，否则抛 `HTTPException(422, "code 必须为 6 位数字")`
- 复用 `_sina_prefix` / `_market_label` 的市场前缀逻辑
**验证：** `cd server && uv run python -c "from stocks import _validate_stock_code"` 无报错

### TS3.3 实现 `POST /stocks/{code}/daily-quotes/sync` 端点
- 修改 `server/stocks.py`
- 新增 `@router.post("/stocks/{code}/daily-quotes/sync")`
- 流程：
  1. `_validate_stock_code(code)`；参数反序列化失败 / `start_date > end_date` → `HTTPException(422)`
  2. 计算 AKShare symbol = `_sina_prefix(code) + code`，`start_date`/`end_date` 转 `YYYYMMDD`
  3. `ak.stock_zh_a_daily(symbol=..., start_date=..., end_date=..., adjust="qfq")`，抛异常 → `HTTPException(502, "行情数据获取失败")`
  4. DataFrame 为空 → 返回 `{"code", "start_date", "end_date", "adjust": "qfq", "total": 0, "upserted": 0}`
  5. 否则调用 `db_client.upsert_daily_quotes(df, adjust="qfq")`；写库异常 → `HTTPException(500, "数据库写入失败")`
- 由 `main.py` 现有 `dependencies=[Depends(get_current_user)]` 自动覆盖鉴权，无需改动 `main.py`
**验证：** `cd server && uv run python -c "from stocks import router"` 无报错；`grep -n 'daily-quotes' server/stocks.py` 能匹配到路由

### TS3.4 API 端到端测试
- 修改 `server/tests/test_stocks.py`
- 复用现有 `client` / `auth_headers` / `fake_db` 夹具；`_stub_akshare` 不影响新端点（按需 monkeypatch `ak.stock_zh_a_daily`）
- 新增测试：
  - `test_sync_daily_quotes_requires_token` — 不带 token → 401
  - `test_sync_daily_quotes_rejects_non_six_digit_code` — `code="12345"` 或 `"abcdef"` → 422
  - `test_sync_daily_quotes_rejects_inverted_dates` — `start_date=2026-02-01`、`end_date=2026-01-01` → 422
  - `test_sync_daily_quotes_returns_stats_on_success` — monkeypatch `ak.stock_zh_a_daily` 返回 3 行，断言响应包含 `code/start_date/end_date/adjust/total/upserted`，且 `fake_db.tables["stock_daily_quotes"]` 行数正确、`adjust="qfq"`
  - `test_sync_daily_quotes_idempotent_overwrite` — 同一 `(code, date, adjust)` 二次调用，`close` 被覆盖、不新增行
  - `test_sync_daily_quotes_returns_502_when_akshare_fails` — `ak.stock_zh_a_daily` 抛异常 → 502
  - `test_sync_daily_quotes_returns_zero_when_akshare_empty` — 返回空 DataFrame → `total=0, upserted=0`
**验证：** `cd server && uv run pytest tests/ -q` 全部通过；旧 `test_sync_*` / `test_search_*` / `test_*_legacy_*` 不回归

---

## Phase 4：回归 & 端到端

### TS4.1 回归测试
- 运行：`cd server && uv run pytest tests/ -q`
- 覆盖范围：
  - `test_auth.py` — 鉴权 helper 不变
  - `test_db_client.py` — `sync_stock_list` / `upsert_indicators` / `clean_expired_data` 不受影响
  - `test_stocks.py` — `/stocks/sync`、`/stocks/search`、`/stocks/{code}`、`/stocks/{code}/kline` 行为不变
**验证：** 全量测试通过，无现有用例失败

### TS4.2 端到端冒烟
- 启动：`cd server && uv run uvicorn main:app --reload`
- 登录：`POST /svc/api/auth/login`（admin / admin123）→ 拿到 token
- 鉴权：`POST /svc/api/stocks/600519/daily-quotes/sync` 不带 token → 401
- 校验：`code="abc"` → 422；`start_date > end_date` → 422
- 同步：合法日期区间（如 `2026-01-01` ~ `2026-01-31`）→ 200，返回 `total/upserted`
- 幂等：同一区间再调一次 → `upserted` 与首调一致，不翻倍
- 隔离：`SELECT COUNT(*) FROM stock_daily_data` 行数不变；`SELECT COUNT(*) FROM stocks WHERE is_active=true` 不变
**验证：** 全流程通过；`stock_daily_quotes` 新增数据；`stock_daily_data` 与 `stocks` 不受影响

---

## 完成标准

- [ ] `../schema/schema.sql` 包含 `stock_daily_quotes` 表、唯一键、两条索引
- [ ] `server/db_client.upsert_daily_quotes(df, adjust="qfq")` 写入正确、幂等、不触碰 `stock_daily_data`
- [ ] `POST /svc/api/stocks/{code}/daily-quotes/sync` 受 JWT 保护，校验 code 与日期区间，调用 AKShare 拉取 `qfq` 行情并返回同步统计
- [ ] 错误语义符合 plan 第 2 节：401 / 422 / 502 / 500
- [ ] AKShare 无数据时返回 `total=0, upserted=0`
- [ ] 同一 `(code, trade_date, adjust)` 重复同步覆盖旧值、不产生重复行
- [ ] 现有 `/stocks/sync`、`/stocks/search`、`/stocks/{code}`、`/stocks/{code}/kline` 行为不变
- [ ] `stock_daily_data` 与 `stocks` 表在调用前后无变更
- [ ] 全量测试通过