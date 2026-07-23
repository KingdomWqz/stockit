-- ============================================================
-- Stockit - Supabase 数据库 Schema (幂等，可重复执行)
-- 来源: docs/database.md
-- 项目: doidksdivyowjicjzplv
-- ============================================================

-- ========================================================
-- 1. 股票基础字典表 (Stocks Basic)
-- ========================================================
CREATE TABLE IF NOT EXISTS public.stocks (
    code VARCHAR(10) PRIMARY KEY,       -- 股票代码 (如 '600519')
    name VARCHAR(20) NOT NULL,          -- 股票简称
    industry VARCHAR(30),               -- 所属行业
    is_active BOOLEAN DEFAULT true      -- 是否正常上市交易
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
    close REAL,                         -- 收盘价
    pct_chg REAL,                       -- 涨跌幅 (%)
    turnover_rate REAL,                 -- 换手率 (%)

    -- 核心技术指标
    ma5 REAL,                           -- 5日均线
    ma20 REAL,                          -- 20日均线
    macd_dif REAL,                      -- MACD DIF
    macd_dea REAL,                      -- MACD DEA
    macd_hist REAL,                     -- MACD 柱
    kdj_k REAL,                         -- KDJ K值
    kdj_d REAL,                         -- KDJ D值
    kdj_j REAL,                         -- KDJ J值
    rsi12 REAL,                         -- RSI 12日
    boll_upper REAL,                    -- 布林线上轨
    boll_lower REAL,                    -- 布林线下轨

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

-- ========================================================
-- 4. 定时清理存储过程 (Stored Procedure)
--    默认保留近 90 天，返回删除行数；SECURITY INVOKER 遵循调用方权限。
-- ========================================================
CREATE OR REPLACE FUNCTION public.clean_old_stock_data(retention_days INT DEFAULT 90)
RETURNS INT
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
DECLARE
    deleted_rows INT;
BEGIN
    DELETE FROM public.stock_daily_data
    WHERE trade_date < CURRENT_DATE - (retention_days || ' days')::INTERVAL;

    GET DIAGNOSTICS deleted_rows = ROW_COUNT;
    RETURN deleted_rows;
END;
$$;
