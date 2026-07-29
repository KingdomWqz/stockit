# 本地 SQLite 迁移 — 实施记录

> 任务清单：[sqlite-migration-tasks.md](./sqlite-migration-tasks.md)
> 分支：`feat/sqlite-migration`
> 日期：2026-07-29

## 目标

将后端数据库方案从 Supabase PostgREST 改为本地 SQLite。前端 `/svc/api/*`
调用契约不变，鉴权继续使用现有后端 JWT。

## 完成情况

全部 5 个 Phase 完成，`cd server && uv run pytest -q` 共 **56 passed**，
`rg -n "supabase|SUPABASE|postgrest" server scripts` 在当前运行代码中**零命中**。

### Phase 1：Schema 与连接层
- **TS1.1** 新增 `server/schema_sqlite.sql`：三张表 `stocks` / `stock_daily_data` /
  `stock_daily_quotes`，SQLite 类型映射（`BOOLEAN`→`INTEGER 0/1`、
  `BIGINT IDENTITY`→`INTEGER AUTOINCREMENT`、`TIMESTAMPTZ`→`TEXT ISO8601`），
  保留唯一约束与外键，含 `updated_at` 触发器，幂等可重复执行。
- **TS1.2** 重写 `db_client.get_client`：模块级 `sqlite3.Connection` 单例，
  `check_same_thread=False`，PRAGMA `WAL`/`busy_timeout=5000`/`synchronous=NORMAL`/
  `foreign_keys=ON`，`threading.Lock` 串行保护，`DATABASE_PATH` 默认 `data/stockit.db`
  （相对路径按 `server/` 解析）。新增 `close_client()` 供测试复位。

### Phase 2：写入与查询函数
- **TS2.1** `sync_stock_list`：`INSERT ... ON CONFLICT(code) DO UPDATE`，退市置
  `is_active=0`，北交所残留先删子表 `stock_daily_quotes` 再删父表 `stocks`（外键）。
- **TS2.2** `upsert_daily_quotes`：保留 AKShare 字段映射，`volume` 转 `int`，
  `NaN`→`NULL`，`ON CONFLICT(code,trade_date,adjust) DO UPDATE`，缺失列映射为 NULL。
- **TS2.3** `upsert_indicators`：目标字段白名单，`ON CONFLICT(code,trade_date) DO UPDATE`。
- **TS2.4** `clean_expired_data`：SQL `DELETE ... WHERE trade_date < date('now','-N days')`，
  返回 `rowcount`；异常回滚并返回 `None`。
- **TS2.5** `get_active_stock_codes`：`LIMIT ? OFFSET ?` 分页，去重保序。
- **TS2.6** 新增 `search_active_stocks(keyword, limit=20)`：名称 `LIKE '%kw%'` +
  代码 `LIKE 'kw%'`，按 `code` 排序。

### Phase 3：API 与脚本
- **TS3.1** `stocks.py` `/stocks/search` 改调 `db_client.search_active_stocks`，
  移除 PostgREST DSL。
- **TS3.2** `scripts/bench_daily_quotes_sync.py` 移除 `supabase`，改用只读 SQLite
  连接；`--retry-missing` 用 `NOT EXISTS` 子查询。

### Phase 4：配置、依赖与文档
- **TS4.1** `.env.example` 删 Supabase 配置、新增 `DATABASE_PATH`；
  `.gitignore` 忽略 `server/data/*.db`、`server/data/*.db-*`（WAL/SHM）。
- **TS4.2** `pyproject.toml` 删 `supabase>=2.31.0`；`httpx` 移入 dev 依赖（原为
  supabase 传递依赖，TestClient 需要）；`uv lock` + `uv sync` 卸载 supabase 全家桶。
- **TS4.3** 根 `README.md`、`docs/projects/stockit/schema/schema.sql` 指向 SQLite；
  数据库设计文档加历史背景横幅，明确 Supabase 为已退役方案。

### Phase 5：测试迁移
- **TS5.1** `conftest.py` 删 FakeClient/PostgREST query builder fake，改用 `:memory:`
  SQLite fixture，显式执行 `schema_sqlite.sql`，monkeypatch `db_client.get_client`。
- **TS5.2/5.3** db_client 与 stocks API 测试断言改为直接查 SQLite 表；外键约束下
  预种父表 `stocks` 行。

## 类型映射对照

| Postgres | SQLite |
|----------|--------|
| `BOOLEAN` | `INTEGER` (0/1) |
| `BIGINT GENERATED ALWAYS AS IDENTITY` | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| `VARCHAR(n)` / `DATE` | `TEXT` |
| `REAL` | `REAL` |
| `TIMESTAMPTZ DEFAULT NOW()` | `TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))` |
| plpgsql `clean_old_stock_data` RPC | Python `clean_expired_data` SQL DELETE |

## 首次使用

```bash
cd server
uv run python -c "import sqlite3,db_client; c=db_client.get_client(); c.executescript(open('schema_sqlite.sql').read()); c.commit()"
```
