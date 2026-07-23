import pandas as pd
import pytest
import akshare as ak


@pytest.fixture(autouse=True)
def _stub_akshare(monkeypatch):
    """Avoid real network calls into AKShare during auth-gate tests."""
    monkeypatch.setattr(
        ak,
        "stock_info_a_code_name",
        lambda: pd.DataFrame([{"code": "600000", "name": "浦发银行"}]),
    )


def test_stocks_search_requires_token(client):
    resp = client.get("/svc/api/stocks/search?keyword=600")
    assert resp.status_code == 401


def test_stocks_search_rejects_invalid_token(client):
    resp = client.get(
        "/svc/api/stocks/search?keyword=600",
        headers={"Authorization": "Bearer not-a-jwt"},
    )
    assert resp.status_code == 401


def test_login_endpoint_is_open(client):
    resp = client.post(
        "/svc/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200
    assert "token" in resp.json()


def test_health_endpoint_under_svc_api(client):
    resp = client.get("/svc/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
