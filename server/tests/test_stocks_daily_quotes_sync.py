"""End-to-end tests for ``POST /svc/api/stocks/{code}/daily-quotes/sync``.

Behaviour spec (docs/daily-quotes-sync-plan.md §2 + §5):
- 401 when no token
- 422 on non-6-digit code or inverted date range
- 200 with sync stats on success
- 200 with ``total=upserted=0`` when AKShare returns empty
- 502 when AKShare raises
- idempotent: same ``(code, trade_date, adjust)`` second call overwrites,
  no duplicate row.
"""

import pandas as pd
import pytest
import akshare as ak

import db_client


@pytest.fixture(autouse=True)
def _stub_akshare(monkeypatch):
    """Keep AKShare offline; individual tests override as needed."""
    monkeypatch.setattr(
        ak,
        "stock_info_a_code_name",
        lambda: pd.DataFrame([{"code": "300750", "name": "宁德时代"}]),
    )


def _quotes_df():
    """模仿 AKShare stock_zh_a_daily 真实列名(turnover 而非 turnover_rate)。"""
    return pd.DataFrame(
        [
            {"date": "2026-01-02", "open": 100.0, "high": 105.0, "low": 99.0,
             "close": 103.5, "volume": 1000, "amount": 100000.0,
             "pct_chg": 1.5, "turnover": 0.8},
            {"date": "2026-01-05", "open": 103.5, "high": 107.0, "low": 103.0,
             "close": 106.0, "volume": 1200, "amount": 120000.0,
             "pct_chg": 2.4, "turnover": 0.9},
            {"date": "2026-01-06", "open": 106.0, "high": 108.0, "low": 105.0,
             "close": 107.5, "volume": 900, "amount": 95000.0,
             "pct_chg": 1.4, "turnover": 0.7},
        ]
    )


# --------------------------------------------------------------------------- #
def test_sync_daily_quotes_requires_token(client):
    resp = client.post(
        "/svc/api/stocks/600519/daily-quotes/sync",
        json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
    )
    assert resp.status_code == 401


def test_sync_daily_quotes_rejects_non_six_digit_code(client, auth_headers):
    for bad in ["12345", "abcdef", "60051a"]:
        resp = client.post(
            f"/svc/api/stocks/{bad}/daily-quotes/sync",
            json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
            headers=auth_headers,
        )
        assert resp.status_code == 422, bad


def test_sync_daily_quotes_rejects_inverted_dates(client, auth_headers):
    resp = client.post(
        "/svc/api/stocks/600519/daily-quotes/sync",
        json={"start_date": "2026-02-01", "end_date": "2026-01-01"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_sync_daily_quotes_returns_stats_on_success(
    client, fake_db, auth_headers, monkeypatch
):
    monkeypatch.setattr(ak, "stock_zh_a_daily", lambda **kw: _quotes_df())

    resp = client.post(
        "/svc/api/stocks/600519/daily-quotes/sync",
        json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "code": "600519",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "adjust": "qfq",
        "total": 3,
        "upserted": 3,
    }
    rows = fake_db.tables["stock_daily_quotes"]
    assert len(rows) == 3
    assert all(r["code"] == "600519" and r["adjust"] == "qfq" for r in rows)


def test_sync_daily_quotes_idempotent_overwrite(
    client, fake_db, auth_headers, monkeypatch
):
    monkeypatch.setattr(ak, "stock_zh_a_daily", lambda **kw: _quotes_df())

    first = client.post(
        "/svc/api/stocks/600519/daily-quotes/sync",
        json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        headers=auth_headers,
    )
    assert first.status_code == 200
    assert first.json()["upserted"] == 3

    # Second call overwrites 2026-01-05 close only, idempotent.
    updated = _quotes_df()
    updated.loc[updated["date"] == "2026-01-05", "close"] = 222.22
    monkeypatch.setattr(ak, "stock_zh_a_daily", lambda **kw: updated)

    second = client.post(
        "/svc/api/stocks/600519/daily-quotes/sync",
        json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        headers=auth_headers,
    )
    assert second.status_code == 200
    assert second.json() == {
        "code": "600519",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "adjust": "qfq",
        "total": 3,
        "upserted": 3,
    }

    rows = fake_db.tables["stock_daily_quotes"]
    assert len(rows) == 3
    by_date = {r["trade_date"]: r for r in rows}
    assert by_date["2026-01-05"]["close"] == 222.22


def test_sync_daily_quotes_returns_502_when_akshare_fails(
    client, auth_headers, monkeypatch
):
    def boom(**kw):
        raise RuntimeError("down")

    monkeypatch.setattr(ak, "stock_zh_a_daily", boom)

    resp = client.post(
        "/svc/api/stocks/600519/daily-quotes/sync",
        json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        headers=auth_headers,
    )
    assert resp.status_code == 502


def test_sync_daily_quotes_returns_zero_when_akshare_empty(
    client, fake_db, auth_headers, monkeypatch
):
    monkeypatch.setattr(
        ak, "stock_zh_a_daily",
        lambda **kw: pd.DataFrame(columns=["date", "open", "close", "high", "low",
                                           "volume", "amount", "pct_chg",
                                           "turnover_rate"]),
    )

    resp = client.post(
        "/svc/api/stocks/600519/daily-quotes/sync",
        json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "code": "600519",
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "adjust": "qfq",
        "total": 0,
        "upserted": 0,
    }
    assert fake_db.tables["stock_daily_quotes"] == []


def test_sync_daily_quotes_passes_correct_akshare_symbol_and_dates(
    client, auth_headers, monkeypatch
):
    captured = {}

    def fake_call(symbol, start_date, end_date, adjust):
        captured["symbol"] = symbol
        captured["start_date"] = start_date
        captured["end_date"] = end_date
        captured["adjust"] = adjust
        return pd.DataFrame(columns=["date", "open", "high", "low", "close",
                                     "volume", "amount", "pct_chg",
                                     "turnover_rate"])

    monkeypatch.setattr(ak, "stock_zh_a_daily", fake_call)

    client.post(
        "/svc/api/stocks/000001/daily-quotes/sync",
        json={"start_date": "2026-01-01", "end_date": "2026-01-31"},
        headers=auth_headers,
    )

    assert captured == {
        "symbol": "sz000001",
        "start_date": "20260101",
        "end_date": "20260131",
        "adjust": "qfq",
    }