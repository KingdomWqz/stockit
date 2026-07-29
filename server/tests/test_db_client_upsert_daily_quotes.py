"""Tests for ``db_client.upsert_daily_quotes``.

Validates the basic-quote ingest helper against the contract in
``docs/projects/stockit/prd/daily-quotes-sync-plan.md`` §4 and §5 — column mapping, NaN
handling, idempotent overwrite, batching, and isolation from
``stock_daily_data``.

Tests assert directly against the SQLite ``stock_daily_quotes`` table via the
real in-memory ``fake_db`` connection.
"""

import sqlite3

import pandas as pd
import pytest

import db_client


@pytest.fixture(autouse=True)
def _seed_parent_stock(fake_db):
    """stock_daily_quotes.code 外键引用 stocks.code，先种入父行 600519。"""
    fake_db.execute(
        "INSERT INTO stocks (code, name, is_active) VALUES ('600519', '贵州茅台', 1)"
    )
    fake_db.commit()


def _quotes_rows(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT code, trade_date, adjust, open, high, low, close, volume, "
        "amount, pct_chg, turnover_rate FROM stock_daily_quotes "
        "ORDER BY trade_date"
    ).fetchall()
    return [dict(r) for r in rows]


def _sample_df():
    """模仿 AKShare stock_zh_a_daily 的真实列名(turnover 而非 turnover_rate)。"""
    return pd.DataFrame(
        [
            {
                "date": "2026-01-02",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 103.5,
                "volume": 1000,
                "amount": 100000.0,
                "pct_chg": 1.5,
                "turnover": 0.8,
            },
            {
                "date": "2026-01-03",
                "open": 103.5,
                "high": 107.0,
                "low": 103.0,
                "close": 106.0,
                "volume": 1200,
                "amount": 120000.0,
                "pct_chg": 2.4,
                "turnover": 0.9,
            },
            {
                "date": "2026-01-06",
                "open": 106.0,
                "high": 108.0,
                "low": 105.0,
                "close": 107.5,
                "volume": 900,
                "amount": 95000.0,
                "pct_chg": 1.4,
                "turnover": 0.7,
            },
        ]
    )


def test_upsert_daily_quotes_writes_new_rows(fake_db):
    df = _sample_df()

    result = db_client.upsert_daily_quotes(df, code="600519")

    assert result == {"total": 3, "upserted": 3}
    rows = _quotes_rows(fake_db)
    assert len(rows) == 3
    by_date = {r["trade_date"]: r for r in rows}
    assert by_date["2026-01-02"]["close"] == 103.5
    assert by_date["2026-01-02"]["adjust"] == "qfq"
    assert by_date["2026-01-02"]["code"] == "600519"
    assert by_date["2026-01-06"]["volume"] == 900
    # AKShare 列 turnover 映射到 DB 列 turnover_rate
    assert by_date["2026-01-02"]["turnover_rate"] == 0.8


def test_upsert_daily_quotes_overwrites_same_key(fake_db):
    df1 = _sample_df()
    db_client.upsert_daily_quotes(df1, code="600519")

    overwrite = _sample_df().iloc[[0]].assign(close=999.99)
    result = db_client.upsert_daily_quotes(overwrite, code="600519")

    assert result == {"total": 1, "upserted": 1}
    rows = _quotes_rows(fake_db)
    assert len(rows) == 3  # no duplicate row added
    by_date = {r["trade_date"]: r for r in rows}
    assert by_date["2026-01-02"]["close"] == 999.99
    # untouched rows keep original values
    assert by_date["2026-01-03"]["close"] == 106.0


def test_upsert_daily_quotes_empty_df(fake_db):
    df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    result = db_client.upsert_daily_quotes(df, code="600519")

    assert result == {"total": 0, "upserted": 0}
    assert _quotes_rows(fake_db) == []


def test_upsert_daily_quotes_missing_date_column(fake_db):
    df = pd.DataFrame(
        [
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
        ]
    )

    with pytest.raises(ValueError, match="date"):
        db_client.upsert_daily_quotes(df, code="600519")
    assert _quotes_rows(fake_db) == []


def test_upsert_daily_quotes_batches_small_batch_size(fake_db):
    result = db_client.upsert_daily_quotes(_sample_df(), code="600519", batch_size=2)

    assert result == {"total": 3, "upserted": 3}
    assert len(_quotes_rows(fake_db)) == 3


def test_upsert_daily_quotes_does_not_touch_daily_data(fake_db):
    con = fake_db
    con.execute(
        "INSERT INTO stock_daily_data (code, trade_date, close, pct_chg, turnover_rate) "
        "VALUES (?, ?, ?, ?, ?)",
        ("600519", "2026-01-02", 99.0, 0.0, 0.5),
    )
    con.commit()
    snapshot = [
        dict(r) for r in con.execute(
            "SELECT code, trade_date, close, pct_chg, turnover_rate FROM stock_daily_data"
        ).fetchall()
    ]

    db_client.upsert_daily_quotes(_sample_df(), code="600519")

    after = [
        dict(r) for r in con.execute(
            "SELECT code, trade_date, close, pct_chg, turnover_rate FROM stock_daily_data"
        ).fetchall()
    ]
    assert after == snapshot


def test_upsert_daily_quotes_handles_nan(fake_db):
    df = pd.DataFrame(
        [
            {
                "date": "2026-01-02",
                "open": float("nan"),
                "high": 105.0,
                "low": 99.0,
                "close": 103.5,
                "volume": float("nan"),
                "amount": float("nan"),
                "pct_chg": 1.5,
                "turnover": float("nan"),
            },
        ]
    )

    db_client.upsert_daily_quotes(df, code="600519")

    [row] = _quotes_rows(fake_db)
    assert row["open"] is None
    assert row["amount"] is None
    assert row["turnover_rate"] is None
    assert row["volume"] is None
    assert row["close"] == 103.5


def test_upsert_daily_quotes_coerces_volume_to_int(fake_db):
    """AKShare volume 是 float(如 2733342.0),DB 列是 INTEGER。

    helper 必须转成 int，避免类型不一致。
    """
    df = pd.DataFrame(
        [
            {
                "date": "2026-01-02",
                "open": 100.0,
                "high": 105.0,
                "low": 99.0,
                "close": 103.5,
                "volume": 2733342.0,
                "amount": 100000.0,
                "turnover": 0.8,
            },
        ]
    )

    db_client.upsert_daily_quotes(df, code="600519")

    [row] = _quotes_rows(fake_db)
    assert row["volume"] == 2733342
    assert isinstance(row["volume"], int)
