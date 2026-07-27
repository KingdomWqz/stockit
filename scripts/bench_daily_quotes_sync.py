#!/usr/bin/env python3
"""Benchmark: sync one trading day of daily quotes for ALL stocks.

Calls POST /svc/api/stocks/{code}/daily-quotes/sync for every stock in the
`stocks` table, measures total elapsed time + throughput, and reports
per-stock success/failure counts. Disk size is measured separately via
Supabase SQL before/after this run.

Usage (run from repo root, with the server up on :8000):
    uv run --directory server python scripts/bench_daily_quotes_sync.py "$TOKEN"
    # optional env: CONCURRENCY=8 STOCKIT_API_BASE=... START_DATE=... END_DATE=...
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from dotenv import load_dotenv
from supabase import create_client

_ENV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server", ".env")
load_dotenv(_ENV)  # explicitly load server/.env regardless of cwd

BASE = os.getenv("STOCKIT_API_BASE", "http://localhost:8000/svc/api").rstrip("/")
TOKEN = os.environ.get("STOCKIT_TOKEN") or (sys.argv[1] if len(sys.argv) > 1 else "")
START_DATE = os.environ.get("START_DATE", "2026-07-24")
END_DATE = os.environ.get("END_DATE", "2026-07-24")
CONCURRENCY = int(os.environ.get("CONCURRENCY", "8"))
TIMEOUT = 30


def _paginated_select(select: str, table: str) -> list[dict]:
    """Page through a PostgREST select (capped at 1000 rows/page)."""
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    rows: list[dict] = []
    offset = 0
    page = 1000
    while True:
        resp = client.table(table).select(select).order("code").range(offset, offset + page - 1).execute()
        rows.extend(resp.data)
        if len(resp.data) < page:
            break
        offset += page
    return rows


def fetch_codes() -> list[str]:
    """Every stock code from `stocks`."""
    return [r["code"] for r in _paginated_select("code", "stocks")]


def fetch_missing_codes(day: str) -> list[str]:
    """Codes in `stocks` that have NO row in `stock_daily_quotes` for `day`.

    Uses SQL via the PostgREST RPC-free path is not possible for NOT EXISTS, so
    we compute the set difference in Python: all stocks minus codes present.
    """
    all_codes = {r["code"] for r in _paginated_select("code", "stocks")}
    present: set[str] = set()
    offset = 0
    page = 1000
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    while True:
        resp = (
            client.table("stock_daily_quotes")
            .select("code")
            .eq("trade_date", day)
            .range(offset, offset + page - 1)
            .execute()
        )
        present.update(r["code"] for r in resp.data)
        if len(resp.data) < page:
            break
        offset += page
    return sorted(all_codes - present)


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
    if not TOKEN:
        sys.exit("error: pass JWT via STOCKIT_TOKEN env or argv[1]")
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
    sess.headers.update({"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})

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
