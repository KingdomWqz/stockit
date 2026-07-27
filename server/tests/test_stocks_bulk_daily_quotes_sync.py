"""End-to-end tests for the bulk daily-quotes sync API.

POST /svc/api/stocks/daily-quotes/sync        -> 202 + job_id (background task)
GET  /svc/api/stocks/daily-quotes/sync/{job_id} -> job status snapshot

Behaviour spec (docs/projects/stockit/prd/bulk-daily-quotes-sync-plan.md):
- 401 when no token
- 422 on inverted dates or range > 5 days
- 202 with job_id + status_url; GET unknown job_id -> 404
- background task aggregates upserted/empty/failed; partial failure -> status
  ``completed`` with ``failed_codes`` (not a 500)
- single-stock endpoint still accepts >5-day ranges (the 5-day cap is bulk-only)
"""

import time

import pandas as pd
import pytest
import akshare as ak

import db_client
import stocks


def _quotes_df():
    """Tiny per-stock qfq df mirroring ``ak.stock_zh_a_daily`` columns."""
    return pd.DataFrame(
        [{"date": "2026-07-24", "open": 10.0, "high": 11.0, "low": 9.5,
          "close": 10.5, "volume": 1000, "amount": 10500.0,
          "pct_chg": 1.0, "turnover": 0.5}]
    )


def _raise_no_stub(**_kw):
    raise RuntimeError("akshare must be stubbed in tests")


@pytest.fixture(autouse=True)
def _bulk_test_isolation(monkeypatch):
    """Keep akshare offline and skip retry backoff; tests override as needed."""
    monkeypatch.setattr(ak, "stock_zh_a_daily", _raise_no_stub)
    monkeypatch.setattr(time, "sleep", lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _clear_jobs():
    """Isolate the in-memory job registry between tests."""
    stocks._BULK_JOBS.clear()
    yield
    stocks._BULK_JOBS.clear()


def _seed_active_stocks(fake_db, codes):
    fake_db.tables["stocks"] = [
        {"code": c, "name": f"股票{c}", "is_active": True, "industry": None}
        for c in codes
    ]


# --------------------------------------------------------------------------- #
def test_bulk_sync_requires_token(client):
    resp = client.post(
        "/svc/api/stocks/daily-quotes/sync",
        json={"start_date": "2026-07-24", "end_date": "2026-07-24"},
    )
    assert resp.status_code == 401


def test_bulk_sync_rejects_inverted_dates(client, auth_headers):
    resp = client.post(
        "/svc/api/stocks/daily-quotes/sync",
        json={"start_date": "2026-07-25", "end_date": "2026-07-24"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_bulk_sync_rejects_range_over_5_days(client, auth_headers):
    # 6-day span -> 422
    resp = client.post(
        "/svc/api/stocks/daily-quotes/sync",
        json={"start_date": "2026-07-01", "end_date": "2026-07-07"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_bulk_sync_accepts_5_day_range(client, auth_headers, monkeypatch):
    # exactly 5 days -> accepted (202); no-op background keeps it pending
    monkeypatch.setattr(stocks, "_run_bulk_sync", lambda *a, **kw: None)
    resp = client.post(
        "/svc/api/stocks/daily-quotes/sync",
        json={"start_date": "2026-07-01", "end_date": "2026-07-06"},
        headers=auth_headers,
    )
    assert resp.status_code == 202


def test_bulk_sync_returns_202_and_pending_status(client, auth_headers, monkeypatch):
    monkeypatch.setattr(stocks, "_run_bulk_sync", lambda *a, **kw: None)
    resp = client.post(
        "/svc/api/stocks/daily-quotes/sync",
        json={"start_date": "2026-07-24", "end_date": "2026-07-24"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "pending"
    assert body["job_id"]
    assert body["status_url"] == f"/svc/api/stocks/daily-quotes/sync/{body['job_id']}"

    # GET unknown job_id -> 404
    assert client.get(
        "/svc/api/stocks/daily-quotes/sync/nope", headers=auth_headers
    ).status_code == 404

    status = client.get(body["status_url"], headers=auth_headers).json()
    assert status["status"] == "pending"
    assert status["start_date"] == "2026-07-24"
    assert status["end_date"] == "2026-07-24"
    assert status["total_stocks"] == 0


def test_bulk_sync_happy_path_completes(client, fake_db, auth_headers, monkeypatch):
    _seed_active_stocks(fake_db, ["600519", "000001"])
    monkeypatch.setattr(ak, "stock_zh_a_daily", lambda **kw: _quotes_df())

    resp = client.post(
        "/svc/api/stocks/daily-quotes/sync",
        json={"start_date": "2026-07-24", "end_date": "2026-07-24"},
        headers=auth_headers,
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # TestClient runs the background task to completion before returning.
    status = client.get(
        f"/svc/api/stocks/daily-quotes/sync/{job_id}", headers=auth_headers
    ).json()
    assert status["status"] == "completed"
    assert status["total_stocks"] == 2
    assert status["upserted"] == 2
    assert status["empty"] == 0
    assert status["failed"] == 0
    assert status["failed_codes"] == []
    assert status["elapsed_ms"] is not None

    rows = fake_db.tables["stock_daily_quotes"]
    assert len(rows) == 2
    assert {r["code"] for r in rows} == {"600519", "000001"}
    assert all(r["trade_date"] == "2026-07-24" and r["adjust"] == "qfq" for r in rows)


def test_bulk_sync_partial_failure_still_completes(
    client, fake_db, auth_headers, monkeypatch
):
    _seed_active_stocks(fake_db, ["600519", "000001", "688981"])

    def fake_ak(**kw):
        # 688981 always raises (after retries) -> failed; others succeed.
        if "688981" in kw.get("symbol", ""):
            raise RuntimeError("boom")
        return _quotes_df()

    monkeypatch.setattr(ak, "stock_zh_a_daily", fake_ak)

    resp = client.post(
        "/svc/api/stocks/daily-quotes/sync",
        json={"start_date": "2026-07-24", "end_date": "2026-07-24"},
        headers=auth_headers,
    )
    job_id = resp.json()["job_id"]
    status = client.get(
        f"/svc/api/stocks/daily-quotes/sync/{job_id}", headers=auth_headers
    ).json()

    assert status["status"] == "completed"
    assert status["total_stocks"] == 3
    assert status["upserted"] == 2
    assert status["failed"] == 1
    assert status["failed_codes"] == ["688981"]


def test_bulk_sync_empty_df_counts_as_empty(
    client, fake_db, auth_headers, monkeypatch
):
    _seed_active_stocks(fake_db, ["600519"])
    empty = pd.DataFrame(columns=["date", "open", "high", "low", "close",
                                  "volume", "amount", "pct_chg", "turnover"])
    monkeypatch.setattr(ak, "stock_zh_a_daily", lambda **kw: empty)

    resp = client.post(
        "/svc/api/stocks/daily-quotes/sync",
        json={"start_date": "2026-07-24", "end_date": "2026-07-24"},
        headers=auth_headers,
    )
    job_id = resp.json()["job_id"]
    status = client.get(
        f"/svc/api/stocks/daily-quotes/sync/{job_id}", headers=auth_headers
    ).json()

    assert status["status"] == "completed"
    assert status["empty"] == 1
    assert status["upserted"] == 0
    assert status["failed"] == 0
    assert fake_db.tables["stock_daily_quotes"] == []


def test_single_stock_endpoint_unaffected_by_5_day_cap(
    client, fake_db, auth_headers, monkeypatch
):
    """Regression: single-stock endpoint still accepts a >5-day range."""
    monkeypatch.setattr(ak, "stock_zh_a_daily", lambda **kw: _quotes_df())
    # A 31-day span would be 422 under the bulk cap; single-stock must accept it.
    resp = client.post(
        "/svc/api/stocks/600519/daily-quotes/sync",
        json={"start_date": "2026-07-01", "end_date": "2026-07-31"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["upserted"] == 1
