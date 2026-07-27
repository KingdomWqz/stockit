# 全市场批量入库基础行情（后台任务）

单股基础行情入库接口 `POST /svc/api/stocks/{code}/daily-quotes/sync` 已就绪；其 PRD
(`daily-quotes-sync-plan.md`) §7 将「全市场批量同步」列为不做范围、§8 列为后续扩展。
现决定新增 `POST /svc/api/stocks/daily-quotes/sync`,对 `stocks` 表中全部活跃股票按日期
区间批量拉取 qfq 日线并入库,即单股接口的全市场版本。

复用现有 `stock_daily_quotes` 表与 `db_client.upsert_daily_quotes`,不新增表、不改 schema、
不触碰 `stock_daily_data`。新增 `BulkDailyQuotesSyncRequest`(独立于单股
`DailyQuotesSyncRequest`),除 `start<=end` 外增加 `end - start <= 5 天` 护栏——全市场
批量同步的 AKShare 调用次数恒为活跃股票数(~5500),与日期跨度无关,但过宽区间会线性
放大写入行数与单任务时长,故设 5 天上限;该护栏不作用于单股端点(单股仍支持任意区间回补)。

全市场单日约 5–10 分钟(直连 AKShare、并发 4、无 HTTP 跳),不宜阻塞 HTTP 请求。故采用
后台执行:端点立即返回 `202 + job_id`,由 FastAPI `BackgroundTasks` 启动 `_run_bulk_sync`,
逐股 `ThreadPoolExecutor(max_workers=4)` 并发 + 2 次线性退避重试(对标
`scripts/bench_daily_quotes_sync.py` 的 `sync_one`);单股失败仅计入 `failed`/
`failed_codes`、不让整个任务失败。新增 `GET /svc/api/stocks/daily-quotes/sync/{job_id}`
轮询任务状态。

任务态存于进程内存(`_BULK_JOBS` 字典),进程重启即丢——个人手动触发场景下可接受的权衡,
亦对标 PRD「不做队列/调度」约束。代价是无法跨重启恢复、无持久化进度;收益是零新基础设施、
实现聚焦、与现有「手动同步」语义一致。
