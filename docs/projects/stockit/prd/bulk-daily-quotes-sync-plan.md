# 全市场基础行情批量入库 API 实施计划

本文档描述 Stockit 全市场批量基础日行情入库接口的实施计划,对应
`daily-quotes-sync-plan.md` §8「全市场批量入库」后续扩展。目标是对 `stocks` 表中
全部活跃股票批量拉取 qfq 日线并写入 `stock_daily_quotes`,复用既有表与 helper,不新增表。

## 1. 目标

```text
POST /stocks/daily-quotes/sync {start_date, end_date}
      |
      v
校验日期区间(start<=end, 且 end-start<=5 天)
      |
      v
登记任务态 _BULK_JOBS[job_id]=pending, BackgroundTasks 启动后台 fan-out
      |
      v
逐股(并发4 + 重试2) ak.stock_zh_a_daily(qfq) -> db_client.upsert_daily_quotes
      |
      v
聚合 upserted/empty/failed, 回写任务态, status=completed
      |
      v
GET /stocks/daily-quotes/sync/{job_id} 轮询状态
```

成功标准:

- 提供一个受 JWT 保护的手动批量同步接口,立即返回 `202 + job_id`。
- 复用 `stock_daily_quotes` 与 `db_client.upsert_daily_quotes`,不新增表、不改 schema。
- 日期区间 ≤5 天护栏(独立于单股端点)。
- 单股失败不阻断整体,聚合 `failed_codes`,任务以 `completed` 结束。
- 不引入 cron、后台队列、调度服务。

## 2. API 设计

```text
POST /svc/api/stocks/daily-quotes/sync
Authorization: Bearer <token>
Content-Type: application/json
```

请求体:

```json
{
  "start_date": "2026-07-24",
  "end_date": "2026-07-24"
}
```

响应体(`202`):

```json
{
  "job_id": "<hex>",
  "status": "pending",
  "status_url": "/svc/api/stocks/daily-quotes/sync/<job_id>"
}
```

状态查询:

```text
GET /svc/api/stocks/daily-quotes/sync/{job_id}
Authorization: Bearer <token>
```

状态响应(`200`):

```json
{
  "job_id": "...",
  "status": "running|completed|failed",
  "start_date": "2026-07-24",
  "end_date": "2026-07-24",
  "total_stocks": 5530,
  "upserted": 5524,
  "empty": 5,
  "failed": 1,
  "failed_codes": ["689009"],
  "started_at": "2026-07-27T08:00:00+00:00",
  "finished_at": "2026-07-27T08:09:43+00:00",
  "elapsed_ms": 283000,
  "error": null
}
```

接口行为:

- `start_date`、`end_date` 使用 `YYYY-MM-DD`,`start_date` 不得晚于 `end_date`。
- **护栏**:`end_date - start_date` 不得超过 5 天,否则 `422`(防止误触发超长/超重批量任务)。
- 端点不阻塞:立即登记任务、返回 `202 + job_id`,实际拉取在后台进行。
- 单股 AKShare/DB 异常**不**让整个任务失败,计入 `failed` + `failed_codes`,其余继续。
- `empty` = AKShare 返回空(暂停股);任务态存于进程内存,进程重启即丢。

错误语义:

```text
401  未登录或 token 无效
422  请求参数非法(日期倒置、区间超 5 天)
404  job_id 不存在
500  服务端内部异常(后台任务整体失败时,任务态置 status=failed + error)
```

## 3. 数据库设计

**不新增表**。复用 `stock_daily_quotes`(见 `daily-quotes-sync-plan.md` §3),唯一键
`(code, trade_date, adjust)` 保证幂等覆盖。新增的只是读取入口:

```text
db_client.get_active_stock_codes(batch_size=1000) -> list[str]
```

职责:

- 分页读取 `stocks` 表中 `is_active=true` 的 `code`(PostgREST 单次 select 上限约 1000 行,
  用 `.range(from, to)` 分页直至取完)。
- 供全市场批量同步使用;去重保序返回。

## 4. 后端实现

新增请求模型:

```text
BulkDailyQuotesSyncRequest
  start_date: date
  end_date: date
  校验: start_date <= end_date 且 (end_date - start_date).days <= 5
```

> 独立于单股 `DailyQuotesSyncRequest`,避免把 5 天上限强加给单股端点(单股支持任意区间回补)。

新增任务态:

```text
@dataclass BulkSyncJob(job_id, status, start_date, end_date,
                       total_stocks, upserted, empty, failed, failed_codes,
                       started_at, finished_at, elapsed_ms, error)
_BULK_JOBS: dict[str, BulkSyncJob]   # 进程内,重启即丢
```

新增后台 fan-out:

```text
_run_bulk_sync(job_id, start_date, end_date):
  整体 try/except 兜底(置 failed + error,不杀进程)
  -> db_client.get_active_stock_codes()
  -> ThreadPoolExecutor(max_workers=4) 逐股 _sync_one_stock
  -> 每 500 只回写一次进度(加锁)
  -> 收尾: status=completed, failed_codes=[...]

_sync_one_stock(code, start_str, end_str) -> (kind, n):
  symbol = _sina_prefix(code) + code
  重试2次(线性退避) ak.stock_zh_a_daily(symbol, start, end, adjust="qfq")
  空 DataFrame -> ("empty", 0)            # 暂停股,不重试
  db_client.upsert_daily_quotes(df, code, adjust="qfq")
  -> ("upserted", stats["upserted"]) | ("failed", 0)
```

新增路由:

```text
POST /stocks/daily-quotes/sync            -> 202 + job_id(BackgroundTasks)
GET  /stocks/daily-quotes/sync/{job_id}    -> 任务态快照(未知 -> 404)
```

复用 `stocks.py` 既有 `_sina_prefix`、`_DAILY_QUOTES_ADJUST="qfq"`;由 `main.py` 路由级
`Depends(get_current_user)` 自动覆盖鉴权,无需改 `main.py`。

## 5. 测试计划

数据库 helper 测试(`test_db_client.py`):

- `get_active_stock_codes` 分页读取、过滤 `is_active=false`、空表返回 `[]`。

API 测试(`test_stocks_bulk_daily_quotes_sync.py`):

- 未携带 token -> `401`。
- 日期倒置 -> `422`;区间超 5 天 -> `422`;恰好 5 天 -> `202`。
- `POST` 返回 `202` + `job_id` + `status_url`;`GET` 未知 job_id -> `404`,已知 -> 任务态。
- happy path:mock 全部活跃股票 + `ak.stock_zh_a_daily` + `upsert_daily_quotes`,任务 `completed`,
  `upserted` 正确,`stock_daily_quotes` 行数正确。
- 部分失败:一股持续抛错进 `failed_codes`,其余成功,任务仍 `completed`。
- 空数据:返回空 df -> `empty` 计数、`upserted=0`。
- 回归:单股 `POST /stocks/{code}/daily-quotes/sync` 仍接受 >5 天区间(护栏仅作用于批量端点)。

## 6. 与单股接口的协同

- 批量端点复用单股端点的全部下游:`stock_daily_quotes` 表、`db_client.upsert_daily_quotes`、
  `_sina_prefix`、`_DAILY_QUOTES_ADJUST`。区别仅在编排(逐股 fan-out + 任务态)。
- `BulkDailyQuotesSyncRequest` 不复用 `DailyQuotesSyncRequest`,以免 5 天护栏污染单股端点。
- 两者写入同一张表、同一唯一键,幂等语义一致:同 `(code, trade_date, adjust)` 重复写入覆盖。

## 7. 不做范围

本阶段明确不做:

- 新增数据库表/列、改 schema。
- 定时任务、cron、队列、调度服务。
- 任务态持久化(进程内存即丢,接受此权衡)。
- 前端页面入口(与现有 sync 端点一致,均为手动/curl 触发)。
- `stock_daily_quotes` 滚动清理(独立议题)。
- 实时现价 spot 同步(`ak.stock_zh_a_spot_em`,非本需求)。

## 8. 后续扩展

```text
全市场批量入库
      |
      +--> 任务态持久化(跨重启恢复)
      |
      +--> 外部调度器每日盘后自动调用
      |
      +--> `stock_daily_quotes` 滚动清理(对标 stock_daily_data 的 90 天保留)
      |
      `--> 全市场实时现价快照(独立表,选股器筛选用)
```
