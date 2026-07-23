import pandas as pd
import akshare as ak

import db_client


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
    monkeypatch.setattr(ak, "stock_info_a_code_name", lambda: (_ for _ in ()).throw(RuntimeError("down")))

    resp = client.post("/svc/api/stocks/sync", headers=auth_headers)

    assert resp.status_code == 502


def test_sync_requires_token(client):
    resp = client.post("/svc/api/stocks/sync")
    assert resp.status_code == 401
