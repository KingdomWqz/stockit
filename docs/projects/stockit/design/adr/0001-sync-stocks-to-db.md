# 同步股票列表入库，搜索改为读数据库

原先股票搜索每次请求都实时调用 `ak.stock_info_a_code_name()`（内存缓存），不经过数据库。
现决定新增 `POST /svc/api/stocks/sync` 端点，将沪深 A 股全集 UPSERT 到 `stocks` 表（排除北交所）；
搜索端点改为查询 `stocks` 表并过滤退市股（`is_active = true`）。

同步采用 UPSERT（`on_conflict = 'code'`，显式带 `is_active = true` 以支持重新上市自动激活），
DB 中有但新列表没有的股票标记 `is_active = false`（不删除，保留历史关联）。
北交所（代码以 `4`/`8`/`9` 开头）在入参阶段即被过滤，同步时物理删除 `stocks` 及
`stock_daily_quotes` 表中既存的北交所记录（先删子表行情、再删父表股票，以解除外键引用）。

代价是数据库须先同步一次搜索才有数据，且列表新鲜度取决于同步频率；
收益是搜索更快、更稳定（不依赖 AKShare 实时可用性），且能过滤退市股。
