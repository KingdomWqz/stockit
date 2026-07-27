# Stockit 股票同步入库需求文档

## 1. 背景

`stocks` 表（定义于 `../schema/schema.sql`）已建表但从未写入数据。当前股票搜索每次请求
实时调用 AKShare 获取股票列表并在内存缓存，不经过数据库。

## 2. 目标

- 将沪深 A 股全集同步入库至 `stocks` 表（排除北交所）
- 股票搜索改为读取数据库
- 所有股票端点补上 JWT 鉴权

## 3. 功能需求

### F1 股票同步

- **F1.1** 系统应提供 `POST /svc/api/stocks/sync` 端点，从 AKShare 获取沪深 A 股全集并写入 `stocks` 表（排除北交所）
- **F1.2** 数据源为 `ak.stock_info_a_code_name()`，覆盖上海、深圳两个交易所的 A 股；北交所（代码以 `4`/`8`/`9` 开头）在同步时过滤掉
- **F1.3** 同步采用 UPSERT 语义：`code` 已存在的记录更新 `name`，新 `code` 插入
- **F1.4** 同步时 UPSERT 显式设置 `is_active = true`，确保重新上市的股票自动从退市状态恢复
- **F1.5** 数据库中 `is_active = true` 但不在新列表中的股票，应标记为 `is_active = false`（退市），不删除
- **F1.6** 仅写入 `code`、`name`、`is_active` 三个字段；`industry` 留 NULL
- **F1.7** 同步时物理删除既存的北交所记录：先删子表 `stock_daily_quotes` 中引用北交所 code 的行情，再删父表 `stocks` 中的北交所股票（解除外键引用后）
- **F1.8** 端点返回同步统计：`{"total": int, "upserted": int, "deactivated": int, "deleted": int}`，其中 `deleted` 为本次物理删除的北交所股票数
- **F1.9** AKShare 拉取失败时返回 HTTP 502

### F2 股票搜索

- **F2.1** `GET /svc/api/stocks/search?keyword=xxx` 应查询 `stocks` 表，不再实时调用 AKShare
- **F2.2** 仅返回 `is_active = true`（在市）的股票
- **F2.3** 支持按代码前缀匹配和名称模糊匹配
- **F2.4** 结果包含 `code`、`name`、`market`；`market`（上海/深圳）由代码前缀推算，不存储
- **F2.5** 最多返回 20 条

### F3 鉴权

- **F3.1** 所有 `/svc/api/stocks/*` 端点应要求有效的 JWT Bearer token
- **F3.2** token 缺失、过期或无效时返回 HTTP 401
- **F3.3** `POST /svc/api/auth/login` 端点不需要鉴权

## 4. 数据需求

- 数据范围：沪深 A 股（约 5,200 只），排除北交所（代码以 `4`/`8`/`9` 开头）
- 写入字段：`code`（主键）、`name`、`is_active`
- 不涉及数据库 schema 变更（`stocks` 表已存在）

## 5. 约束

- 不新增 `market` 列到 `stocks` 表
- `industry` 暂不填充，留作后续独立富化步骤
- 个人本地单用户场景

## 6. 验收标准

- [ ] 携带有效 token 调用 `POST /svc/api/stocks/sync`，返回 `total` 约 5,200（沪深），`stocks` 表有数据
- [ ] 同步后 `stocks` 表中不存在代码以 `4`/`8`/`9` 开头的北交所记录，`stock_daily_quotes` 亦无北交所 code 的行情
- [ ] 不携带 token 访问任意 `/svc/api/stocks/*` 端点返回 401
- [ ] 携带有效 token 搜索股票，返回 DB 中在市股票的匹配结果
- [ ] 重复 sync 后，退市股标记 `is_active = false`，重新上市的股票恢复 `is_active = true`
- [ ] 搜索结果不含退市股
