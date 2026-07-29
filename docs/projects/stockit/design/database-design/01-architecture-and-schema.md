# 股票指标数据库设计与维护技术文档 (Supabase 个人本地版)

> **⚠️ 历史背景文档**：本文档描述的是已退役的 Supabase PostgREST 方案，仅作历史参考。
> 当前数据库方案已迁移至**本地 SQLite**，建表脚本见 `server/schema_sqlite.sql`
> （镜像于 `docs/projects/stockit/schema/schema.sql`）。表结构与字段命名与本文档一致，
> 仅类型映射调整（`BOOLEAN`→`INTEGER 0/1`、`BIGINT IDENTITY`→`INTEGER AUTOINCREMENT`、
> `TIMESTAMPTZ`→`TEXT ISO8601`），清理逻辑由 Python 端 `db_client.clean_expired_data`
> 取代原 plpgsql 存储过程。首次使用前需手动执行建表脚本（见根 README）。

本文档专为**单人本地开发/运行**场景设计。针对 Supabase 免费套餐（容量上限 500 MB）的限制，采用**滑动数据保留**与**字段类型精简**策略，确保数据库长期稳定运行且**永久免费**。

---

## 1. 存储架构设计

* **使用场景**：个人本地运行计算脚本，Supabase 仅作为云端/持久化存储数据库。
* **数据保留策略**：滑动保留最近 **90 天（约 3 个月）** 的交易日数据。
* **合并宽表**：将 K 线基础行情与技术指标合并为单表，减少 PostgreSQL 行头与索引开销。
* **精简数据类型**：数值统一采用 `REAL` (Float4)，存储空间较 `NUMERIC` 降低 50%。
* **容量控制预估**：
* **单日全量数据**：~5,000 条记录 ≈ 0.9 MB
* **90 天总数据量**：~300,000 条记录 ≈ 50 MB (含索引)
* **容量占用**：仅占 Supabase 500 MB 额度的 **10%** 左右，安全额度充足。



---

## 2. 数据库 Schema 与索引 SQL

在 Supabase 后台的 **SQL Editor** 中运行以下 SQL 脚本完成数据库构建：

```sql
-- ========================================================
-- 1. 股票基础字典表 (Stocks Basic)
-- ========================================================
CREATE TABLE IF NOT EXISTS public.stocks (
    code VARCHAR(10) PRIMARY KEY,       -- 股票代码 (如 '600519')
    name VARCHAR(20) NOT NULL,           -- 股票简称
    industry VARCHAR(30),                -- 所属行业
    is_active BOOLEAN DEFAULT true       -- 是否正常上市交易
);

COMMENT ON TABLE public.stocks IS '股票基础信息字典表';

-- 个人使用禁用 RLS 权限限制
ALTER TABLE public.stocks DISABLE ROW LEVEL SECURITY;

-- ========================================================
-- 2. 每日行情与指标合并宽表 (Daily Data & Indicators)
-- ========================================================
CREATE TABLE IF NOT EXISTS public.stock_daily_data (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,

    -- 基础行情 (K线)
    close REAL,                          -- 收盘价
    pct_chg REAL,                        -- 涨跌幅 (%)
    turnover_rate REAL,                  -- 换手率 (%)

    -- 核心技术指标
    ma5 REAL,                            -- 5日均线
    ma20 REAL,                           -- 20日均线
    macd_dif REAL,                       -- MACD DIF
    macd_dea REAL,                       -- MACD DEA
    macd_hist REAL,                      -- MACD 柱
    kdj_k REAL,                          -- KDJ K值
    kdj_d REAL,                          -- KDJ D值
    kdj_j REAL,                          -- KDJ J值
    rsi12 REAL,                          -- RSI 12日
    boll_upper REAL,                     -- 布林线上轨
    boll_lower REAL,                     -- 布林线下轨

    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- 联合唯一约束：保证 Upsert 覆盖写入幂等性
    CONSTRAINT uq_code_date UNIQUE (code, trade_date)
);

COMMENT ON TABLE public.stock_daily_data IS '每日K线及指标合并数据表 (保留近90天)';

-- 个人使用禁用 RLS 权限限制
ALTER TABLE public.stock_daily_data DISABLE ROW LEVEL SECURITY;

-- ========================================================
-- 3. 高性能索引配置
-- ========================================================

-- 保证单个股票按日期检索极速返回，同时加速 Upsert 插入冲突判定
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_daily_code_date
ON public.stock_daily_data (code, trade_date DESC);

-- 保证按日期全局筛选策略股票（如某日 MACD 金叉）的性能
CREATE INDEX IF NOT EXISTS idx_stock_daily_date_code
ON public.stock_daily_data (trade_date DESC, code);

```

---
