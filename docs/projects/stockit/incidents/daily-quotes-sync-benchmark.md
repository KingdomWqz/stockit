# 日线行情全市场同步基准测试报告

> 测试日期: 2026-07-27
> 测试目标: 对 `POST /svc/api/stocks/{code}/daily-quotes/sync` 接口在**全市场 A 股**规模下的同步耗时与 `stock_daily_quotes` 表磁盘占用进行基准测量。

---

## 1. 测试背景

`daily-quotes/sync` 端点为**单股**同步接口,每次调用完成:AKShare 拉取 → PostgREST 批量 upsert。本项目此前未在**全市场(~5,530 只)**规模下实测过该接口,需要量化:

1. **同步耗时** —— 全市场跑一遍单日行情需要多久,瓶颈在哪。
2. **磁盘占用** —— 单日全量行情在 `stock_daily_quotes` 表中占多少空间,用于估算长期存储增长。

本次测试同步 **2026-07-24 单个交易日** 的行情数据(qfq)。

---

## 2. 测试环境与方法

### 2.1 环境

| 项 | 值 |
|---|---|
| 数据库 | 远端 Supabase Postgres(`doidksdivyowjicjzplv.supabase.co`) |
| 数据库访问 | supabase-py over PostgREST REST API(upsert 批次 500 行) |
| 应用服务器 | 本地 `uvicorn main:app`,端口 8000,cwd=`server/` |
| 接口路径 | `POST /svc/api/stocks/{code}/daily-quotes/sync` |
| 认证 | JWT Bearer(`admin`/`admin123` 登录,7 天有效期) |
| 股票总数 | 5,530 只(沪深京 A 股,全部 `is_active=true`) |
| 目标日期 | `2026-07-24`(单日,`start_date=end_date`) |
| `adjust` | 固定 `qfq`(端点常量,不可配) |

### 2.2 测试脚本

新增 `scripts/bench_daily_quotes_sync.py`,功能:

- 从 `stocks` 表分页读取全部 code(PostgREST 单页上限 1000)。
- 用 `ThreadPoolExecutor` 并发调用 sync 端点,共享 `requests.Session`(keepalive)。
- 记录每只股票的状态码 / `upserted` / 失败原因,每 500 只打印进度。
- 支持 `--retry-missing` 模式:仅重试 DB 中缺失当日行情的 code(以数据库为准,而非脚本日志)。
- 内置 2 次**瞬时错误重试**(仅对 500/502/503/504 与网络异常重试,4xx 不重试)。

### 2.3 磁盘测量

`stock_daily_quotes` 为空表(72 kB,仅 schema + 2 索引)。测试前后用 Supabase SQL 经 MCP 执行:

```sql
SELECT pg_size_pretty(pg_total_relation_size('stock_daily_quotes')) AS total_size,
       pg_size_pretty(pg_relation_size('stock_daily_quotes'))     AS table_size,
       pg_size_pretty(pg_indexes_size('stock_daily_quotes'))      AS indexes_size,
       count(*)
FROM public.stock_daily_quotes;
```

`pg_total_relation_size` 含堆 + 全部索引 + TOAST,即真实磁盘占用。

---

## 3. 测试过程

### 3.1 第一轮:全量同步(并发 8)

- 命令:`CONCURRENCY=8 uv run --directory server python scripts/bench_daily_quotes_sync.py "$TOKEN"`
- 前置:smoke test 单股(600519)耗时 4.6 s,确认端到端通路正常。

**结果:**

| 指标 | 值 |
|---|---|
| 总耗时 | **2,369.77 s ≈ 39.5 分钟** |
| 吞吐 | 2.33 stocks/s |
| 平均单股 | 428.5 ms/stock |
| 成功 | 5,218(其中 5 只 empty,当日停牌无数据) |
| upserted 行数 | 5,213 |
| 失败 | 312(5.6%),全部 `500 数据库写入失败` |

### 3.2 失败分析

服务器日志显示 312 个失败的根因均为 **`Server disconnected`**(Supabase/PostgREST HTTP 层瞬时断连),**非外键违约、非数据问题**。核验前 20 个失败 code 均在 `stocks` 表中且 `is_active=true`。

进一步以数据库为准查询**真正缺失**当日行情的 code:仅 **78 只**(而非 312 只)。说明 312 个"失败"中约 234 个实际**写入已提交**,只是 HTTP 响应在返回前断开 —— PostgREST 的 `Server disconnected` 不等于写入失败。

### 3.3 第二轮:重试缺失(并发 4)

- 命令:`CONCURRENCY=4 uv run ... --retry-missing`
- 目标:78 个真正缺失的 code,降低并发 + 内置重试。

**结果:**

| 指标 | 值 |
|---|---|
| 总耗时 | 46.49 s |
| 成功 | 77(5 只 empty 停牌) |
| upserted 行数 | 72 |
| 失败 | 1:`689009`(北交所)→ `502 行情数据获取失败`,AKShare/Sina 无该 code 当日数据 |

---

## 4. 最终结果

### 4.1 磁盘占用(`stock_daily_quotes`)

| 指标 | 测试前 | 测试后 |
|---|---|---|
| 行数 | 0 | **5,524** |
| 不同 code 数 | 0 | 5,524 |
| 总大小(堆+索引) | 72 kB | **1,376 kB (1.34 MB)** |
| ├ 表堆 | 8 kB | 656 kB |
| └ 索引 | 64 kB | 688 kB |

**单日全市场行情 ≈ 1.34 MB / 5,524 行 → 每股每日 ≈ 256 字节。**

### 4.2 数据完整性

| 项 | 值 |
|---|---|
| 活跃股票 | 5,530 |
| 已入库 code | **5,524(99.89%)** |
| 缺失 | 6 |
| └ 停牌(当日无数据) | 5 |
| └ AKShare 无数据(`689009`,北交所) | 1 |

6 个缺失均为**数据源无数据**,非同步错误。

### 4.3 耗时汇总

| 轮次 | 并发 | 耗时 |
|---|---|---|
| 全量首轮 | 8 | 39.5 分钟 |
| 重试缺失 | 4 | 46.5 s |
| **合计** | — | **≈ 40.3 分钟** |

---

## 5. 结论与发现

1. **瓶颈是 AKShare 拉取,不是 DB 写入。** 单股平均 428 ms,主要为 `ak.stock_zh_a_daily` 网络往返;PostgREST upsert 负载可忽略(单日仅 1.34 MB)。
2. **并发 8 时 Supabase/PostgREST 会偶发 `Server disconnected`。** 该错误**不代表写入失败** —— 312 个"失败"中约 75% 实际已入库。以数据库为准(查缺失 code)比信任 HTTP 响应更可靠。
3. **重试 + 降并发可收敛瞬时错误。** 并发 4 + 2 次重试后,78 个缺失仅剩 1 个真正的数据源 502。
4. **磁盘估算(长期):**
   - 单日全市场 ≈ **1.34 MB**。
   - 90 天(项目保留窗口)≈ **120 MB**(含索引)。
   - 1 年(≈250 交易日)≈ **335 MB**,接近 Supabase 免费版 500 MB 上限。
   - 全历史(1990 至今)会**远超 500 MB**,不可行 —— 需配合滑动保留策略(`../design/database-design/01-architecture-and-schema.md` 已规划 90 天保留)。

---

## 6. 建议

- **生产批量同步应降并发(≤4)并内置重试**,以规避 PostgREST 瞬时断连;或在脚本层以"查 DB 缺失 code 重试"做幂等收尾(本次脚本已实现 `--retry-missing`)。
- **`stock_daily_quotes` 当前无清理 job**(`clean_old_stock_data` 只清 `stock_daily_data`)。若长期运行全市场同步,需为该表新增滑动保留,否则会逼近 500 MB 上限。
- **北交所部分 code(如 `689009`)AKShare 无 qfq 数据**,属预期内的数据源缺失,可忽略或在监控中按"数据源无数据"分类,不与真正的同步故障混淆。
- 全市场批量同步此前在 `../prd/daily-quotes-sync-plan.md` 中列为"未来扩展";本次实测表明**单日全量可在 ~40 分钟内完成**,作为日终任务是可行的。

---

## 附:测试产物

- 脚本:`scripts/bench_daily_quotes_sync.py`
- 首轮日志:`/tmp/stockit-bench.log`
- 重试日志:`/tmp/stockit-retry.log`
- 服务器日志:`/tmp/stockit-server.log`
