"""Inngest 集成测试：验证 Dev Server 可通过 /svc/api/inngest 同步并发现函数。"""

import inngest_app

sync_stock_list = inngest_app.sync_stock_list


def test_sync_endpoint_registered_and_discoverable(client):
    """GET /svc/api/inngest 返回 probe 摘要，确认函数已注册、运行于 Dev 模式。"""
    resp = client.get("/svc/api/inngest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "dev"
    assert body["function_count"] >= 1


def test_sync_function_triggers_configured():
    """sync_stock_list 同时配置了 cron（定时）与 event（手动触发）。"""
    assert sync_stock_list.id == "stockit-sync_stock_list"

    crons = []
    events = []
    for trigger in sync_stock_list._triggers:
        if hasattr(trigger, "cron"):
            crons.append(trigger.cron)
        if hasattr(trigger, "event"):
            events.append(trigger.event)

    assert crons, "缺少 cron 触发器"
    assert "stock/sync.requested" in events
