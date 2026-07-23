"""Inngest 集成：定时同步股票列表。

Inngest Dev Server（默认 http://localhost:8288）会轮询本应用由
``inngest.fast_api.serve`` 挂载的 ``/svc/api/inngest`` 端点，发现函数并按 cron
计划调用 ``sync_stock_list``。该函数以受信 service 身份通过 HTTP 调用 server
受 JWT 保护的 ``POST /svc/api/stocks/sync`` 接口完成沪深京 A 股全集同步。
"""

import logging
import os
import time

import httpx
import inngest
import jwt

from auth import SECRET

logger = logging.getLogger("uvicorn.inngest")
logger.setLevel(logging.DEBUG)

inngest_client = inngest.Inngest(app_id="stockit", logger=logger)

# 同步目标：本 server 的股票同步接口（个人本地单机场景默认指向自身）。
SYNC_API_BASE_URL = os.getenv("SYNC_API_BASE_URL", "http://localhost:8000")
# 定时计划（5 段 cron，UTC）。默认工作日 08:00 UTC ≈ 北京时间 16:00（收盘后）。
SYNC_CRON = os.getenv("STOCK_SYNC_CRON", "0 8 * * 1-5")
# HTTP 调用超时：同步约 5500 只股票分批写库，留足余量。
SYNC_TIMEOUT = int(os.getenv("STOCK_SYNC_TIMEOUT", "300"))


def _make_service_token() -> str:
    """签发短期 service JWT，以受信客户端身份调用受保护的同步接口。"""
    return jwt.encode(
        {
            "user_id": 0,
            "username": "inngest-scheduler",
            "exp": int(time.time()) + 3600,
        },
        SECRET,
        algorithm="HS256",
    )


@inngest_client.create_function(
    fn_id="sync_stock_list",
    name="同步股票列表",
    trigger=[
        inngest.TriggerCron(cron=SYNC_CRON),
        inngest.TriggerEvent(event="stock/sync.requested"),
    ],
    retries=2,
)
async def sync_stock_list(ctx: inngest.Context) -> dict:
    """定时调用 server 的股票列表同步接口。"""
    url = f"{SYNC_API_BASE_URL}/svc/api/stocks/sync"
    headers = {"Authorization": f"Bearer {_make_service_token()}"}
    ctx.logger.info("开始同步股票列表: %s", url)

    async with httpx.AsyncClient(timeout=SYNC_TIMEOUT) as client:
        resp = await client.post(url, headers=headers)

    if resp.status_code != 200:
        ctx.logger.error("同步失败: HTTP %s %s", resp.status_code, resp.text)
        raise RuntimeError(
            f"同步接口返回 HTTP {resp.status_code}: {resp.text}"
        )

    result = resp.json()
    ctx.logger.info("同步完成: %s", result)
    return result


def _is_dev_mode() -> bool:
    """是否显式启用本地 Dev Server 模式（INNGEST_DEV 为真值）。"""
    return os.getenv("INNGEST_DEV", "").strip().lower() in {"1", "true", "yes", "on"}


def register(app) -> None:
    """将 Inngest 函数挂载到 FastAPI 应用，暴露 /svc/api/inngest 同步端点。

    仅当显式启用本地 Dev 模式（``INNGEST_DEV``）或配置云签名密钥
    （``INNGEST_SIGNING_KEY``）时才挂载；否则跳过，保证应用在未配置 Inngest
    时仍可正常启动。本地配合 Inngest Dev Server 使用时需设置 ``INNGEST_DEV=1``。
    """
    import inngest.fast_api

    if not (_is_dev_mode() or os.getenv("INNGEST_SIGNING_KEY")):
        logger.warning(
            "Inngest 未启用：设置 INNGEST_DEV=1（本地 Dev Server）或 "
            "INNGEST_SIGNING_KEY（云）后重启以启用定时股票同步"
        )
        return

    inngest.fast_api.serve(
        app,
        inngest_client,
        [sync_stock_list],
        serve_path="/svc/api/inngest",
    )
