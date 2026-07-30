# 数据库迁移计划:Supabase (PostgREST) → 本地 SQLite

## Context

stockit 是个人单用户选股器,后端 (`server/`,FastAPI) 当前用 `supabase-py` PostgREST 客户端直连 Supabase 云库(service role key,绕过 RLS)。迁移动机:摆脱云依赖、降低延迟、本地零成本持久化。前端 (`web/`) 完全解耦,经 `/svc/api/*` 同源反代调用后端,**无需改动**。auth 是后端自签 JWT(`auth.py`),与 Supabase GoTrue 无关。

迁移面集中在后端:`server/db_client.py`(整个重写)、`server/stocks.py`(1 处直接 DSL 调用)、测试(`conftest.py` 的 PostgREST fake)、`scripts/bench_daily_quotes_sync.py`、配置与文档。无既有 SQLite 痕迹,从零开始。

## 关键决策

1. **驱动:stdlib `sqlite3`**。端点均为同步 `def`;批量同步用 `ThreadPoolExecutor`(线程,非 asyncio);sqlite3 零新依赖。aiosqlite 会迫使所有 db_client 函数与调用点改 async,不划算。
2. **连接管理:单一模块级连接 + `threading.Lock` + WAL**。一个 `sqlite3.Connection`,`check_same_thread=False`,`PRAGMA journal_mode=WAL`、`busy_timeout=5000`、`synchronous=NORMAL`、`foreign_keys=ON`;模块级 `threading.Lock` 序列化所有操作。批量同步 4 个 worker 线程并发写 `upsert_daily_quotes`,SQLite 只允许单写,共享连接+Lock 干净串行化,避免 `database is locked` 与跨线程对象错误。WAL 让读端(`search_stocks`、`get_active_stock_codes`)与写端文件级并发。
3. **Schema 由人手动建,代码不自动建表**:DB 文件 `server/data/stockit.db`,env `DATABASE_PATH` 可配(默认相对 `server/` 解析)。新建 `server/schema_sqlite.sql` 作为**供人手动在 DB 客户端执行的建表脚本**(幂等 `CREATE TABLE IF NOT EXISTS`)。`db_client.get_client()` 打开连接后**只设 PRAGMA(WAL/busy_timeout/foreign_keys),不跑 DDL**——表结构由你手动执行 `schema_sqlite.sql` 创建。类型映射:VARCHAR→TEXT、BIGINT IDENTITY→INTEGER PRIMARY KEY AUTOINCREMENT、REAL→REAL、BOOLEAN→INTEGER(0/1)、DATE/TIMESTAMPTZ→TEXT、`NOW()`→`strftime('%Y-%m-%dT%H:%M:%SZ','now')`。测试 fixture 显式加载同一份 `schema_sqlite.sql` 建表(共用一份避免漂移),生产代码不自动建。
4. **Upsert**:SQLite `INSERT ... ON CONFLICT(...) DO UPDATE SET col=excluded.col` 替代 PostgREST `upsert(on_conflict=...)`。冲突键对应表上的 UNIQUE 约束。
5. **BOOLEAN**:存 0/1;db_client 读回 `is_active` 时 int→bool,写入 bool→int。
6. **search_stocks 下沉到 db_client**:新增 `db_client.search_active_stocks(keyword, limit=20)`。SQL:`WHERE is_active=1 AND (name LIKE ? OR code LIKE ?) ORDER BY code LIMIT ?`,name 用 `%kw%`(包含),code 用 `kw%`(前缀),对应原 `name.ilike.%kw%` + `code.like.kw%`。SQLite `LIKE` 默认 ASCII 大小写不敏感,中文不受影响。`stocks.search_stocks` 改为薄封装,只补 market 标签。
7. **测试:用真实 `:memory:` SQLite 替换 FakeClient**。删除 `_Response`/`_QueryBuilder`/`FakeClient`。`fake_db` fixture 建一个 `:memory:` 连接、跑 schema、monkeypatch `db_client.get_client`(并设 `db_client._conn`),测试间重置。测试单线程,共享一个内存连接安全。
8. **clean_expired_data**:RPC → Python `DELETE FROM stock_daily_data WHERE trade_date < date('now', ?)`,返回 `cur.rowcount`。
9. **bench 脚本**:删 `from supabase import create_client`,改 `sqlite3` 只读打开 `DATABASE_PATH`;`fetch_codes` 单条 `SELECT`;`fetch_missing_codes` 用 `NOT EXISTS` 子查询;HTTP 同步循环不变。
10. **配置/env**:`.env`/`.env.example` 用 `DATABASE_PATH=data/stockit.db` 替换 `SUPABASE_*`;`pyproject.toml` 删 `supabase>=2.31.0` 并 `uv lock`;`.gitignore` 加 `server/data/*.db` 与 `server/data/*.db-*`(WAL/SHM)。`.env` 已被 `.gitignore` 覆盖(已验证)。

## Schema SQL(`server/schema_sqlite.sql`,新建)

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS stocks (
    code      TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    industry  TEXT,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stock_daily_data (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    close REAL, pct_chg REAL, turnover_rate REAL,
    ma5 REAL, ma20 REAL,
    macd_dif REAL, macd_dea REAL, macd_hist REAL,
    kdj_k REAL, kdj_d REAL, kdj_j REAL,
    rsi12 REAL, boll_upper REAL, boll_lower REAL,
    created_at    TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (code, trade_date)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_daily_code_date ON stock_daily_data (code, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_daily_date_code ON stock_daily_data (trade_date DESC, code);

CREATE TABLE IF NOT EXISTS stock_daily_quotes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code          TEXT NOT NULL REFERENCES stocks(code),
    trade_date    TEXT NOT NULL,
    adjust        TEXT NOT NULL DEFAULT 'qfq',
    open REAL, high REAL, low REAL, close REAL,
    volume        INTEGER,
    amount REAL, pct_chg REAL, turnover_rate REAL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (code, trade_date, adjust)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_daily_quotes_code_date_adjust ON stock_daily_quotes (code, trade_date DESC, adjust);
CREATE INDEX IF NOT EXISTS idx_stock_daily_quotes_date_code ON stock_daily_quotes (trade_date DESC, code);
```
来源对照:`docs/projects/stockit/schema/schema.sql`(Postgres 版,含 5 节完整 DDL)。`clean_old_stock_data` plpgsql 函数弃用(由 Python `clean_expired_data` 取代)。

## `server/db_client.py` 重写结构

模块级:`_conn`、`_lock = threading.Lock()`。`_resolve_db_path()` 解析 `DATABASE_PATH`(默认 `data/stockit.db`,相对模块目录)。`_apply_pragmas(conn)` 设 WAL/busy_timeout/synchronous/foreign_keys(**仅 PRAGMA,不建表**)。`get_client()` 懒加载双检锁单例,返回共享连接(保留函数名,兼容测试 monkeypatch 与 `stocks.py`)。**不在生产代码跑 DDL**——表由人手动执行 `schema_sqlite.sql` 创建。

公开函数签名(尽量不变):
```python
def upsert_indicators(df_results, batch_size=500) -> int
def clean_expired_data(retention_days=90) -> int          # RPC→Python DELETE
def sync_stock_list(df, batch_size=500) -> dict           # {"total","upserted","deactivated","deleted"}
def upsert_daily_quotes(df_quotes, code, adjust="qfq", batch_size=500) -> dict  # {"total","upserted"}
def get_active_stock_codes(batch_size=1000) -> list[str]  # LIMIT/OFFSET,保留 batch_size
def search_active_stocks(keyword, limit=20) -> list[dict]  # 新增,[{"code","name"}]
```
内部:`_delete_bse_stocks(conn, batch_size) -> int`(LIKE 前缀删,先子表后父表)、`_upsert_batch(conn, table, columns, rows, conflict_cols, update_cols)`(拼 `INSERT...ON CONFLICT` + `executemany`)。所有公开函数持 `_lock`;批 upsert 在一个 `BEGIN`/`COMMIT` 内。`is_active` 读写做 bool↔0/1 转换;`volume` 保持 Python int。

`stocks.search_stocks`(原 `stocks.py:124-138` 直接 DSL)改为:
```python
rows = db_client.search_active_stocks(keyword, limit=20)
return [{"code": r["code"], "name": r["name"], "market": _market_label(r["code"])} for r in rows]
```

## 测试迁移

- `conftest.py`:删 FakeClient 机制;`fake_db` = 真实 `:memory:` SQLite,**显式读取 `schema_sqlite.sql` 执行 `executescript` 建表**(测试必须建表才能跑;此处加载同一份 DDL 脚本,与生产手动执行共用,避免漂移),设 PRAGMA,monkeypatch `db_client.get_client`/`_conn`,测试间重置模块 `_conn` 防泄漏。保留 `make_token`/`auth_headers`/`client` fixture。
- `test_db_client.py`:用 `conn.execute("INSERT...")` 种子、查回断言,`is_active` 用 `bool(...)`;`get_active_stock_codes` 保留 `batch_size` 分页测试(LIMIT/OFFSET)。
- `test_db_client_upsert_daily_quotes.py`:查 `stock_daily_quotes` 断言;NaN→`is None`;volume-int→`isinstance(int)` 成立。**删除 `test_upsert_daily_quotes_batches_small_batch_size`**(它 spy `.table().upsert()` 调用大小 `[2,1]`,与 SQL 不兼容;行数契约已由 `..._writes_new_rows` 覆盖)。
- `test_stocks.py`:`test_sync_stock_list_excludes_and_deletes_bse` + 3 个 search 测试改种/查 SQLite;`test_sync_returns_stats`(monkeypatch `db_client.sync_stock_list`)与 `test_legacy_in_memory_cache_removed` 不变。
- 可选新增 `test_clean_expired_data.py`(种旧行→调用→确认删除+计数)。

## 文件清单(顺序)

新建:
- `server/schema_sqlite.sql`
- `docs/projects/stockit/changelog/sqlite-migration-tasks.md`(本文件)
- (可选)`server/tests/test_clean_expired_data.py`

修改:
- `server/db_client.py`(重写)
- `server/stocks.py`(`search_stocks` 下沉 db_client)
- `server/tests/conftest.py`(fake→内存 SQLite)
- `server/tests/test_db_client.py`、`server/tests/test_db_client_upsert_daily_quotes.py`、`server/tests/test_stocks.py`(断言改查 SQLite)
- `scripts/bench_daily_quotes_sync.py`(去 supabase,查 SQLite)
- `server/pyproject.toml`(删 `supabase` 依赖)+ `uv lock`
- `server/.env`、`server/.env.example`(`SUPABASE_*` → `DATABASE_PATH=data/stockit.db`)
- `.gitignore`(加 `server/data/*.db`、`server/data/*.db-*`)
- `docs/projects/stockit/schema/schema.sql`、`design/database-design/01-architecture-and-schema.md`、`design/database-design/03-cleanup-and-sdk.md`、根 `README.md`(文档改 SQLite)

## 验证

1. `cd server && uv run pytest -q` 全绿;`grep -rn supabase server/ scripts/` 无命中。
2. 删 `server/data/stockit.db`,在 DB 客户端手动执行 `server/schema_sqlite.sql` 建表;启动 server(`scripts/start.sh`),确认文件 + WAL 生成,`sqlite3` `.tables` 列出 3 表。
3. 端点冒烟:`GET /svc/api/health`;登录 + `POST /svc/api/stocks/sync`(验证 `SELECT count(*) FROM stocks WHERE is_active=1`);`GET /svc/api/stocks/search?keyword=600`;`POST /svc/api/stocks/{code}/daily-quotes/sync`(1 天区间,验证 `stock_daily_quotes` 有行)。
4. 并发:`POST /svc/api/stocks/daily-quotes/sync`(1 天区间)轮询至 `completed`,确认日志无 `database is locked`(验证 4 写者下共享连接+Lock+WAL)。
5. `clean_expired_data`:种旧行于 `stock_daily_data`,调用 `retention_days=90`,确认删除+计数。
6. bench 脚本无 supabase import 可运行;`fetch_missing_codes` 返回缺当日行情的 code。
7. `web/` 不动;`/svc/api` 契约不变。

## 风险与缓解

- **批量同步写锁**:共享连接 + `threading.Lock` + WAL + busy_timeout;批在单事务内。
- **`:memory:` 测试泄漏**:fixture 重置模块 `_conn`。
- **布尔漂移**:db_client 读写转换 `is_active` 0/1↔bool。
- **日期运算**:`date('now','-N days')` 对 TEXT `YYYY-MM-DD` 成立;确保 `trade_date` 一律存 `YYYY-MM-DD`。
- **`uv.lock` 漂移**:删依赖后 `uv lock`,否则 CI 安装失败。
- **生产需手动建表**:代码不自动建表,首次部署须手动执行 `server/schema_sqlite.sql`;若忘建表,首个查询会报 `no such table`。在 README/changelog 中明确这一操作步骤。
