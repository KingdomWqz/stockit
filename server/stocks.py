import logging
import re
from datetime import date

import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, model_validator
import akshare as ak

import db_client

logger = logging.getLogger(__name__)

router = APIRouter()


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


def _validate_stock_code(code: str) -> None:
    """校验路径参数 code,必须为 6 位数字,否则抛 422。"""
    if not (isinstance(code, str) and len(code) == 6 and code.isdigit()):
        raise HTTPException(status_code=422, detail="code 必须为 6 位数字")


class DailyQuotesSyncRequest(BaseModel):
    """手动同步日线行情请求体。

    不暴露 ``adjust`` 字段,固定为 ``"qfq"``(由端点常量提供)。
    """

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date 不得晚于 end_date")
        return self


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
    resp = (
        db_client.get_client()
        .table("stocks")
        .select("code,name")
        .eq("is_active", True)
        .or_(f"name.ilike.%{keyword}%,code.like.{keyword}%")
        .limit(20)
        .execute()
    )
    return [
        {"code": row["code"], "name": row["name"], "market": _market_label(row["code"])}
        for row in resp.data
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


_DAILY_QUOTES_ADJUST = "qfq"


@router.post("/stocks/{code}/daily-quotes/sync")
def sync_daily_quotes(code: str, body: DailyQuotesSyncRequest):
    """手动同步单股指定日期区间的基础行情(qfq)到 ``stock_daily_quotes``。"""
    _validate_stock_code(code)

    symbol = f"{_sina_prefix(code)}{code}"
    start_str = body.start_date.strftime("%Y%m%d")
    end_str = body.end_date.strftime("%Y%m%d")

    try:
        df = ak.stock_zh_a_daily(
            symbol=symbol,
            start_date=start_str,
            end_date=end_str,
            adjust=_DAILY_QUOTES_ADJUST,
        )
    except Exception as exc:
        logger.error("AKShare 拉取失败 (code=%s): %s", code, exc)
        raise HTTPException(status_code=502, detail="行情数据获取失败")

    if df is None or df.empty:
        return {
            "code": code,
            "start_date": body.start_date.isoformat(),
            "end_date": body.end_date.isoformat(),
            "adjust": _DAILY_QUOTES_ADJUST,
            "total": 0,
            "upserted": 0,
        }

    try:
        stats = db_client.upsert_daily_quotes(df, code=code, adjust=_DAILY_QUOTES_ADJUST)
    except Exception as exc:
        logger.error("写入 stock_daily_quotes 失败 (code=%s): %s", code, exc)
        raise HTTPException(status_code=500, detail="数据库写入失败")

    return {
        "code": code,
        "start_date": body.start_date.isoformat(),
        "end_date": body.end_date.isoformat(),
        "adjust": _DAILY_QUOTES_ADJUST,
        "total": stats["total"],
        "upserted": stats["upserted"],
    }
