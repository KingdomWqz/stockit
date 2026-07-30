# Stockit

个人量化选股工具 — 基于 akshare 获取A股数据，提供股票筛选与分析功能。

## 技术栈

- **后端**: Python 3.12+ / FastAPI / uvicorn / akshare
- **前端**: Next.js
- **数据**: 本地 SQLite（`server/data/stockit.db`）

## 目录

| 目录 | 说明 |
|------|------|
| `server/` | FastAPI 后端（Python，`uv` 管理依赖） |
| `web/` | Next.js 前端 |
| `docs/` | 数据库设计、前端规格、任务规划等文档 |

## 数据库初始化

当前数据库方案为**本地 SQLite**（已从 Supabase PostgREST 迁移）。首次使用前需手动建表：

```bash
cd server
uv run python -c "import sqlite3,db_client; c=db_client.get_client(); c.executescript(open('schema_sqlite.sql').read()); c.commit()"
```

建表脚本见 `server/schema_sqlite.sql`（幂等，可重复执行）。数据库路径可通过环境变量 `DATABASE_PATH` 覆盖（相对路径按 `server/` 解析，默认 `data/stockit.db`）。


https://deepwiki.com/myhhub/stock
https://github.com/myhhub/stock
没有做 技术指标计算核心（instock/core/indicator/) 、K线形态识别（instock/core/kline/）、策略选股算法（instock/core/strategy/），规划一下
