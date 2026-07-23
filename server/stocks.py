import logging
import re
import requests
from fastapi import APIRouter, HTTPException, Query
import akshare as ak

import db_client

logger = logging.getLogger(__name__)

router = APIRouter()

_CODE_NAME_CACHE = None


def _get_code_name_df():
    global _CODE_NAME_CACHE
    if _CODE_NAME_CACHE is None:
        _CODE_NAME_CACHE = ak.stock_info_a_code_name()
    return _CODE_NAME_CACHE


def _market_label(code: str) -> str:
    if code.startswith("6"):
        return "上海"
    if code.startswith(("0", "3")):
        return "深圳"
    if code.startswith(("4", "8", "9")):
        return "北京"
    return "未知"


def _sina_prefix(code: str) -> str:
    if code.startswith("6"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    if code.startswith(("4", "8", "9")):
        return "bj"
    return "sz"


def _fetch_sina_spot(code: str) -> dict | None:
    """Fetch real-time quote from Sina Finance API."""
    prefix = _sina_prefix(code)
    url = f"http://hq.sinajs.cn/list={prefix}{code}"
    try:
        r = requests.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=10)
        r.encoding = "gbk"
        text = r.text
        match = re.search(r'"([^"]+)"', text)
        if not match:
            return None
        fields = match.group(1).split(",")
        if len(fields) < 10 or not fields[0]:
            return None
        return {
            "name": fields[0],
            "open": float(fields[1]),
            "prevClose": float(fields[2]),
            "price": float(fields[3]),
            "high": float(fields[4]),
            "low": float(fields[5]),
            "volume": float(fields[8]),
            "turnover": float(fields[9]),
        }
    except Exception:
        return None


@router.post("/stocks/sync")
def sync_stocks():
    try:
        df = ak.stock_info_a_code_name()
    except Exception:
        raise HTTPException(status_code=502, detail="股票列表获取失败")
    return db_client.sync_stock_list(df)


@router.get("/stocks/search")
def search_stocks(keyword: str = Query(..., min_length=1)):
    try:
        df = _get_code_name_df()
    except Exception:
        raise HTTPException(status_code=502, detail="股票列表获取失败")

    mask = df["name"].str.contains(keyword, na=False) | df["code"].str.startswith(keyword, na=False)
    matched = df[mask].head(20)

    return [
        {"code": row["code"], "name": row["name"], "market": _market_label(row["code"])}
        for _, row in matched.iterrows()
    ]


@router.get("/stocks/{code}")
def stock_snapshot(code: str):
    spot = _fetch_sina_spot(code)
    if spot is None:
        raise HTTPException(status_code=502, detail="行情数据获取失败")

    price = spot["price"]
    prev_close = spot["prevClose"]
    change = price - prev_close
    change_percent = (change / prev_close * 100) if prev_close else 0

    return {
        "code": code,
        "name": spot["name"],
        "market": _market_label(code),
        "price": price,
        "change": round(change, 2),
        "changePercent": round(change_percent, 2),
        "high": spot["high"],
        "low": spot["low"],
        "open": spot["open"],
        "volume": spot["volume"],
        "turnover": spot["turnover"],
    }


@router.get("/stocks/{code}/kline")
def stock_kline(
    code: str,
    period: str = Query("day", pattern=r"^(day|week|month)$"),
):
    prefix = _sina_prefix(code)
    symbol = f"{prefix}{code}"

    try:
        df = ak.stock_zh_a_daily(
            symbol=symbol, start_date="19900101", end_date="21000101", adjust="qfq"
        )
    except Exception:
        raise HTTPException(status_code=502, detail="K线数据获取失败")

    if df is None or df.empty:
        return []

    return [
        {
            "date": str(r["date"]),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
        }
        for _, r in df.iterrows()
    ]
