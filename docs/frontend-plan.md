# Stockit 前端实施计划

## 1. 功能范围

两个核心功能，不多不少：

1. **搜索股票** — 输入代码或名称，自动补全匹配结果
2. **查看 K 线图** — 展示蜡烛图 + 成交量 + MA 均线，支持切换日K/周K/月K

## 2. 路由

```
/login          → 登录页
/               → 首页（搜索入口 + 最近查看的股票列表）
/stocks/[code]  → 个股 K 线图
```

## 3. 组件树

### 3.1 布局

```
RootLayout
├── Header（Logo + 搜索框）
└── <main>{children}</main>
```

### 3.2 首页 `/`

```
HomePage
├── SearchInput（自动补全，输入代码/名称搜索）
│   └── SearchDropdown（搜索结果列表，点击跳转个股页）
└── RecentStocks（最近查看的股票，localStorage 持久化）
    └── StockCard[]（代码、名称、最新价、涨跌幅）
```

### 3.3 个股K线 `/stocks/[code]`

```
KlinePage
├── StockHeader（名称、代码、最新价、涨跌幅、涨跌额）
├── PeriodSelector（日K / 周K / 月K 切换按钮组）
└── KlineChart（lightweight-charts 封装）
    ├── 蜡烛图主图
    ├── MA5 / MA10 / MA20 / MA60 均线叠加
    └── 成交量副图
```

## 4. 鉴权

JWT Token 方案：

- 登录后后端返回 `access_token`，有效期 24h
- 前端存 localStorage
- axios 请求拦截器自动带 `Authorization: Bearer xxx`
- 响应拦截器捕获 401，清除 token 并跳转 `/login`
- 路由守卫：未登录用户访问任何页面都重定向到 `/login`

### 4.1 Auth Store（zustand + localStorage）

```typescript
interface AuthStore {
  token: string | null;
  user: { id: string; username: string } | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: () => boolean;
}
```

### 4.2 组件树

**登录页 `/login`**
```
LoginPage
└── LoginForm（username + password + 登录按钮 + 错误提示）
```

## 5. API 契约

```typescript
// 登录
interface LoginRequest {
  username: string;
  password: string;
}

interface LoginResponse {
  access_token: string;
  user: { id: string; username: string };
}

// 搜索
interface StockSearchResult {
  code: string;       // "600519"
  name: string;       // "贵州茅台"
  market: 'sh' | 'sz' | 'bj';
}

// 个股快照
interface StockSnapshot {
  code: string;
  name: string;
  market: 'sh' | 'sz' | 'bj';
  price: number;
  change_pct: number;
  change_amt: number;
}

// K线
interface KlineData {
  date: string;       // "2026-07-22"
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
```

## 6. 后端 API

| 用途 | Endpoint | 方法 | 鉴权 |
|------|----------|------|------|
| 登录 | `/svc/api/auth/login` | POST | 否 |
| 搜索股票 | `/svc/api/stocks/search?keyword=xxx` | GET | 是 |
| 个股快照 | `/svc/api/stocks/{code}` | GET | 是 |
| K线数据 | `/svc/api/stocks/{code}/kline?period=daily\|weekly\|monthly` | GET | 是 |

## 7. 依赖

| 包名 | 用途 |
|------|------|
| `@tanstack/react-query` | 数据请求缓存 |
| `axios` | HTTP 客户端（拦截器注入 JWT） |
| `lightweight-charts` | K 线图渲染 |
| `lucide-react` | 图标 |
| `zustand` | Auth 状态 + 最近查看记录 |

## 8. 实施任务

详见 [tasks.md](./tasks.md)，共 3 个 Phase、16 个独立任务，每个任务 = 一个 commit = 一个 MR。