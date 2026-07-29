"""本地 SQLite 存储模块：写入每日指标与日线行情、清理过期记录、查询股票。

设计说明：
- 懒加载连接：import 本模块不会因缺少环境变量而崩溃，仅在首次调用
  ``get_client()`` 时才创建 SQLite 连接。
- 使用模块级 ``sqlite3.Connection`` 单例，``check_same_thread=False`` 允许
  跨线程共享（FastAPI 线程池 + 批量同步 ThreadPoolExecutor）。
- 所有公开数据库操作由模块级 ``threading.Lock`` 串行保护，避免并发写入冲突。
- 日志使用 ``logging.getLogger(__name__)``，与项目其它模块保持一致。
- ``is_active`` 在 SQLite 中存为 INTEGER (0/1)，本模块在边界处与 Python bool 互转。
"""

import logging
import os
import sqlite3
import threading

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# 相对路径按 server/ 目录解析
_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_DB_PATH = os.path.join(_SERVER_DIR, "data", "stockit.db")

_connection: sqlite3.Connection | None = None
_lock = threading.Lock()


def get_client() -> sqlite3.Connection:
    """懒加载并缓存模块级 SQLite 连接。首次连接时设置 PRAGMA，不自动建表。

    :return: 全局共享的 ``sqlite3.Connection``
    """
    global _connection
    if _connection is None:
        db_path = os.getenv("DATABASE_PATH")
        if not db_path:
            db_path = _DEFAULT_DB_PATH
        elif not os.path.isabs(db_path):
            db_path = os.path.join(_SERVER_DIR, db_path)
        # 确保目录存在（仅对文件型路径；:memory: 由父目录为空判断跳过）
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        con = sqlite3.connect(db_path, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        _connection = con
    return _connection


def close_client() -> None:
    """关闭并清空模块级连接（主要供测试使用）。"""
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None


def upsert_indicators(df_results: pd.DataFrame, batch_size: int = 500) -> int:
    """接收本地计算好的指标 DataFrame 并批量 Upsert 写入 SQLite。

    :param df_results: 必须包含 'code' 和 'trade_date'，以及 Schema 中定义的指标列
    :param batch_size: 单次批处理大小，默认 500 条
    :return: 实际处理的记录总数
    """
    target_columns = [
        "code", "trade_date", "close", "pct_chg", "turnover_rate",
        "ma5", "ma20", "macd_dif", "macd_dea", "macd_hist",
        "kdj_k", "kdj_d", "kdj_j", "rsi12", "boll_upper", "boll_lower",
    ]

    # 过滤出符合数据库 schema 的列，并将 NaN 替换为 None (映射为 SQL NULL)
    valid_cols = [col for col in target_columns if col in df_results.columns]
    df_upload = df_results[valid_cols].astype(object).where(
        pd.notnull(df_results[valid_cols]), None
    )

    records = df_upload.to_dict(orient="records")
    total_records = len(records)
    logger.info("开始分批写入 SQLite stock_daily_data，共 %d 条数据...", total_records)

    con = get_client()
    placeholders = ",".join("?" for _ in valid_cols)
    update_cols = [c for c in valid_cols if c not in ("code", "trade_date")]
    update_clause = ",".join(f"{c}=excluded.{c}" for c in update_cols)
    sql = (
        f"INSERT INTO stock_daily_data ({','.join(valid_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(code, trade_date) DO UPDATE SET {update_clause}"
    )
    with _lock:
        for i in range(0, total_records, batch_size):
            batch = records[i:i + batch_size]
            try:
                con.executemany(
                    sql, [tuple(rec.get(c) for c in valid_cols) for rec in batch]
                )
                con.commit()
                logger.info("写入进度: %d / %d", min(i + batch_size, total_records), total_records)
            except Exception as e:
                logger.error("批次写入失败 (行范围 %d - %d): %s", i, i + len(batch), e)
                con.rollback()

    return total_records


def clean_expired_data(retention_days: int = 90) -> int | None:
    """删除 stock_daily_data 中超过保留期的旧记录。

    :param retention_days: 保留的天数，默认 90 天
    :return: 已删除的旧记录行数；异常时记录日志并返回 None
    """
    logger.info("开始清理 %d 天以前的过期数据...", retention_days)
    con = get_client()
    sql = (
        "DELETE FROM stock_daily_data "
        "WHERE trade_date < date('now', ?)"
    )
    try:
        with _lock:
            cur = con.execute(sql, (f"-{retention_days} days",))
            deleted = cur.rowcount
            con.commit()
        logger.info("数据清理成功，本次已删除 %s 条旧记录。", deleted)
        return deleted
    except Exception as e:
        logger.error("清理过期数据失败: %s", e)
        with _lock:
            con.rollback()
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
    con = get_client()

    # 1. 仅保留沪深 A 股（沪 6 开头、深 0/3 开头），排除北交所（4/8/9 开头）
    code_str = df["code"].astype(str)
    df = df[code_str.str.startswith(("6", "0", "3"))].copy()

    # 2. 查询当前在市 (is_active=1) 的 code 集合
    with _lock:
        rows = con.execute("SELECT code FROM stocks WHERE is_active = 1").fetchall()
    existing_active = {row["code"] for row in rows}

    # 3. 构造记录并分批 UPSERT，显式带 is_active=1 以支持重新上市自动激活
    records = [
        {"code": str(row["code"]), "name": str(row["name"]), "is_active": 1}
        for row in df.to_dict(orient="records")
    ]
    total = len(records)
    upsert_sql = (
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?) "
        "ON CONFLICT(code) DO UPDATE SET name=excluded.name, is_active=excluded.is_active"
    )
    with _lock:
        for i in range(0, total, batch_size):
            batch = records[i:i + batch_size]
            con.executemany(
                upsert_sql,
                [(r["code"], r["name"], r["is_active"]) for r in batch],
            )
        con.commit()

    # 4. 退市：现有 active 集合 - 新列表 code 集合，分批置 is_active=0
    new_codes = {row["code"] for row in records}
    to_deactivate = list(existing_active - new_codes)
    if to_deactivate:
        with _lock:
            for i in range(0, len(to_deactivate), batch_size):
                batch = to_deactivate[i:i + batch_size]
                placeholders = ",".join("?" for _ in batch)
                con.execute(
                    f"UPDATE stocks SET is_active = 0 WHERE code IN ({placeholders})",
                    batch,
                )
            con.commit()

    # 5. 物理删除北交所残留：先删子表 stock_daily_quotes，再删父表 stocks。
    deleted = _delete_bse_stocks(con, batch_size)

    return {
        "total": total,
        "upserted": total,
        "deactivated": len(to_deactivate),
        "deleted": deleted,
    }


def _delete_bse_stocks(con: sqlite3.Connection, batch_size: int = 500) -> int:
    """物理删除北交所(4/8/9 开头)记录，先删子表行情、再删父表股票。

    :param con: SQLite 连接
    :param batch_size: 单批删除记录数（未使用，保留以与其它批操作接口一致）
    :return: 删除的 ``stocks`` 记录数（``stock_daily_quotes`` 行情数不计入）
    """
    bse_prefixes = ("4", "8", "9")
    deleted = 0
    with _lock:
        for prefix in bse_prefixes:
            # 子表：先删 stock_daily_quotes 中此前缀 code 的行情，解除外键引用
            con.execute(
                "DELETE FROM stock_daily_quotes WHERE code LIKE ?",
                (f"{prefix}%",),
            )
            # 父表：再删 stocks 中此前缀 code 的股票，统计删除行数
            cur = con.execute(
                "DELETE FROM stocks WHERE code LIKE ?", (f"{prefix}%",)
            )
            deleted += cur.rowcount
        con.commit()
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

# stock_daily_quotes 写入列（不含 code/adjust，二者来自参数）
_DAILY_QUOTES_DB_COLUMNS = [
    "code", "trade_date", "adjust", "open", "high", "low", "close",
    "volume", "amount", "pct_chg", "turnover_rate",
]


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
        # volume 是 INTEGER;AKShare 返回 float(如 2733342.0),统一转 Python int(NaN -> None)。
        vol = rec.get("volume")
        if vol is None or pd.isna(vol):
            rec["volume"] = None
        else:
            rec["volume"] = int(vol)

    total = len(records)
    con = get_client()
    placeholders = ",".join("?" for _ in _DAILY_QUOTES_DB_COLUMNS)
    update_cols = [
        c for c in _DAILY_QUOTES_DB_COLUMNS
        if c not in ("code", "trade_date", "adjust")
    ]
    update_clause = ",".join(f"{c}=excluded.{c}" for c in update_cols)
    sql = (
        f"INSERT INTO stock_daily_quotes ({','.join(_DAILY_QUOTES_DB_COLUMNS)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(code, trade_date, adjust) DO UPDATE SET {update_clause}"
    )
    upserted = 0
    with _lock:
        for i in range(0, total, batch_size):
            batch = records[i:i + batch_size]
            con.executemany(
                sql,
                # 缺失列(如 pct_chg 未返回)映射为 NULL
                [tuple(rec.get(c) for c in _DAILY_QUOTES_DB_COLUMNS) for rec in batch],
            )
            upserted += len(batch)
        con.commit()
    logger.info("写入 stock_daily_quotes: total=%d, upserted=%d", total, upserted)
    return {"total": total, "upserted": upserted}


def get_active_stock_codes(batch_size: int = 1000) -> list[str]:
    """分页读取 ``stocks`` 表中所有 ``is_active=1`` 的股票代码。

    :param batch_size: 单页行数,默认 1000
    :return: 去重保序的活跃股票代码列表
    """
    con = get_client()
    codes: list[str] = []
    offset = 0
    while True:
        with _lock:
            rows = con.execute(
                "SELECT code FROM stocks WHERE is_active = 1 "
                "ORDER BY code LIMIT ? OFFSET ?",
                (batch_size, offset),
            ).fetchall()
        page = [row["code"] for row in rows]
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


def search_active_stocks(keyword: str, limit: int = 20) -> list[dict]:
    """搜索 active 股票：名称包含匹配或代码前缀匹配。

    名称使用包含匹配 ``name LIKE '%keyword%'``，代码使用前缀匹配
    ``code LIKE 'keyword%'``，按 ``code`` 排序并限制返回数量。

    :param keyword: 搜索关键词
    :param limit: 最多返回条数,默认 20
    :return: 每条含 ``code``、``name``、``is_active`` 的字典列表
    """
    con = get_client()
    pattern_name = f"%{keyword}%"
    pattern_code = f"{keyword}%"
    with _lock:
        rows = con.execute(
            "SELECT code, name FROM stocks "
            "WHERE is_active = 1 AND (name LIKE ? OR code LIKE ?) "
            "ORDER BY code LIMIT ?",
            (pattern_name, pattern_code, limit),
        ).fetchall()
    return [{"code": row["code"], "name": row["name"], "is_active": 1} for row in rows]
