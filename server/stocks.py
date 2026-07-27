import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import JSONResponse
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


class BulkDailyQuotesSyncRequest(BaseModel):
    """全市场批量同步日线行情请求体。

    沿用单股接口的 ``start<=end`` 校验,并增加 **5 天区间上限护栏**:
    全市场批量同步的耗时与风控压力主要来自股票数(~5500 次调用),
    与日期跨度无关;但过宽区间会线性放大写入行数与单任务时长,故设 5 天上限。
    护栏独立于单股 ``DailyQuotesSyncRequest``,避免把上限强加给单股端点
    (单股支持任意区间回补)。
    """

    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _check_range(self):
        if self.start_date > self.end_date:
            raise ValueError("start_date 不得晚于 end_date")
        if (self.end_date - self.start_date).days > 5:
            raise ValueError("日期区间不得超过 5 天")
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


# --------------------------------------------------------------------------- #
# 全市场批量日线同步(后台任务)
#
# 对标 PRD docs/projects/stockit/prd/daily-quotes-sync-plan.md §8「全市场批量入库」
# 与 scripts/bench_daily_quotes_sync.py 的并发+重试策略。复用 stock_daily_quotes
# 表与 db_client.upsert_daily_quotes,不新增表。
# --------------------------------------------------------------------------- #
_BULK_CONCURRENCY = 4
_BULK_RETRIES = 2
_BULK_PROGRESS_EVERY = 500


@dataclass
class BulkSyncJob:
    """全市场批量同步任务的进程内状态快照。

    任务态仅存于进程内存(``_BULK_JOBS``),进程重启即丢——个人手动触发场景
    下可接受的权衡(对标 PRD「不做队列/调度」约束)。
    """

    job_id: str
    status: str  # pending | running | completed | failed
    start_date: date
    end_date: date
    total_stocks: int = 0
    upserted: int = 0
    empty: int = 0
    failed: int = 0
    failed_codes: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: int | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "total_stocks": self.total_stocks,
            "upserted": self.upserted,
            "empty": self.empty,
            "failed": self.failed,
            "failed_codes": list(self.failed_codes),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": self.elapsed_ms,
            "error": self.error,
        }


_BULK_JOBS: dict[str, BulkSyncJob] = {}
_BULK_JOBS_LOCK = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sync_one_stock(code: str, start_str: str, end_str: str) -> tuple[str, int]:
    """同步单只股票 qfq 日线,含 2 次线性退避重试。

    重试对标 ``scripts/bench_daily_quotes_sync.py`` 的 ``sync_one``:akshare 拉取
    异常或数据库写入异常均重试(后者因 PostgREST 偶发断连);空 DataFrame 视为
    暂停股的有效结果,不重试。

    :return: ``(kind, n)`` 其中 kind ∈ {"upserted","empty","failed"}
    """
    symbol = f"{_sina_prefix(code)}{code}"
    for attempt in range(_BULK_RETRIES + 1):
        try:
            df = ak.stock_zh_a_daily(
                symbol=symbol,
                start_date=start_str,
                end_date=end_str,
                adjust=_DAILY_QUOTES_ADJUST,
            )
        except Exception as exc:
            logger.warning("akshare 拉取失败 (code=%s, attempt=%d): %s", code, attempt, exc)
            if attempt < _BULK_RETRIES:
                time.sleep(1.0 * (attempt + 1))
                continue
            return ("failed", 0)

        if df is None or df.empty:
            return ("empty", 0)

        try:
            stats = db_client.upsert_daily_quotes(df, code=code, adjust=_DAILY_QUOTES_ADJUST)
        except Exception as exc:
            logger.warning("写入失败 (code=%s, attempt=%d): %s", code, attempt, exc)
            if attempt < _BULK_RETRIES:
                time.sleep(1.0 * (attempt + 1))
                continue
            return ("failed", 0)
        return ("upserted", stats["upserted"])
    return ("failed", 0)


def _run_bulk_sync(job_id: str, start_date: date, end_date: date) -> None:
    """后台执行全市场 qfq 日线批量入库。

    整体 try/except 兜底:任何未捕获异常置 ``status="failed"``+``error``,
    绝不冒泡杀进程。逐股结果聚合到 ``BulkSyncJob``;单股失败仅计入
    ``failed``/``failed_codes``,不让整个任务失败。
    """
    job = _BULK_JOBS.get(job_id)
    if job is None:  # pragma: no cover - 防御性
        return
    started = time.time()
    with _BULK_JOBS_LOCK:
        job.status = "running"
        job.started_at = _now_iso()
    try:
        codes = db_client.get_active_stock_codes()
        with _BULK_JOBS_LOCK:
            job.total_stocks = len(codes)
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        upserted = 0
        empty = 0
        failed = 0
        failed_codes: list[str] = []
        done = 0
        with ThreadPoolExecutor(max_workers=_BULK_CONCURRENCY) as ex:
            futs = {ex.submit(_sync_one_stock, c, start_str, end_str): c for c in codes}
            for fut in as_completed(futs):
                code = futs[fut]
                try:
                    kind, n = fut.result()
                except Exception as exc:  # 线程内未预期异常
                    logger.error("批量任务异常 (code=%s): %s", code, exc)
                    kind, n = ("failed", 0)
                if kind == "upserted":
                    upserted += n
                elif kind == "empty":
                    empty += 1
                else:
                    failed += 1
                    failed_codes.append(code)
                done += 1
                if done % _BULK_PROGRESS_EVERY == 0:
                    with _BULK_JOBS_LOCK:
                        job.upserted = upserted
                        job.empty = empty
                        job.failed = failed
                        job.failed_codes = list(failed_codes)

        with _BULK_JOBS_LOCK:
            job.upserted = upserted
            job.empty = empty
            job.failed = failed
            job.failed_codes = failed_codes
            job.finished_at = _now_iso()
            job.elapsed_ms = int((time.time() - started) * 1000)
            job.status = "completed"
    except Exception as exc:
        logger.error("批量同步任务 %s 失败: %s", job_id, exc)
        with _BULK_JOBS_LOCK:
            job.status = "failed"
            job.error = str(exc)
            job.finished_at = _now_iso()
            job.elapsed_ms = int((time.time() - started) * 1000)


@router.post("/stocks/daily-quotes/sync")
def sync_bulk_daily_quotes(
    body: BulkDailyQuotesSyncRequest,
    background_tasks: BackgroundTasks,
):
    """全市场批量同步 qfq 日线到 ``stock_daily_quotes``(后台执行,立即返回 202)。

    对 ``stocks`` 表中全部活跃股票按 ``[start_date, end_date]``(≤5 天)拉取
    qfq 日线并 UPSERT。单日全市场约 5-10 分钟,故后台执行、返回 job_id 供
    ``GET /stocks/daily-quotes/sync/{job_id}`` 轮询。
    """
    job_id = uuid4().hex
    job = BulkSyncJob(
        job_id=job_id,
        status="pending",
        start_date=body.start_date,
        end_date=body.end_date,
    )
    with _BULK_JOBS_LOCK:
        _BULK_JOBS[job_id] = job
    background_tasks.add_task(_run_bulk_sync, job_id, body.start_date, body.end_date)
    return JSONResponse(
        status_code=202,
        content={
            "job_id": job_id,
            "status": "pending",
            "status_url": f"/svc/api/stocks/daily-quotes/sync/{job_id}",
        },
    )


@router.get("/stocks/daily-quotes/sync/{job_id}")
def get_bulk_sync_status(job_id: str):
    """查询全市场批量同步任务状态。未知 job_id 返回 404。"""
    with _BULK_JOBS_LOCK:
        job = _BULK_JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job.to_dict()
