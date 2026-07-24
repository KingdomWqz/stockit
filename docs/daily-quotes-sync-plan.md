# 基础行情入库 API 实施计划

本文档描述 Stockit 基础日行情入库接口的实施计划。目标是先提供一个可手动调用的 API，把单只股票指定日期区间的基础行情写入数据库；本阶段不做任务调度。

## 1. 目标

```text
手动调用 API
      |
      v
校验股票代码与日期区间
      |
      v
从 AKShare 拉取单股日线基础行情
      |
      v
标准化字段与数据类型
      |
      v
UPSERT 写入基础行情表
      |
      v
返回同步统计
```

成功标准：

- 提供一个受 JWT 保护的手动同步接口。
- 支持单只股票、指定日期区间同步。
- 默认使用前复权 `qfq` 行情。
- 基础行情写入独立表，不与指标、策略、回测结果耦合。
- 重复同步同一股票、同一日期、同一复权口径时覆盖旧数据，不产生重复记录。
- 不引入 cron、后台任务、队列或第三方调度服务。

## 2. API 设计

```text
POST /svc/api/stocks/{code}/daily-quotes/sync
Authorization: Bearer <token>
Content-Type: application/json
```

请求体：

```json
{
  "start_date": "2026-01-01",
  "end_date": "2026-01-31"
}
```

响应体：

```json
{
  "code": "600519",
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "adjust": "qfq",
  "total": 20,
  "upserted": 20
}
```

接口行为：

- `code` 从路径读取，要求为 6 位数字。
- `start_date`、`end_date` 使用 `YYYY-MM-DD`。
- `start_date` 不得晚于 `end_date`。
- `adjust` 本阶段不暴露为请求参数，固定为 `qfq`。
- AKShare 无数据时返回成功响应，`total = 0`、`upserted = 0`。

错误语义：

```text
401  未登录或 token 无效
422  请求参数非法，例如 code 格式错误、日期格式错误、开始日期晚于结束日期
502  AKShare 拉取失败
500  数据库写入失败
```

## 3. 数据库设计

新增独立基础行情表：

```sql
CREATE TABLE IF NOT EXISTS public.stock_daily_quotes (
    id BIGSERIAL PRIMARY KEY,
    code TEXT NOT NULL REFERENCES public.stocks(code),
    trade_date DATE NOT NULL,
    adjust TEXT NOT NULL DEFAULT 'qfq',
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume BIGINT,
    amount REAL,
    pct_chg REAL,
    turnover_rate REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (code, trade_date, adjust)
);
```

索引：

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_stock_daily_quotes_code_date_adjust
ON public.stock_daily_quotes (code, trade_date DESC, adjust);

CREATE INDEX IF NOT EXISTS idx_stock_daily_quotes_date_code
ON public.stock_daily_quotes (trade_date DESC, code);
```

设计说明：

- 独立表只存基础行情，后续指标表、策略表、回测表通过 `code + trade_date` 关联。
- `adjust` 入唯一键，为以后扩展不复权或后复权保留空间。
- 本阶段实际只写入 `qfq`。
- `created_at`、`updated_at` 用于审计；如需严格自动更新 `updated_at`，后续可补触发器。

## 4. 后端实现

新增数据库写入能力：

```text
upsert_daily_quotes(code, df_quotes, adjust="qfq", batch_size=500)
```

职责：

- 接收 AKShare 返回的 DataFrame。
- 映射字段到数据库列。
- 统一日期为 `YYYY-MM-DD`。
- 将 NaN 转为 null。
- 按批次 upsert 到 `stock_daily_quotes`。
- 使用 `on_conflict="code,trade_date,adjust"` 保证幂等。

字段映射：

```text
date          -> trade_date
open          -> open
high          -> high
low           -> low
close         -> close
volume        -> volume
amount        -> amount
pct_chg       -> pct_chg
turnover_rate -> turnover_rate
```

新增路由处理：

```text
接收请求
  |
  +--> 校验 code 与日期区间
  |
  +--> 调用 AKShare 获取 qfq 日线
  |
  +--> 调用 upsert_daily_quotes 写库
  |
  `--> 返回同步统计
```

AKShare 调用约定：

```text
ak.stock_zh_a_daily(
    symbol=<market_prefix + code>,
    start_date=<YYYYMMDD>,
    end_date=<YYYYMMDD>,
    adjust="qfq"
)
```

其中市场前缀沿用当前逻辑：

```text
6xxxxx        -> sh
0xxxxx/3xxxxx -> sz
4/8/9xxxxx    -> bj
```

## 5. 测试计划

数据库 helper 测试：

- 空 DataFrame 返回 `total = 0`、`upserted = 0`。
- 标准 DataFrame 正确写入 `stock_daily_quotes`。
- 同一 `code + trade_date + adjust` 重复写入时覆盖旧值。
- 缺少必要字段时抛出明确异常。

API 测试：

- 未携带 token 调用返回 `401`。
- 合法请求调用成功，返回 code、日期范围、adjust、total、upserted。
- AKShare 抛异常时返回 `502`。
- AKShare 返回空数据时返回 `total = 0`。
- 日期倒置返回 `422`。
- code 非 6 位数字返回 `422`。

回归测试：

- 现有股票列表同步接口不受影响。
- 现有股票搜索接口不受影响。
- 现有 K 线展示接口不受影响。

## 6. 不做范围

本阶段明确不做：

- 全市场批量同步。
- 定时任务、后台任务、cron、队列。
- 技术指标计算。
- K 线形态识别。
- 策略筛选。
- 回测或收益验证。
- 前端页面入口。

## 7. 后续扩展

后续可以在这个基础上继续扩展：

```text
单股基础行情入库
      |
      +--> 全市场批量入库
      |
      +--> 技术指标计算
      |
      +--> 策略信号生成
      |
      +--> 回测验证
      |
      `--> 外部调度器手动调用 API
```
