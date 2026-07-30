import sqlite3

import pandas as pd

import db_client


def _stocks_rows(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute("SELECT code, name, is_active FROM stocks ORDER BY code").fetchall()
    return [dict(r) for r in rows]


def test_sync_stock_list_upserts_updates_and_deactivates(fake_db):
    con = fake_db
    con.executemany(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        [("600519", "贵州茅台", 1), ("000001", "平安银行", 1)],
    )
    con.commit()
    df = pd.DataFrame(
        [
            {"code": "600519", "name": "贵州茅台股份"},
            {"code": "600000", "name": "浦发银行"},
        ]
    )

    result = db_client.sync_stock_list(df)

    assert result == {"total": 2, "upserted": 2, "deactivated": 1, "deleted": 0}
    rows = {r["code"]: r for r in _stocks_rows(con)}
    assert rows["600519"]["name"] == "贵州茅台股份"
    assert rows["600519"]["is_active"] == 1
    assert rows["600000"]["name"] == "浦发银行"
    assert rows["600000"]["is_active"] == 1
    assert rows["000001"]["is_active"] == 0
    assert rows["000001"]["name"] == "平安银行"


def test_sync_stock_list_reactivates_delisted(fake_db):
    con = fake_db
    con.execute(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        ("688981", "中芯国际", 0),
    )
    con.commit()
    df = pd.DataFrame([{"code": "688981", "name": "中芯国际"}])

    result = db_client.sync_stock_list(df)

    assert result == {"total": 1, "upserted": 1, "deactivated": 0, "deleted": 0}
    row = con.execute("SELECT is_active FROM stocks WHERE code='688981'").fetchone()
    assert row["is_active"] == 1


def test_sync_stock_list_batches_small_batch_size(fake_db):
    con = fake_db
    df = pd.DataFrame([{"code": f"{i:06d}", "name": f"股票{i}"} for i in range(5)])

    result = db_client.sync_stock_list(df, batch_size=2)

    assert result == {"total": 5, "upserted": 5, "deactivated": 0, "deleted": 0}
    rows = _stocks_rows(con)
    assert {r["code"] for r in rows} == {f"{i:06d}" for i in range(5)}
    assert all(r["is_active"] == 1 for r in rows)


def test_get_active_stock_codes_paginates_and_filters_active(fake_db):
    con = fake_db
    con.executemany(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        [
            ("600519", "贵州茅台", 1),
            ("000001", "平安银行", 1),
            ("688981", "中芯国际", 0),
            ("600000", "浦发银行", 1),
        ],
    )
    con.commit()
    # batch_size=2 -> pages: [000001,600000] then [600519] (len 1 < 2 -> stop).
    # The inactive 688981 is filtered out before pagination. Ordered by code.
    codes = db_client.get_active_stock_codes(batch_size=2)
    assert codes == ["000001", "600000", "600519"]


def test_get_active_stock_codes_empty(fake_db):
    assert db_client.get_active_stock_codes() == []


def test_get_active_stock_codes_single_page(fake_db):
    con = fake_db
    con.executemany(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        [("600519", "贵州茅台", 1), ("688981", "中芯国际", 0)],
    )
    con.commit()
    assert db_client.get_active_stock_codes() == ["600519"]


# --------------------------------------------------------------------------- #
# search_active_stocks
# --------------------------------------------------------------------------- #
def test_search_active_stocks_by_name_substring(fake_db):
    con = fake_db
    con.executemany(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        [
            ("600519", "贵州茅台", 1),
            ("000001", "平安银行", 1),
            ("000002", "平安退", 0),
        ],
    )
    con.commit()
    rows = db_client.search_active_stocks("平安")
    codes = {r["code"] for r in rows}
    assert codes == {"000001"}
    assert rows[0]["name"] == "平安银行"


def test_search_active_stocks_by_code_prefix(fake_db):
    con = fake_db
    con.executemany(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        [
            ("600519", "贵州茅台", 1),
            ("600000", "浦发银行", 1),
            ("000001", "平安银行", 1),
        ],
    )
    con.commit()
    rows = db_client.search_active_stocks("600")
    assert {r["code"] for r in rows} == {"600000", "600519"}


def test_search_active_stocks_filters_inactive(fake_db):
    con = fake_db
    con.execute(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        ("000002", "平安退", 0),
    )
    con.commit()
    assert db_client.search_active_stocks("平安") == []


def test_search_active_stocks_limits_to_20(fake_db):
    con = fake_db
    con.executemany(
        "INSERT INTO stocks (code, name, is_active) VALUES (?, ?, ?)",
        [(f"{i:06d}", f"股票{i}", 1) for i in range(25)],
    )
    con.commit()
    rows = db_client.search_active_stocks("股票", limit=20)
    assert len(rows) == 20
