# 股票指标数据库设计与维护技术文档 (Supabase 个人本地版)

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

## 3. 定时清理存储过程 (SQL Stored Procedure)

在 Supabase 中创建一个 SQL 函数，用于在本地任务完成写入后自动清理过期数据：

```sql
-- 创建自动清理旧数据的函数 (默认保留近 90 天)
CREATE OR REPLACE FUNCTION clean_old_stock_data(retention_days INT DEFAULT 90)
RETURNS INT AS $$
DECLARE
    deleted_rows INT;
BEGIN
    DELETE FROM public.stock_daily_data
    WHERE trade_date < CURRENT_DATE - (retention_days || ' days')::INTERVAL;
    
    GET DIAGNOSTICS deleted_rows = ROW_COUNT;
    RETURN deleted_rows;
END;
$$ LANGUAGE plpgsql;

```

---

## 4. 本地数据库写入与维护 SDK 模块

本地项目计算出指标数据（`pandas.DataFrame`）后，可直接调用以下模块导入 Supabase，并自动执行清理。

### 依赖安装

```bash
pip install supabase pandas python-dotenv

```

### 配置文件 `.env`

在本地项目根目录下创建 `.env` 文件：

```bash
SUPABASE_URL=https://your-supabase-project-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key

```

### Python 操作模块 (`db_client.py`)

```python
import os
import logging
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    raise ValueError("环境变量缺失，请检查 .env 文件中的 SUPABASE_URL 和 SUPABASE_SERVICE_ROLE_KEY！")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def upsert_indicators(df_results: pd.DataFrame, batch_size: int = 500):
    """
    接收本地计算好的指标 DataFrame 并批量 Upsert 写入 Supabase
    
    :param df_results: 必须包含 'code' 和 'trade_date'，以及 Schema 中定义的指标列
    :param batch_size: 单次批处理大小，默认 500 条
    """
    target_columns = [
        "code", "trade_date", "close", "pct_chg", "turnover_rate",
        "ma5", "ma20", "macd_dif", "macd_dea", "macd_hist",
        "kdj_k", "kdj_d", "kdj_j", "rsi12", "boll_upper", "boll_lower"
    ]
    
    # 过滤出符合数据库 schema 的列，并将 NaN 替换为 None (映射为 JSON null)
    valid_cols = [col for col in target_columns if col in df_results.columns]
    df_upload = df_results[valid_cols].where(pd.notnull(df_results[valid_cols]), None)
    
    records = df_upload.to_dict(orient="records")
    total_records = len(records)
    logging.info(f"开始分批写入 Supabase，共 {total_records} 条数据...")

    for i in range(0, total_records, batch_size):
        batch = records[i:i + batch_size]
        try:
            supabase.table("stock_daily_data").upsert(
                batch,
                on_conflict="code,trade_date"
            ).execute()
            logging.info(f"写入进度: {min(i + batch_size, total_records)} / {total_records}")
        except Exception as e:
            logging.error(f"批次写入失败 (行范围 {i} - {i + len(batch)}): {e}")


def clean_expired_data(retention_days: int = 90):
    """
    调用数据库存储过程清理过期的旧数据
    
    :param retention_days: 保留的天数，默认 90 天
    """
    logging.info(f"开始清理 {retention_days} 天以前的过期数据...")
    try:
        response = supabase.rpc("clean_old_stock_data", {"retention_days": retention_days}).execute()
        logging.info(f"数据清理成功，本次已删除 {response.data} 条旧记录。")
    except Exception as e:
        logging.error(f"调用清理存储过程失败: {e}")

```
