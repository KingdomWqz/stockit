-- ============================================================
-- Stockit - 本地 SQLite 数据库 Schema (幂等，可重复执行)
--
-- 替代原 Supabase PostgREST 方案。三张表与原 Postgres schema 一一对应：
--   stocks               股票基础字典
--   stock_daily_data     每日行情与指标合并宽表 (保留近 90 天)
--   stock_daily_quotes   原始日线行情表 (完整 OHLCV + adjust)
--
-- 首次使用前手动执行：
--   sqlite3 data/stockit.db < server/schema_sqlite.sql
-- ============================================================

-- ========================================================
-- 1. 股票基础字典表 (Stocks Basic)
-- ========================================================
CREATE TABLE IF NOT EXISTS stocks (
    code      TEXT PRIMARY KEY,          -- 股票代码 (如 '600519')
    name      TEXT NOT NULL,             -- 股票简称
    industry  TEXT,                      -- 所属行业
    is_active INTEGER NOT NULL DEFAULT 1 -- 是否正常上市交易 (0/1)
);

-- ========================================================
-- 2. 每日行情与指标合并宽表 (Daily Data & Indicators)
-- ========================================================
CREATE TABLE IF NOT EXISTS stock_daily_data (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT NOT NULL,
    trade_date     TEXT NOT NULL,        -- YYYY-MM-DD

    -- 基础行情 (K线)
    close          REAL,                 -- 收盘价
    pct_chg        REAL,                 -- 涨跌幅 (%)
    turnover_rate  REAL,                 -- 换手率 (%)

    -- 核心技术指标
    ma5            REAL,                 -- 5日均线
    ma20           REAL,                 -- 20日均线
    macd_dif       REAL,                 -- MACD DIF
    macd_dea       REAL,                 -- MACD DEA
    macd_hist      REAL,                 -- MACD 柱
    kdj_k          REAL,                 -- KDJ K值
    kdj_d          REAL,                 -- KDJ D值
    kdj_j          REAL,                 -- KDJ J值
    rsi12          REAL,                 -- RSI 12日
    boll_upper     REAL,                 -- 布林线上轨
    boll_lower     REAL,                 -- 布林线下轨

    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),

    -- 联合唯一约束：保证 Upsert 覆盖写入幂等性
    CONSTRAINT uq_code_date UNIQUE (code, trade_date)
);

-- 单股按日期检索 + Upsert 冲突判定
CREATE INDEX IF NOT EXISTS idx_stock_daily_code_date
ON stock_daily_data (code, trade_date DESC);

-- 全局按日期筛选策略股票 (如某日 MACD 金叉)
CREATE INDEX IF NOT EXISTS idx_stock_daily_date_code
ON stock_daily_data (trade_date DESC, code);

-- ========================================================
-- 3. 原始日线行情表 (Daily Quotes)
--    与 stock_daily_data 分层：本表存完整 OHLCV + adjust，
--    由基础行情入库 API 写入；stock_daily_data 是指标宽表。
-- ========================================================
CREATE TABLE IF NOT EXISTS stock_daily_quotes (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    code           TEXT NOT NULL REFERENCES stocks(code),
    trade_date     TEXT NOT NULL,        -- YYYY-MM-DD
    adjust         TEXT NOT NULL DEFAULT 'qfq',
    open           REAL,
    high           REAL,
    low            REAL,
    close          REAL,
    volume         INTEGER,              -- 成交量
    amount         REAL,
    pct_chg        REAL,
    turnover_rate  REAL,
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CONSTRAINT uq_code_date_adjust UNIQUE (code, trade_date, adjust)
);

-- 单股按日期检索 + Upsert 冲突判定
CREATE INDEX IF NOT EXISTS idx_stock_daily_quotes_code_date_adjust
ON stock_daily_quotes (code, trade_date DESC, adjust);

-- 全局按日期检索：每日全市场扫描
CREATE INDEX IF NOT EXISTS idx_stock_daily_quotes_date_code
ON stock_daily_quotes (trade_date DESC, code);

-- 写入时刷新 updated_at
CREATE TRIGGER IF NOT EXISTS trg_quotes_updated_at
AFTER UPDATE ON stock_daily_quotes
FOR EACH ROW
BEGIN
    UPDATE stock_daily_quotes
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
    WHERE id = OLD.id;
END;
