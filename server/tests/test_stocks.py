import sqlite3

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


def _seed_stocks(con: sqlite3.Connection, rows):
    """rows: iterable of (code, name, is_active)."""
    con.executemany(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        [(c, n, 1 if a else 0) for c, n, a in rows],
    )
    con.commit()


def _quotes_rows(con: sqlite3.Connection) -> list[dict]:
    return [
        dict(r) for r in con.execute(
            "SELECT code, trade_date, adjust FROM stock_daily_quotes ORDER BY trade_date"
        ).fetchall()
    ]


# --------------------------------------------------------------------------- #
# /stocks/sync
# --------------------------------------------------------------------------- #
def test_sync_returns_stats(client, monkeypatch):
    df = pd.DataFrame(
        [{"code": "600000", "name": "浦发银行"}, {"code": "600519", "name": "贵州茅台"}]
    )
    monkeypatch.setattr(ak, "stock_info_a_code_name", lambda: df)
    captured = {}

    def fake_sync(df_arg, batch_size=500):
        captured["df"] = df_arg
        return {"total": 2, "upserted": 2, "deactivated": 0, "deleted": 0}

    monkeypatch.setattr(db_client, "sync_stock_list", fake_sync)

    resp = client.post("/svc/api/stocks/sync")

    assert resp.status_code == 200
    assert resp.json() == {"total": 2, "upserted": 2, "deactivated": 0, "deleted": 0}
    assert list(captured["df"]["code"]) == ["600000", "600519"]


def test_sync_returns_502_when_akshare_fails(client, monkeypatch):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(ak, "stock_info_a_code_name", boom)

    resp = client.post("/svc/api/stocks/sync")

    assert resp.status_code == 502


# --------------------------------------------------------------------------- #
# sync_stock_list: 北交所过滤 + 物理删除
# --------------------------------------------------------------------------- #
def test_sync_stock_list_excludes_and_deletes_bse(fake_db):
    """sync_stock_list 应过滤北交所 code 不入库，并物理删除既存北交所残留。

    覆盖：
    - 入参 df 含北交所 code（830799/920000）→ 不写入 stocks
    - stocks 表已有北交所残留 → 物理删除
    - stock_daily_quotes 有引用北交所 code 的行情 → 先删子表、再删父表
    - 返回统计含 deleted 字段
    """
    con = fake_db
    # 既有数据：沪深各一条在市 + 北交所残留（股票表 + 行情表）
    con.executemany(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        [
            ("600519", "贵州茅台", 1),
            ("830799", "某北交所旧", 1),
            ("920000", "某北交所旧2", 1),
        ],
    )
    con.executemany(
        "INSERT INTO stock_daily_quotes (code, trade_date, adjust, open, high, low, close, volume) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("830799", "2026-07-24", "qfq", 1.0, 1.0, 1.0, 1.0, 1),
            ("920000", "2026-07-24", "qfq", 2.0, 2.0, 2.0, 2.0, 2),
        ],
    )
    con.commit()

    df = pd.DataFrame([
        {"code": "600519", "name": "贵州茅台"},   # 沪，已在库 → 更新
        {"code": "000001", "name": "平安银行"},   # 深，新 → 插入
        {"code": "830799", "name": "某北交所新"},  # 北 → 过滤掉，不入库
    ])
    stats = db_client.sync_stock_list(df)

    # 入库 code 仅沪深两条
    written_codes = {
        r["code"] for r in con.execute("SELECT code FROM stocks").fetchall()
    }
    assert written_codes == {"600519", "000001"}

    # 北交所行情已从子表删除
    quote_codes = {
        r["code"] for r in con.execute("SELECT code FROM stock_daily_quotes").fetchall()
    }
    assert "830799" not in quote_codes and "920000" not in quote_codes

    # 统计：total=2（沪深），deleted=2（两条北交所股票）
    assert stats["total"] == 2
    assert stats["upserted"] == 2
    assert stats["deleted"] == 2


# --------------------------------------------------------------------------- #
# /stocks/search (DB-backed)
# --------------------------------------------------------------------------- #
def test_search_returns_active_name_matches_from_db(client, fake_db):
    _seed_stocks(
        fake_db,
        [("600519", "贵州茅台", True), ("000001", "平安银行", True), ("000002", "平安退", False)],
    )
    resp = client.get("/svc/api/stocks/search?keyword=平安")

    assert resp.status_code == 200
    data = resp.json()
    assert {"code": "000001", "name": "平安银行", "market": "深圳"} in data
    assert all(d["code"] != "000002" for d in data)


def test_search_matches_by_code_prefix(client, fake_db):
    _seed_stocks(
        fake_db,
        [("600519", "贵州茅台", True), ("600000", "浦发银行", True), ("000001", "平安银行", True)],
    )
    resp = client.get("/svc/api/stocks/search?keyword=600")

    assert resp.status_code == 200
    data = resp.json()
    assert {d["code"] for d in data} == {"600519", "600000"}
    assert all(d["market"] == "上海" for d in data)


def test_search_limits_to_20(client, fake_db):
    _seed_stocks(fake_db, [(f"{i:06d}", f"股票{i}", True) for i in range(25)])
    resp = client.get("/svc/api/stocks/search?keyword=股票")

    assert resp.status_code == 200
    assert len(resp.json()) == 20


def test_legacy_in_memory_cache_removed():
    import stocks

    assert not hasattr(stocks, "_CODE_NAME_CACHE")
    assert not hasattr(stocks, "_get_code_name_df")
