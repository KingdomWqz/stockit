import pandas as pd

import db_client


def test_sync_stock_list_upserts_updates_and_deactivates(fake_db):
    fake_db.tables["stocks"] = [
        {"code": "600519", "name": "贵州茅台", "is_active": True, "industry": None},
        {"code": "000001", "name": "平安银行", "is_active": True, "industry": None},
    ]
    df = pd.DataFrame(
        [
            {"code": "600519", "name": "贵州茅台股份"},
            {"code": "600000", "name": "浦发银行"},
        ]
    )

    result = db_client.sync_stock_list(df)

    assert result == {"total": 2, "upserted": 2, "deactivated": 1, "deleted": 0}
    rows = {r["code"]: r for r in fake_db.tables["stocks"]}
    assert rows["600519"]["name"] == "贵州茅台股份"
    assert rows["600519"]["is_active"] is True
    assert rows["600000"]["name"] == "浦发银行"
    assert rows["600000"]["is_active"] is True
    assert rows["000001"]["is_active"] is False
    assert rows["000001"]["name"] == "平安银行"


def test_sync_stock_list_reactivates_delisted(fake_db):
    fake_db.tables["stocks"] = [
        {"code": "688981", "name": "中芯国际", "is_active": False, "industry": None},
    ]
    df = pd.DataFrame([{"code": "688981", "name": "中芯国际"}])

    result = db_client.sync_stock_list(df)

    assert result == {"total": 1, "upserted": 1, "deactivated": 0, "deleted": 0}
    assert fake_db.tables["stocks"][0]["is_active"] is True


def test_sync_stock_list_batches_small_batch_size(fake_db):
    df = pd.DataFrame([{"code": f"{i:06d}", "name": f"股票{i}"} for i in range(5)])

    result = db_client.sync_stock_list(df, batch_size=2)

    assert result == {"total": 5, "upserted": 5, "deactivated": 0, "deleted": 0}
    codes = {r["code"] for r in fake_db.tables["stocks"]}
    assert codes == {f"{i:06d}" for i in range(5)}
    assert all(r["is_active"] is True for r in fake_db.tables["stocks"])
