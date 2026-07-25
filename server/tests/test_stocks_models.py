"""Tests for the new ``stocks`` module exports used by daily-quotes sync.

Covers ``DailyQuotesSyncRequest`` (Pydantic model with date validation)
and ``_validate_stock_code`` (6-digit guard).
"""

from datetime import date

import pytest
from pydantic import ValidationError

import stocks


# --------------------------------------------------------------------------- #
# DailyQuotesSyncRequest
# --------------------------------------------------------------------------- #
def test_daily_quotes_sync_request_accepts_valid_range():
    req = stocks.DailyQuotesSyncRequest(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )

    assert req.start_date == date(2026, 1, 1)
    assert req.end_date == date(2026, 1, 31)


def test_daily_quotes_sync_request_rejects_inverted_dates():
    with pytest.raises(ValidationError):
        stocks.DailyQuotesSyncRequest(
            start_date=date(2026, 2, 1),
            end_date=date(2026, 1, 1),
        )


def test_daily_quotes_sync_request_does_not_expose_adjust():
    fields = set(stocks.DailyQuotesSyncRequest.model_fields.keys())
    assert "adjust" not in fields
    assert {"start_date", "end_date"} <= fields


# --------------------------------------------------------------------------- #
# _validate_stock_code
# --------------------------------------------------------------------------- #
def test_validate_stock_code_accepts_six_digits():
    stocks._validate_stock_code("600519")
    stocks._validate_stock_code("000001")
    stocks._validate_stock_code("300750")
    stocks._validate_stock_code("830799")


def test_validate_stock_code_rejects_non_six_digit_codes():
    from fastapi import HTTPException

    for bad in ["12345", "1234567", "abcdef", "60051a", ""]:
        with pytest.raises(HTTPException) as exc:
            stocks._validate_stock_code(bad)
        assert exc.value.status_code == 422