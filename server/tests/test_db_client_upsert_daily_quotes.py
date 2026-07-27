"""Tests for ``db_client.upsert_daily_quotes``.

Validates the basic-quote ingest helper against the contract in
``docs/projects/stockit/prd/daily-quotes-sync-plan.md`` §4 and §5 — column mapping, NaN
handling, idempotent overwrite, batching, and isolation from
``stock_daily_data``.
"""

import pandas as pd
import pytest

import db_client


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
    rows = fake_db.tables["stock_daily_quotes"]
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
    rows = fake_db.tables["stock_daily_quotes"]
    assert len(rows) == 3  # no duplicate row added
    by_date = {r["trade_date"]: r for r in rows}
    assert by_date["2026-01-02"]["close"] == 999.99
    # untouched rows keep original values
    assert by_date["2026-01-03"]["close"] == 106.0


def test_upsert_daily_quotes_empty_df(fake_db):
    df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    result = db_client.upsert_daily_quotes(df, code="600519")

    assert result == {"total": 0, "upserted": 0}
    assert fake_db.tables["stock_daily_quotes"] == []


def test_upsert_daily_quotes_missing_date_column(fake_db):
    df = pd.DataFrame(
        [
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5},
        ]
    )

    with pytest.raises(ValueError, match="date"):
        db_client.upsert_daily_quotes(df, code="600519")
    assert fake_db.tables["stock_daily_quotes"] == []


def test_upsert_daily_quotes_batches_small_batch_size(fake_db):
    calls: list[int] = []
    original_table = fake_db.table

    def spy_table(name):
        builder = original_table(name)
        if name == "stock_daily_quotes":
            original_upsert = builder.upsert

            def recording_upsert(records, on_conflict=None):
                calls.append(len(records))
                return original_upsert(records, on_conflict)

            builder.upsert = recording_upsert
        return builder

    fake_db.table = spy_table  # type: ignore[assignment]

    result = db_client.upsert_daily_quotes(_sample_df(), code="600519", batch_size=2)

    assert result == {"total": 3, "upserted": 3}
    assert calls == [2, 1]
    assert len(fake_db.tables["stock_daily_quotes"]) == 3


def test_upsert_daily_quotes_does_not_touch_daily_data(fake_db):
    fake_db.tables["stock_daily_data"] = [
        {
            "code": "600519",
            "trade_date": "2026-01-02",
            "close": 99.0,
            "pct_chg": 0.0,
            "turnover_rate": 0.5,
        },
    ]
    snapshot = [dict(r) for r in fake_db.tables["stock_daily_data"]]

    db_client.upsert_daily_quotes(_sample_df(), code="600519")

    assert fake_db.tables["stock_daily_data"] == snapshot


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

    [row] = fake_db.tables["stock_daily_quotes"]
    assert row["open"] is None
    assert row["amount"] is None
    assert row["turnover_rate"] is None
    assert row["volume"] is None
    assert row["close"] == 103.5


def test_upsert_daily_quotes_coerces_volume_to_int(fake_db):
    """AKShare volume 是 float(如 2733342.0),DB 列是 BIGINT。

    PostgREST 把带小数的字符串送入 BIGINT 会报 22P02,helper 必须转成 int。
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

    [row] = fake_db.tables["stock_daily_quotes"]
    assert row["volume"] == 2733342
    assert isinstance(row["volume"], int)