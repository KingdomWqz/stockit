"""Supabase 存储模块：写入每日指标数据并清理过期记录。

设计说明：
- 懒加载客户端：import 本模块不会因缺少环境变量而崩溃，仅在首次调用
  ``get_client()`` 时才创建 Supabase 客户端。
- 日志使用 ``logging.getLogger(__name__)``，与项目其它模块（stocks.py 等）保持一致，
  不在 import 时调用 ``basicConfig``。
- 使用 service role key 直连，绕过 RLS（个人单用户场景，表已 DISABLE RLS）。
"""

import logging
import os

import pandas as pd
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

logger = logging.getLogger(__name__)

_client: Client | None = None


def get_client() -> Client:
    """懒加载并缓存 Supabase 客户端。缺 env 时抛 ValueError。"""
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise ValueError(
                "环境变量缺失，请检查 .env 文件中的 SUPABASE_URL 和 SUPABASE_SERVICE_ROLE_KEY！"
            )
        _client = create_client(url, key)
    return _client


def upsert_indicators(df_results: pd.DataFrame, batch_size: int = 500) -> int:
    """接收本地计算好的指标 DataFrame 并批量 Upsert 写入 Supabase。

    :param df_results: 必须包含 'code' 和 'trade_date'，以及 Schema 中定义的指标列
    :param batch_size: 单次批处理大小，默认 500 条
    :return: 实际处理的记录总数
    """
    target_columns = [
        "code", "trade_date", "close", "pct_chg", "turnover_rate",
        "ma5", "ma20", "macd_dif", "macd_dea", "macd_hist",
        "kdj_k", "kdj_d", "kdj_j", "rsi12", "boll_upper", "boll_lower",
    ]

    # 过滤出符合数据库 schema 的列，并将 NaN 替换为 None (映射为 JSON null)
    valid_cols = [col for col in target_columns if col in df_results.columns]
    df_upload = df_results[valid_cols].astype(object).where(
        pd.notnull(df_results[valid_cols]), None
    )

    records = df_upload.to_dict(orient="records")
    total_records = len(records)
    logger.info("开始分批写入 Supabase，共 %d 条数据...", total_records)

    client = get_client()
    for i in range(0, total_records, batch_size):
        batch = records[i:i + batch_size]
        try:
            client.table("stock_daily_data").upsert(
                batch,
                on_conflict="code,trade_date",
            ).execute()
            logger.info("写入进度: %d / %d", min(i + batch_size, total_records), total_records)
        except Exception as e:
            logger.error("批次写入失败 (行范围 %d - %d): %s", i, i + len(batch), e)

    return total_records


def clean_expired_data(retention_days: int = 90) -> int | None:
    """调用数据库存储过程清理过期的旧数据。

    :param retention_days: 保留的天数，默认 90 天
    :return: 已删除的旧记录行数；调用失败时返回 None
    """
    logger.info("开始清理 %d 天以前的过期数据...", retention_days)
    try:
        response = get_client().rpc(
            "clean_old_stock_data", {"retention_days": retention_days}
        ).execute()
        deleted = response.data
        logger.info("数据清理成功，本次已删除 %s 条旧记录。", deleted)
        return deleted
    except Exception as e:
        logger.error("调用清理存储过程失败: %s", e)
        return None


def sync_stock_list(df: pd.DataFrame, batch_size: int = 500) -> dict:
    """将沪深京 A 股全集 UPSERT 到 ``stocks`` 表，并退市不在列表中的股票。

    :param df: AKShare ``stock_info_a_code_name()`` 返回的 DataFrame，需含 code、name
    :param batch_size: 单批 UPSERT/UPDATE 的记录数
    :return: ``{"total", "upserted", "deactivated"}`` 同步统计
    """
    client = get_client()

    # 1. 查询当前在市 (is_active=true) 的 code 集合
    resp = client.table("stocks").select("code").eq("is_active", True).execute()
    existing_active = {row["code"] for row in resp.data}

    # 2. 构造记录并分批 UPSERT，显式带 is_active=True 以支持重新上市自动激活
    records = [
        {"code": str(row["code"]), "name": str(row["name"]), "is_active": True}
        for row in df.to_dict(orient="records")
    ]
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        client.table("stocks").upsert(batch, on_conflict="code").execute()

    # 3. 退市：现有 active 集合 - 新列表 code 集合，分批置 is_active=False
    new_codes = {row["code"] for row in records}
    to_deactivate = list(existing_active - new_codes)
    for i in range(0, len(to_deactivate), batch_size):
        batch = to_deactivate[i:i + batch_size]
        client.table("stocks").update({"is_active": False}).in_("code", batch).execute()

    return {"total": total, "upserted": total, "deactivated": len(to_deactivate)}
