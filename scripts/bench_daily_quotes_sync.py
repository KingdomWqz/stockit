#!/usr/bin/env python3
"""Benchmark: sync one trading day of daily quotes for ALL stocks.

Calls POST /svc/api/stocks/{code}/daily-quotes/sync for every stock in the
`stocks` table, measures total elapsed time + throughput, and reports
per-stock success/failure counts.

Usage (run from repo root, with the server up on :8000):
    uv run --directory server python scripts/bench_daily_quotes_sync.py
    # optional env: CONCURRENCY=8 STOCKIT_API_BASE=... START_DATE=... END_DATE=...
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv

_SERVER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"
)
_ENV = os.path.join(_SERVER_DIR, ".env")
load_dotenv(_ENV)  # explicitly load server/.env regardless of cwd

BASE = os.getenv("STOCKIT_API_BASE", "http://localhost:8000/svc/api").rstrip("/")
START_DATE = os.environ.get("START_DATE", "2026-07-24")
END_DATE = os.environ.get("END_DATE", "2026-07-24")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "8"))
TIMEOUT = 30


def _read_only_connection() -> sqlite3.Connection:
    """打开只读 SQLite 连接，DATABASE_PATH 默认 data/stockit.db。"""
    db_path = os.getenv("DATABASE_PATH", os.path.join(_SERVER_DIR, "data", "stockit.db"))
    if not os.path.isabs(db_path):
        db_path = os.path.join(_SERVER_DIR, db_path)
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def fetch_codes() -> list[str]:
    """Every stock code from `stocks`."""
    con = _read_only_connection()
    try:
        rows = con.execute("SELECT code FROM stocks ORDER BY code").fetchall()
    finally:
        con.close()
    return [r["code"] for r in rows]


def fetch_missing_codes(day: str) -> list[str]:
    """Codes in `stocks` that have NO row in `stock_daily_quotes` for `day`."""
    con = _read_only_connection()
    try:
        rows = con.execute(
            "SELECT s.code FROM stocks s "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM stock_daily_quotes q "
            "  WHERE q.code = s.code AND q.trade_date = ?"
            ") "
            "ORDER BY s.code",
            (day,),
        ).fetchall()
    finally:
        con.close()
    return [r["code"] for r in rows]


def sync_one(sess: requests.Session, code: str, retries: int = 2) -> tuple[int, dict | str]:
    """POST the sync endpoint with a small retry on transient 5xx/network errors."""
    last = (599, "")
    for attempt in range(retries + 1):
        try:
            r = sess.post(
                f"{BASE}/stocks/{code}/daily-quotes/sync",
                json={"start_date": START_DATE, "end_date": END_DATE},
                timeout=TIMEOUT,
            )
        except requests.RequestException as e:
            last = (599, f"network: {e}")
            time.sleep(1.0 * (attempt + 1))
            continue
        if r.status_code == 200:
            return 200, r.json()
        last = (r.status_code, r.text)
        # Retry only transient server-side / gateway failures, not 4xx.
        if r.status_code in (500, 502, 503, 504) and attempt < retries:
            time.sleep(1.0 * (attempt + 1))
            continue
        break
    return last


def main() -> None:
    retry_missing = "--retry-missing" in sys.argv
    if retry_missing:
        codes = fetch_missing_codes(START_DATE)
        label = "retry-missing"
    else:
        codes = fetch_codes()
        label = "full"
    print(f"mode={label} codes={len(codes)} concurrency={CONCURRENCY} date={START_DATE}..{END_DATE}")
    print(f"base={BASE}")

    sess = requests.Session()
    sess.headers.update({"Content-Type": "application/json"})

    ok = empty = fail = total_upserted = 0
    failures: list[tuple[str, str]] = []
    done = 0
    t0 = time.perf_counter()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        futs = {ex.submit(sync_one, sess, c): c for c in codes}
        for fut in as_completed(futs):
            code = futs[fut]
            try:
                sc, body = fut.result()
            except Exception as e:  # noqa: BLE001
                fail += 1
                failures.append((code, f"exc: {e}"))
            else:
                if sc == 200:
                    ok += 1
                    up = int(body.get("upserted", 0))  # type: ignore[union-attr]
                    total_upserted += up
                    if up == 0:
                        empty += 1
                else:
                    fail += 1
                    failures.append((code, f"{sc}: {body}"))
            done += 1
            if done % 500 == 0:
                el = time.perf_counter() - t0
                print(f"  progress {done}/{len(codes)} | {el:.1f}s | ok={ok} empty={empty} fail={fail}")

    elapsed = time.perf_counter() - t0
    print("=" * 64)
    print(f"total={len(codes)} ok={ok} (empty={empty}) fail={fail} upserted={total_upserted}")
    print(f"elapsed={elapsed:.2f}s throughput={len(codes)/elapsed:.2f} stocks/s "
          f"avg={elapsed/len(codes)*1000:.1f}ms/stock")
    if failures:
        print(f"failures(first 20): {failures[:20]}")


if __name__ == "__main__":
    main()
