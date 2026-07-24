# Stockit 技术架构文档

> 本文档描述 Stockit 当前(截至 2026-07)的运行时技术架构，基于 `server/` 与 `web/` 的实际实现整理。

## 1. 概述

Stockit 是一个个人 A 股选股工具，提供**股票搜索**与 **K 线查看**两个核心功能。前端为 Next.js 单页应用，后端为 FastAPI，数据存储于 Supabase(PostgreSQL)，行情数据通过 AKShare 与新浪财经 API 实时获取。股票列表同步由用户手动调用 `POST /svc/api/stocks/sync` 接口触发入库。

## 2. 技术栈

**后端**(`server/`)
- Python 3.12+，`uv` 管理依赖
- FastAPI + uvicorn（Web 框架 / ASGI 服务器）
- PyJWT（JWT 鉴权）
- akshare（A 股数据）、requests（新浪行情）
- supabase-py（数据库客户端，service role key 直连）
- inngest（定时任务 / 后台函数）
- pydantic（请求模型校验）

**前端**(`web/`)
- Next.js 16（App Router）+ React 19
- TanStack Query v5（数据请求与缓存）
- axios（HTTP 客户端，拦截器注入 JWT）
- Zustand（鉴权状态 + 最近浏览记录，localStorage 持久化）
- lightweight-charts（K 线图渲染）
- Tailwind CSS v4、lucide-react（图标）

**数据与基础设施**
- Supabase PostgreSQL（云端持久化存储，免费套餐）
- Inngest Dev Server / Inngest Cloud（定时任务调度）

## 3. 系统架构

```
                         浏览器 (localhost:3000)
                           │
                           ▼
                ┌──────────────────────┐
                │   Next.js (web/)     │   App Router + 中间件路由守卫
                │   - 页面/组件渲染      │   rewrites: /svc/api/* -> :8000
                │   - TanStack Query   │
                │   - Zustand (JWT)    │
                └──────────┬───────────┘
                           │  HTTP (同源反向代理 /svc/api/*)
                           ▼
                ┌──────────────────────┐
                │  FastAPI (server/)   │   uvicorn :8000
                │  - JWT 鉴权 (HTTPBearer)
                │  - 路由: auth / stocks
                │  - CORS: *            │
                └───┬──────┬──────┬─────┘
            读/写    │      │      │  定时触发
                    ▼      ▼      ▼
          ┌──────────┐ ┌─────────┐ ┌──────────────────┐
          │ Supabase │ │ AKShare │ │ 新浪财经 hq.sinajs│
          │PostgreSQL│ │ (列表/  │ │ (实时行情快照)    │
          │          │ │  K线)   │ └──────────────────┘
          └──────────┘ └─────────┘
                ▲
                │ service role key 直连 (绕过 RLS)
```

**反向代理**：Next.js 通过 `next.config.ts` 的 `rewrites` 将 `/svc/api/:path*` 转发到 `http://127.0.0.1:8000/svc/api/:path*`，实现同源调用，避免跨域。

**请求链路**：浏览器 → Next.js dev server(:3000) → rewrite → FastAPI(:8000) → Supabase / AKShare / 新浪。

## 4. 后端架构

后端为扁平模块结构（非包），各模块直接同级导入：

```
server/
├── main.py          # FastAPI 应用入口，挂载路由与中间件
├── auth.py          # 鉴权：JWT 签发 + get_current_user 依赖
├── stocks.py        # 股票业务路由：搜索/快照/K线/同步
├── db_client.py     # Supabase 客户端封装：股票字典与指标读写
├── inngest_app.py   # Inngest 定时任务：定时同步股票列表
├── pyproject.toml   # 依赖与 pytest 配置
└── tests/           # 测试
```

**应用装配**(`main.py`)
- 创建 `FastAPI(title="Stockit API", version="0.1.0")`
- 注册 CORS 中间件：`allow_origins=["*"]`、允许凭证与全部方法/头
- `auth_router` 挂载于 `/svc/api`（无鉴权）
- `stocks_router` 挂载于 `/svc/api`，**整组依赖** `Depends(get_current_user)`，即所有股票接口均需 JWT
- `inngest_app.register(app)` 条件挂载 Inngest 端点

**分层职责**
- `auth.py`：签发/校验 JWT，硬编码测试用户(`admin/admin123`)
- `stocks.py`：业务路由，直接调用 AKShare/新浪获取行情，调用 `db_client` 读写数据库
- `db_client.py`：Supabase 客户端懒加载与缓存，封装 `sync_stock_list`、`upsert_indicators`、`clean_expired_data`

> 注意：`stocks.py` 与 `db_client.py` 之间未做严格的业务/数据分层隔离，业务路由直接混用了外部数据源调用与数据库访问。

## 5. 前端架构

```
web/src/
├── app/                      # App Router 路由
│   ├── layout.tsx            # 根布局：Providers + Header
│   ├── page.tsx              # 首页：搜索 + 最近查看
│   ├── login/page.tsx        # 登录页
│   └── stocks/[code]/page.tsx# 个股 K 线页
├── components/
│   ├── Providers.tsx         # QueryClientProvider
│   ├── layout/Header.tsx     # 顶栏 + 退出
│   ├── stock/                # StockSearch / StockHeader / PeriodSelector
│   └── charts/KlineChart.tsx # lightweight-charts 封装
├── hooks/use-stocks.ts       # TanStack Query hooks
├── lib/api.ts                # axios 实例 + 拦截器
├── stores/                   # Zustand: auth.ts / recent.ts
├── types/api.ts              # 接口类型定义
└── middleware.ts             # 路由守卫
```

**路由与守卫**
- 公开路由仅 `/login`；其余(`/`、`/stocks/:code`)需登录
- `middleware.ts` 读取 `token` cookie：无 token 访问受保护页 → 重定向 `/login`；已登录访问 `/login` → 重定向 `/`

**数据流**
```
组件 → useXxx hook (TanStack Query) → api.ts (axios)
                                          │
                          请求拦截: 注入 Authorization: Bearer <token>
                          响应拦截: 401 → logout + 清 cookie + 跳 /login
```

**状态管理**
- `auth.ts`：token + user，`persist` 到 `localStorage`(`auth-storage`)
- `recent.ts`：最近浏览股票(最多 10 条)，`persist` 到 `localStorage`(`recent-stocks`)

**K 线图**(`KlineChart.tsx`)
- 基于 lightweight-charts v5，蜡烛图 + 成交量副图
- 前端本地计算 MA5/MA10/MA20/MA60 均线并叠加
- 涨跌色采用 A 股惯例(红涨绿跌)

## 6. 数据架构

数据库为 Supabase PostgreSQL，详细 Schema 见 `docs/sql/schema.sql`。

**表结构**

| 表 | 主键 | 用途 |
|------|------|------|
| `stocks` | `code` | 股票基础字典(代码/名称/行业/是否在市) |
| `stock_daily_data` | `id` (联合唯一 `code,trade_date`) | 每日行情 + 技术指标合并宽表 |

**关键设计**
- **合并宽表**：K 线基础行情与技术指标合并为单表，数值统一 `REAL`，降低存储开销
- **滑动保留**：默认保留近 90 天数据，通过存储过程 `clean_old_stock_data(retention_days)` 清理
- **Upsert 幂等**：`on_conflict="code,trade_date"` 保证重复写入覆盖
- **RLS 关闭**：个人单用户场景，使用 service role key 直连绕过 RLS
- **索引**：`(code, trade_date DESC)` 唯一索引、`(trade_date DESC, code)` 普通索引

**数据流向**
```
AKShare stock_info_a_code_name()  ──sync──▶  stocks 表 (UPSERT, 退市标记)
AKShare stock_zh_a_daily()        ──kline──▶ 实时返回前端 (不入库)
新浪 hq.sinajs.cn                 ──snapshot▶ 实时返回前端 (不入库)
(本地计算指标)                     ──upsert──▶ stock_daily_data 表
```

> 当前线上实际入库的只有 `stocks` 表(由 Inngest 定时同步)。`stock_daily_data` 指标写入由 `upsert_indicators` 提供，但尚无定时调用入口在主流程中触发。K 线与快照均为实时拉取不入库。

## 7. 鉴权机制

```
登录: POST /svc/api/auth/login  ──admin/admin123──▶  签发 JWT (HS256, 7天有效)
                                                          │
受保护接口: GET/POST /svc/api/stocks/*                      │
     │  Authorization: Bearer <token> ◀──────────────────┘
     ▼
 get_current_user: 解码 JWT → {user_id, username}
     │ 失败/缺失
     └──▶ 401 {"detail": "未认证" | "token 无效或已过期"}
```

- 算法：HS256，密钥硬编码 `stockit-dev-secret`
- Payload：`{user_id, username, exp}`，有效期 7 天(`86400*7` 秒)
- 服务间调用：Inngest 函数以 `user_id=0, username=inngest-scheduler` 签发短期(1h)JWT 调用同步接口
- 前端：token 存 `localStorage` + `cookie`，axios 拦截器自动注入

> 安全提示：密钥与测试账号硬编码于 `auth.py`，仅适用于个人本地场景。

## 8. 后台任务 (Inngest)

`inngest_app.py` 注册一个定时函数 `sync_stock_list`，工作日定时同步沪深京 A 股全集到 `stocks` 表。

```
Inngest (Dev Server :8288 / Cloud)
        │  轮询 /svc/api/inngest 发现函数
        │  按 cron 触发
        ▼
 sync_stock_list()
        │  签发 service JWT (1h)
        │  POST /svc/api/stocks/sync (Authorization: Bearer)
        ▼
 stocks.sync_stocks() → db_client.sync_stock_list() → stocks 表 UPSERT
```

**配置(环境变量)**
- `INNGEST_DEV=1`：启用本地 Dev Server 模式
- `INNGEST_SIGNING_KEY`：云模式签名密钥
- `STOCK_SYNC_CRON`：定时计划，默认 `0 8 * * 1-5`(UTC 工作日 08:00 ≈ 北京 16:00 收盘后)
- `SYNC_API_BASE_URL`：同步目标，默认 `http://localhost:8000`
- `STOCK_SYNC_TIMEOUT`：HTTP 超时秒数，默认 300

> 未配置 `INNGEST_DEV` 或 `INNGEST_SIGNING_KEY` 时，`register()` 跳过挂载并打印警告，应用仍可正常启动。

## 9. 部署与运行

**本地开发**：`scripts/start.sh` 同时启动两端，`scripts/stop.sh` 停止。
- Server：`cd server && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- Web：`cd web && npm run dev`(:3000)
- PID 记录于 `.pids/`

**环境变量**(`server/.env`)
- `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`(必需)
- Inngest 相关(可选，见上节)

**端口约定**
- 3000：Next.js 前端
- 8000：FastAPI 后端
- 8288：Inngest Dev Server(本地，外部进程)

## 10. 已知差异(实现 vs 规格文档)

`docs/frontend-spec.md` 与 `docs/stock-sync-spec.md` 为早期规格，实际实现有以下差异，文档与接口契约以**实际代码**为准：

| 项目 | 规格文档 | 实际实现 |
|------|----------|----------|
| 登录返回字段 | `access_token` | `token` |
| token 有效期 | 24h | 7 天 |
| `market` 取值 | `sh/sz/bj` | 中文 `上海/深圳/北京/未知` |
| K 线 period | `daily/weekly/monthly` | `day/week/month` |
| 快照字段 | `change_pct/change_amt` | `change/changePercent` + `high/low/open/volume/turnover` |

## 11. 相关文档

- [服务端接口契约](./api-contract.md)
- [数据库设计](./database.md)
- [数据库 Schema](./sql/schema.sql)
- [前端规格](./frontend-spec.md)
- [股票同步需求](./stock-sync-spec.md)
- [ADR-0001 同步股票入库](./adr/0001-sync-stocks-to-db.md)
