# Stockit 本地 SQLite 迁移任务清单

目标：将后端数据库方案从 Supabase PostgREST 改为本地 SQLite。前端 `/svc/api/*`
调用契约不变，鉴权继续使用现有后端 JWT。

---

## Phase 1：SQLite Schema 与连接层

### TS1.1 新增 SQLite 建表脚本
- 新增 `server/schema_sqlite.sql`
- 定义三张表：`stocks`、`stock_daily_data`、`stock_daily_quotes`
- 使用 SQLite 类型：
  - `TEXT` 存股票代码、名称、日期、时间戳
  - `REAL` 存价格、指标、换手率等浮点字段
  - `INTEGER` 存布尔值与成交量
  - `INTEGER PRIMARY KEY AUTOINCREMENT` 替代 Postgres identity
- 保留唯一约束：
  - `stocks.code`
  - `stock_daily_data(code, trade_date)`
  - `stock_daily_quotes(code, trade_date, adjust)`
- 建表脚本幂等，可重复执行
**验证：** 使用 SQLite 客户端执行脚本后，`.tables` 能看到三张表，唯一索引存在。

### TS1.2 重写数据库客户端初始化
- 修改 `server/db_client.py`
- 移除 `supabase`、`Client`、`create_client` 相关导入
- 通过 `DATABASE_PATH` 读取数据库路径，默认值为 `data/stockit.db`
- 相对路径按 `server/` 目录解析
- 使用模块级 `sqlite3.Connection` 单例
- 连接参数使用 `check_same_thread=False`
- 初始化连接时只设置 PRAGMA，不自动建表：
  - `PRAGMA journal_mode=WAL`
  - `PRAGMA busy_timeout=5000`
  - `PRAGMA synchronous=NORMAL`
  - `PRAGMA foreign_keys=ON`
- 使用模块级 `threading.Lock` 保护公开数据库操作
**验证：** `cd server && uv run python -c "import db_client; db_client.get_client()"` 在已有数据库文件时能成功连接。

---

## Phase 2：迁移写入与查询函数

### TS2.1 迁移 `sync_stock_list`
- 修改 `server/db_client.py`
- 使用 SQL 查询当前 `is_active = 1` 的股票代码集合
- 过滤北交所代码，仅保留 `6`、`0`、`3` 开头股票
- 使用 `INSERT ... ON CONFLICT(code) DO UPDATE` 写入股票列表
- 对缺失于新列表的现有 active 股票执行 `UPDATE is_active = 0`
- 物理删除北交所残留：先删 `stock_daily_quotes`，再删 `stocks`
- 返回值保持 `{"total", "upserted", "deactivated", "deleted"}`
**验证：** 同步含沪深和北交所 code 的 DataFrame 后，北交所不入库，既有北交所残留被删除，返回统计正确。

### TS2.2 迁移 `upsert_daily_quotes`
- 修改 `server/db_client.py`
- 保留 AKShare 字段映射：`date` -> `trade_date`，`turnover` -> `turnover_rate`
- 日期统一写入 `YYYY-MM-DD`
- `NaN` 转为 `NULL`
- `volume` 转为 Python `int` 或 `NULL`
- 使用 `INSERT ... ON CONFLICT(code, trade_date, adjust) DO UPDATE`
- 返回值保持 `{"total": int, "upserted": int}`
**验证：** 重复写入同一 `code/trade_date/adjust` 不新增重复行，覆盖字段值正确。

### TS2.3 迁移 `upsert_indicators`
- 修改 `server/db_client.py`
- 保留现有目标字段白名单
- `NaN` 转为 `NULL`
- 使用 `INSERT ... ON CONFLICT(code, trade_date) DO UPDATE`
- 返回处理记录总数
**验证：** 同一 `code/trade_date` 重复写入会覆盖指标字段，不产生重复行。

### TS2.4 迁移 `clean_expired_data`
- 修改 `server/db_client.py`
- 移除 RPC 调用
- 使用 SQL 删除 `stock_daily_data` 中超过保留期的记录
- 返回删除行数；异常时记录日志并返回 `None`
**验证：** 插入一条旧日期和一条新日期数据，调用后只删除旧数据，返回 `1`。

### TS2.5 迁移 `get_active_stock_codes`
- 修改 `server/db_client.py`
- 使用 `LIMIT ? OFFSET ?` 分页查询 `is_active = 1`
- 返回去重后的股票代码列表
- 保留 `batch_size` 参数
**验证：** active/inactive 混合数据下只返回 active code，分页结果完整。

### TS2.6 新增 `search_active_stocks`
- 修改 `server/db_client.py`
- 新增 `search_active_stocks(keyword, limit=20) -> list[dict]`
- 查询 `stocks` 表中 active 股票
- 名称使用包含匹配：`name LIKE '%keyword%'`
- 代码使用前缀匹配：`code LIKE 'keyword%'`
- 按 `code` 排序并限制返回数量
**验证：** 名称搜索、代码前缀搜索、inactive 过滤、limit=20 均通过。

---

## Phase 3：API 与脚本改造

### TS3.1 搜索接口改为调用 db_client
- 修改 `server/stocks.py`
- `/stocks/search` 不再调用 `.table().select().or_()` PostgREST DSL
- 改为调用 `db_client.search_active_stocks(keyword, limit=20)`
- 响应继续返回 `code`、`name`、`market`
**验证：** `GET /svc/api/stocks/search?keyword=600` 返回格式不变。

### TS3.2 改造 benchmark 脚本
- 修改 `scripts/bench_daily_quotes_sync.py`
- 移除 `from supabase import create_client`
- 通过 SQLite 只读连接读取 `stocks` 表 code
- `--retry-missing` 使用 `NOT EXISTS` 查询缺失指定交易日行情的 code
- HTTP 调用逻辑保持不变
**验证：** 脚本不再依赖 `SUPABASE_URL` 和 `SUPABASE_SERVICE_ROLE_KEY`。

---

## Phase 4：配置、依赖与文档

### TS4.1 更新配置文件
- 修改 `server/.env.example`
- 删除 `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`
- 新增 `DATABASE_PATH=data/stockit.db`
- 修改 `.gitignore`
- 忽略 `server/data/*.db`、`server/data/*.db-*`
**验证：** 本地数据库文件、WAL 文件、SHM 文件不会进入 git。

### TS4.2 更新 Python 依赖
- 修改 `server/pyproject.toml`
- 删除 `supabase>=2.31.0`
- 在 `server/` 下运行 `uv lock`
**验证：** `server/uv.lock` 中不再包含 `supabase` 作为项目直接依赖。

### TS4.3 更新项目文档
- 更新根 `README.md`
- 更新 `docs/projects/stockit/schema/schema.sql`
- 更新数据库设计文档与架构文档中的 Supabase/Postgres 描述
- 明确首次使用前需要手动执行 `server/schema_sqlite.sql`
**验证：** 文档中的当前数据库方案指向 SQLite，不再把 Supabase 描述为当前运行依赖。

---

## Phase 5：测试迁移

### TS5.1 用真实 SQLite fixture 替换 Fake Supabase Client
- 修改 `server/tests/conftest.py`
- 删除 FakeClient 和 PostgREST query builder fake
- 新增 `:memory:` SQLite fixture
- fixture 显式执行 `server/schema_sqlite.sql`
- monkeypatch `db_client.get_client` 返回测试连接
- 测试结束后关闭连接并重置模块级连接状态
**验证：** 测试不需要真实数据库、不需要网络、不依赖 Supabase DSL。

### TS5.2 更新 db_client 测试
- 修改 `server/tests/test_db_client.py`
- 修改 `server/tests/test_db_client_upsert_daily_quotes.py`
- 断言改为直接查询 SQLite 表
- 覆盖 upsert、覆盖更新、inactive 过滤、分页、NaN/NULL、volume int 转换
**验证：** `cd server && uv run pytest tests/test_db_client.py tests/test_db_client_upsert_daily_quotes.py -q` 通过。

### TS5.3 更新 stocks API 测试
- 修改 `server/tests/test_stocks.py`
- 修改日线同步和批量同步相关测试
- 通过 SQLite fixture 种子数据并断言响应
- 保持 AKShare mock，避免网络请求
**验证：** `cd server && uv run pytest tests/test_stocks*.py -q` 通过。

---

## 完成标准

- [ ] `cd server && uv run pytest -q` 全部通过
- [ ] `rg -n "supabase|SUPABASE|postgrest" server scripts` 无当前运行代码命中
- [ ] `server/schema_sqlite.sql` 可手动创建完整本地数据库
- [ ] 启动后端后，登录、股票同步、股票搜索、单股日线同步、批量日线同步均可正常工作
- [ ] `web/` 不需要改动，前端接口响应格式保持兼容
- [ ] 文档明确本地 SQLite 是当前数据库方案，Supabase 只保留为历史背景时才出现
