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
    """将沪深 A 股全集 UPSERT 到 ``stocks`` 表，退市不在列表中的股票，并清理北交所残留。

    北交所(代码以 4/8/9 开头)不在数据范围内：先从入参 df 过滤掉，再物理删除
    ``stock_daily_quotes`` 与 ``stocks`` 表中既存的北交所记录。因 ``stock_daily_quotes.code``
    外键引用 ``stocks.code``，须先删子表行情、再删父表股票。

    :param df: AKShare ``stock_info_a_code_name()`` 返回的 DataFrame，需含 code、name
    :param batch_size: 单批 UPSERT/UPDATE/DELETE 的记录数
    :return: ``{"total", "upserted", "deactivated", "deleted"}`` 同步统计
    """
    client = get_client()

    # 1. 仅保留沪深 A 股（沪 6 开头、深 0/3 开头），排除北交所（4/8/9 开头）
    code_str = df["code"].astype(str)
    df = df[code_str.str.startswith(("6", "0", "3"))].copy()

    # 2. 查询当前在市 (is_active=true) 的 code 集合
    resp = client.table("stocks").select("code").eq("is_active", True).execute()
    existing_active = {row["code"] for row in resp.data}

    # 3. 构造记录并分批 UPSERT，显式带 is_active=True 以支持重新上市自动激活
    records = [
        {"code": str(row["code"]), "name": str(row["name"]), "is_active": True}
        for row in df.to_dict(orient="records")
    ]
    total = len(records)
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        client.table("stocks").upsert(batch, on_conflict="code").execute()

    # 4. 退市：现有 active 集合 - 新列表 code 集合，分批置 is_active=False
    new_codes = {row["code"] for row in records}
    to_deactivate = list(existing_active - new_codes)
    for i in range(0, len(to_deactivate), batch_size):
        batch = to_deactivate[i:i + batch_size]
        client.table("stocks").update({"is_active": False}).in_("code", batch).execute()

    # 5. 物理删除北交所残留：先删子表 stock_daily_quotes，再删父表 stocks。
    #    PostgREST 不支持 code 的正则过滤，改用前缀通配 like 逐前缀删除。
    deleted = _delete_bse_stocks(client, batch_size)

    return {
        "total": total,
        "upserted": total,
        "deactivated": len(to_deactivate),
        "deleted": deleted,
    }


def _delete_bse_stocks(client: Client, batch_size: int = 500) -> int:
    """物理删除北交所(4/8/9 开头)记录，先删子表行情、再删父表股票。

    :param client: Supabase 客户端
    :param batch_size: 单批删除记录数（未使用，保留以与其它批操作接口一致）
    :return: 删除的 ``stocks`` 记录数（``stock_daily_quotes`` 行情数不计入）
    """
    bse_prefixes = ("4", "8", "9")
    deleted = 0
    for prefix in bse_prefixes:
        # 子表：先删 stock_daily_quotes 中此前缀 code 的行情，解除外键引用
        client.table("stock_daily_quotes").delete().like("code", f"{prefix}%").execute()
        # 父表：再删 stocks 中此前缀 code 的股票，统计删除行数
        resp = client.table("stocks").delete().like("code", f"{prefix}%").execute()
        deleted += len(resp.data or [])
    return deleted


# 字段映射：AKShare stock_zh_a_daily 列名 -> 数据库列名
# 注:AKShare 该端点返回 `turnover`(换手率,如 0.002183),映射到 DB 的 turnover_rate;
#    `pct_chg` 该端点不返回,留 NULL(DB 列可空)。
_DAILY_QUOTES_COLUMN_MAP = {
    "date": "trade_date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "amount": "amount",
    "turnover": "turnover_rate",
    "pct_chg": "pct_chg",
}


def upsert_daily_quotes(
    df_quotes: pd.DataFrame,
    code: str,
    adjust: str = "qfq",
    batch_size: int = 500,
) -> dict:
    """将 AKShare 拉取的单股日线行情 UPSERT 到 ``stock_daily_quotes``。

    :param df_quotes: AKShare 返回的 DataFrame,需含 ``date`` 列及 OHLCV 等字段
    :param code: 股票代码,作为写入记录的 ``code`` 列
    :param adjust: 复权口径,默认 ``"qfq"``
    :param batch_size: 单批 UPSERT 大小,默认 500
    :return: ``{"total": int, "upserted": int}`` 同步统计
    :raises ValueError: 输入 DataFrame 缺少 ``date`` 列
    """
    if "date" not in df_quotes.columns:
        raise ValueError("缺少必要字段: date")

    if df_quotes.empty:
        return {"total": 0, "upserted": 0}

    # 仅保留映射表中存在的列,其余丢弃
    valid_cols = [c for c in _DAILY_QUOTES_COLUMN_MAP if c in df_quotes.columns]
    mapped = df_quotes[valid_cols].rename(columns=_DAILY_QUOTES_COLUMN_MAP)

    # 日期统一为 YYYY-MM-DD 字符串,NaN -> None
    mapped["trade_date"] = pd.to_datetime(mapped["trade_date"]).dt.strftime("%Y-%m-%d")
    records = mapped.astype(object).where(pd.notnull(mapped), None).to_dict(orient="records")
    for rec in records:
        rec["code"] = code
        rec["adjust"] = adjust
        # volume 是 BIGINT;AKShare 返回 float(如 2733342.0),PostgREST 把带小数的
        # 字符串送入 BIGINT 会报 22P02,统一转 Python int(NaN -> None)。
        vol = rec.get("volume")
        if vol is None or pd.isna(vol):
            rec["volume"] = None
        else:
            rec["volume"] = int(vol)

    total = len(records)
    client = get_client()
    upserted = 0
    for i in range(0, total, batch_size):
        batch = records[i:i + batch_size]
        client.table("stock_daily_quotes").upsert(
            batch,
            on_conflict="code,trade_date,adjust",
        ).execute()
        upserted += len(batch)
    logger.info("写入 stock_daily_quotes: total=%d, upserted=%d", total, upserted)
    return {"total": total, "upserted": upserted}


def get_active_stock_codes(batch_size: int = 1000) -> list[str]:
    """分页读取 ``stocks`` 表中所有 ``is_active=true`` 的股票代码。

    PostgREST 单次 select 默认上限约 1000 行,故用 ``.range(from, to)`` 分页
    直至取完全部活跃股票。供全市场批量行情同步使用。

    :param batch_size: 单页行数,默认 1000
    :return: 去重保序的活跃股票代码列表
    """
    client = get_client()
    codes: list[str] = []
    offset = 0
    while True:
        resp = (
            client.table("stocks")
            .select("code")
            .eq("is_active", True)
            .range(offset, offset + batch_size - 1)
            .execute()
        )
        page = [row["code"] for row in (resp.data or [])]
        codes.extend(page)
        if len(page) < batch_size:
            break
        offset += batch_size
    seen: set[str] = set()
    unique: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            unique.append(code)
    return unique
