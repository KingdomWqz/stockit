# Stockit 服务端接口契约文档

> 基于 `server/` 实际代码整理，接口契约以实际实现为准。所有接口前缀为 `/svc/api`。

## 1. 通用约定

**Base URL**：`/svc/api`（前端经 Next.js rewrite 同源访问；直连后端为 `http://localhost:8000/svc/api`）

**请求格式**：`POST` 接口使用 `application/json`；`GET` 接口使用 query 参数。

**鉴权**
- 受保护接口需在请求头携带 `Authorization: Bearer <token>`
- token 由 `POST /svc/api/auth/login` 获取，HS256 JWT，有效期 7 天
- 缺失/无效/过期 -> `401`

**统一错误响应**（FastAPI 默认格式）：
```json
{ "detail": "错误描述" }
```

**CORS**：`Access-Control-Allow-Origin: *`，允许凭证与全部方法/头。

## 2. 鉴权机制

JWT(HS256)，密钥硬编码 `stockit-dev-secret`。Payload 结构：
```json
{ "user_id": 1, "username": "admin", "exp": 1234567890 }
```
测试账号：`admin` / `admin123`（硬编码于 `auth.py`）。

鉴权依赖 `get_current_user`：解码 JWT 失败返回 `401`，成功返回 `{user_id, username}`。
- `stocks` 路由组整体挂载该依赖，故所有 `/svc/api/stocks/*` 均需鉴权。
- `auth/login`、`health`、根路径不鉴权。

---

## 3. 接口清单

| 方法 | 路径 | 鉴权 | 用途 |
|------|------|------|------|
| POST | `/svc/api/auth/login` | 否 | 登录获取 token |
| POST | `/svc/api/stocks/sync` | 是 | 同步股票列表入库 |
| GET | `/svc/api/stocks/search` | 是 | 搜索股票 |
| GET | `/svc/api/stocks/{code}` | 是 | 个股实时快照 |
| GET | `/svc/api/stocks/{code}/kline` | 是 | K 线数据 |
| GET | `/svc/api/health` | 否 | 健康检查 |
| GET | `/svc/api` | 否 | 根路径信息 |

---

## 4. 接口详情

### 4.1 登录

`POST /svc/api/auth/login`

**请求体**
```json
{
  "username": "admin",
  "password": "admin123"
}
```

**成功响应** `200`
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": { "id": 1, "username": "admin" }
}
```

**失败响应** `401`
```json
{ "detail": "用户名或密码错误" }
```

**说明**：token 有效期 7 天；用户名或密码错误均返回 401。

---

### 4.2 同步股票列表

`POST /svc/api/stocks/sync`

从 AKShare `stock_info_a_code_name()` 获取沪深京 A 股全集，UPSERT 到 `stocks` 表；不在新列表中的在市股票标记 `is_active=false`（退市）。

**请求体**：无

**成功响应** `200`
```json
{
  "total": 5530,
  "upserted": 5530,
  "deactivated": 3
}
```

**失败响应** `502`
```json
{ "detail": "股票列表获取失败" }
```

**说明**：`upserted` 等于 `total`；同步耗时较长（约 5500 只），前端超时设为 10s，建议单独/手动调用。

---

### 4.3 搜索股票

`GET /svc/api/stocks/search?keyword=xxx`

查询 `stocks` 表中 `is_active=true` 的股票，支持代码前缀与名称模糊匹配，最多返回 20 条。

**Query 参数**

| 参数 | 类型 | 必填 | 约束 |
|------|------|------|------|
| keyword | string | 是 | `min_length=1` |

**成功响应** `200`
```json
[
  { "code": "600519", "name": "贵州茅台", "market": "上海" },
  { "code": "000858", "name": "五粮液", "market": "深圳" }
]
```

**说明**
- `market` 由代码前缀推算（非存储字段）：`6` -> 上海，`0/3` -> 深圳，`4/8/9` -> 北京，其余 -> 未知
- 匹配逻辑：`name.ilike.%keyword% OR code.like.keyword%`
- 依赖 `stocks` 表已同步，首次使用前需调用 4.2 同步

---

### 4.4 个股实时快照

`GET /svc/api/stocks/{code}`

从新浪财经 API(`hq.sinajs.cn`)获取实时行情。

**Path 参数**

| 参数 | 类型 | 说明 |
|------|------|------|
| code | string | 6 位股票代码，如 `600519` |

**成功响应** `200`
```json
{
  "code": "600519",
  "name": "贵州茅台",
  "market": "上海",
  "price": 1685.00,
  "change": 12.34,
  "changePercent": 0.74,
  "high": 1690.00,
  "low": 1670.00,
  "open": 1675.00,
  "volume": 123456.0,
  "turnover": 208000000.0
}
```

**失败响应** `502`
```json
{ "detail": "行情数据获取失败" }
```

**字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| code | string | 股票代码 |
| name | string | 股票名称 |
| market | string | 市场（上海/深圳/北京/未知） |
| price | number | 当前价 |
| change | number | 涨跌额（`price - prevClose`，保留 2 位） |
| changePercent | number | 涨跌幅 %（保留 2 位） |
| high | number | 最高价 |
| low | number | 最低价 |
| open | number | 开盘价 |
| volume | number | 成交量（手） |
| turnover | number | 成交额（元） |

**说明**：`change`/`changePercent` 由当前价与昨收价计算；数据不入库，实时拉取。

---

### 4.5 K 线数据

`GET /svc/api/stocks/{code}/kline?period=day`

从 AKShare `stock_zh_a_daily()` 获取前复权(`qfq`)历史 K 线，范围 `19900101` ~ `21000101`。

**Path 参数**：`code`（6 位股票代码）

**Query 参数**

| 参数 | 类型 | 必填 | 默认 | 约束 |
|------|------|------|------|------|
| period | string | 否 | `day` | 枚举 `day`/`week`/`month` |

**成功响应** `200`（数组，按日期升序）
```json
[
  {
    "date": "2026-07-22",
    "open": 1675.00,
    "high": 1690.00,
    "low": 1670.00,
    "close": 1685.00,
    "volume": 123456.0
  }
]
```

**失败响应**
- `502`：`{ "detail": "K线数据获取失败" }`
- 无数据时返回空数组 `[]`

**字段说明**

| 字段 | 类型 | 说明 |
|------|------|------|
| date | string | 交易日期 `YYYY-MM-DD` |
| open | number | 开盘价 |
| high | number | 最高价 |
| low | number | 最低价 |
| close | number | 收盘价 |
| volume | number | 成交量 |

**说明**：`period` 同时作为 AKShare 周期参数；数据为全历史前复权，体积较大。

---

### 4.6 健康检查

`GET /svc/api/health`

**响应** `200`
```json
{ "status": "ok" }
```

### 4.7 根路径

`GET /svc/api`

**响应** `200`
```json
{ "message": "Stockit API", "version": "0.1.0" }
```

---

## 5. 鉴权失败响应

| 场景 | 状态码 | 响应 |
|------|--------|------|
| 未携带 Authorization 头 | 401 | `{ "detail": "未认证" }` |
| token 无效/过期 | 401 | `{ "detail": "token 无效或已过期" }` |
| 登录凭据错误 | 401 | `{ "detail": "用户名或密码错误" }` |

---

## 6. TypeScript 类型定义

对应前端 `web/src/types/api.ts`，与后端响应一致：

```typescript
export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  user: { id: number; username: string };
}

export interface StockSearchResult {
  code: string;
  name: string;
  market: string; // "上海" | "深圳" | "北京" | "未知"
}

export interface StockSnapshot {
  code: string;
  name: string;
  market: string;
  price: number;
  change: number;
  changePercent: number;
  high: number;
  low: number;
  open: number;
  volume: number;
  turnover: number;
}

export interface KlineData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SyncResult {
  total: number;
  upserted: number;
  deactivated: number;
}
```

---

## 7. 与规格文档的差异

`../prd/frontend-spec.md` 中的早期契约与实际实现存在差异，**以本文档(实际代码)为准**：

| 项目 | 规格(`frontend-spec.md`) | 实际实现 |
|------|--------------------------|----------|
| 登录返回字段 | `access_token` | `token` |
| token 有效期 | 24h | 7 天 |
| `market` 取值 | `sh`/`sz`/`bj` | `上海`/`深圳`/`北京`/`未知` |
| K 线 period | `daily`/`weekly`/`monthly` | `day`/`week`/`month` |
| 快照字段 | `change_pct`/`change_amt` | `change`/`changePercent`(+ `high/low/open/volume/turnover`) |

---

## 8. 相关文档

- [技术架构文档](../design/architecture.md)
- [数据库设计](../design/database-design/01-architecture-and-schema.md)
- [数据库 Schema](../schema/schema.sql)
- [前端规格](../prd/frontend-spec.md)
- [股票同步需求](../prd/stock-sync-spec.md)
