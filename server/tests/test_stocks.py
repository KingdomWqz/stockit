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


# --------------------------------------------------------------------------- #
# /stocks/sync
# --------------------------------------------------------------------------- #
def test_sync_returns_stats(client, monkeypatch, auth_headers):
    df = pd.DataFrame(
        [{"code": "600000", "name": "浦发银行"}, {"code": "600519", "name": "贵州茅台"}]
    )
    monkeypatch.setattr(ak, "stock_info_a_code_name", lambda: df)
    captured = {}

    def fake_sync(df_arg, batch_size=500):
        captured["df"] = df_arg
        return {"total": 2, "upserted": 2, "deactivated": 0}

    monkeypatch.setattr(db_client, "sync_stock_list", fake_sync)

    resp = client.post("/svc/api/stocks/sync", headers=auth_headers)

    assert resp.status_code == 200
    assert resp.json() == {"total": 2, "upserted": 2, "deactivated": 0}
    assert list(captured["df"]["code"]) == ["600000", "600519"]


def test_sync_returns_502_when_akshare_fails(client, monkeypatch, auth_headers):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(ak, "stock_info_a_code_name", boom)

    resp = client.post("/svc/api/stocks/sync", headers=auth_headers)

    assert resp.status_code == 502


def test_sync_requires_token(client):
    resp = client.post("/svc/api/stocks/sync")
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# /stocks/search (DB-backed)
# --------------------------------------------------------------------------- #
def test_search_returns_active_name_matches_from_db(client, fake_db, auth_headers):
    fake_db.tables["stocks"] = [
        {"code": "600519", "name": "贵州茅台", "is_active": True, "industry": None},
        {"code": "000001", "name": "平安银行", "is_active": True, "industry": None},
        {"code": "000002", "name": "平安退", "is_active": False, "industry": None},
    ]
    resp = client.get("/svc/api/stocks/search?keyword=平安", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert {"code": "000001", "name": "平安银行", "market": "深圳"} in data
    assert all(d["code"] != "000002" for d in data)


def test_search_matches_by_code_prefix(client, fake_db, auth_headers):
    fake_db.tables["stocks"] = [
        {"code": "600519", "name": "贵州茅台", "is_active": True, "industry": None},
        {"code": "600000", "name": "浦发银行", "is_active": True, "industry": None},
        {"code": "000001", "name": "平安银行", "is_active": True, "industry": None},
    ]
    resp = client.get("/svc/api/stocks/search?keyword=600", headers=auth_headers)

    assert resp.status_code == 200
    data = resp.json()
    assert {d["code"] for d in data} == {"600519", "600000"}
    assert all(d["market"] == "上海" for d in data)


def test_search_limits_to_20(client, fake_db, auth_headers):
    fake_db.tables["stocks"] = [
        {"code": f"{i:06d}", "name": f"股票{i}", "is_active": True, "industry": None}
        for i in range(25)
    ]
    resp = client.get("/svc/api/stocks/search?keyword=股票", headers=auth_headers)

    assert resp.status_code == 200
    assert len(resp.json()) == 20


def test_legacy_in_memory_cache_removed():
    import stocks

    assert not hasattr(stocks, "_CODE_NAME_CACHE")
    assert not hasattr(stocks, "_get_code_name_df")
