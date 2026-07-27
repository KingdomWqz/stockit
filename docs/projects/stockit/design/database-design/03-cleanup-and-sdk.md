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
