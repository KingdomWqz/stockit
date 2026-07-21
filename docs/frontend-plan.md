# Stockit 前端实施计划

## 1. 项目初始化

### 1.1 脚手架
- 使用 `create-next-app` 在 `web/` 目录初始化
- TypeScript、Tailwind CSS、App Router、src/ 目录
- 包管理器使用 `pnpm`

### 1.2 依赖

| 类别 | 包名 | 用途 |
|------|------|------|
| 数据请求 | `@tanstack/react-query` | 服务端状态缓存、轮询、重新获取 |
| 客户端状态 | `zustand` | 轻量 UI 状态（筛选条件、主题） |
| HTTP | `axios` | HTTP 客户端，支持拦截器 |
| 图表（K线） | `lightweight-charts` | TradingView 高性能 Canvas 蜡烛图 |
| 图表（统计） | `recharts` | 仪表盘的柱状图/折线图/饼图 |
| 图标 | `lucide-react` | 图标集 |
| 表单 | `react-hook-form` + `zod` | 表单状态管理 + 校验 |
| 开发工具 | `@trivago/prettier-plugin-sort-imports` | 统一 import 排序 |

## 2. 路由设计

```
/                          → 仪表盘总览（指数、市盈率、成交额、热力图）
/stocks                    → 股票列表（搜索/筛选/排序）
/stocks/[code]             → 个股详情（K线、基本面、AI 评审）
/strategies                → 策略列表（增删改查）
/strategies/[id]           → 策略详情 + 回测结果
/strategies/[id]/backtest  → 回测配置与执行
/backtests                 → 回测历史列表
/backtests/[id]            → 回测结果详情（权益曲线、指标）
/reviews                   → AI 评审历史
/reviews/[id]              → 单条评审详情
/settings                  → 用户偏好（数据源、通知）
```

## 3. 组件树

### 3.1 布局
```
RootLayout
├── Sidebar
│   ├── Logo
│   ├── NavGroup（"概览"）
│   │   └── NavItem（仪表盘）
│   ├── NavGroup（"股票"）
│   │   └── NavItem（股票列表）
│   ├── NavGroup（"策略"）
│   │   ├── NavItem（策略列表）
│   │   └── NavItem（回测记录）
│   ├── NavGroup（"分析"）
│   │   └── NavItem（AI 评审）
│   └── NavItem（设置）
├── Header
│   ├── Breadcrumb
│   ├── SearchBar（全局股票搜索）
│   └── ThemeToggle
└── <main>（页面内容）
```

### 3.2 页面

**仪表盘 `/`**
```
DashboardPage
├── StatsRow（4 张卡片：指数、成交额、涨跌比、活跃策略数）
├── MarketHeatmap（板块涨跌热力图）
├── TopMovers（涨幅/跌幅榜表格）
└── RecentReviews（近期 AI 评审卡片）
```

**股票列表 `/stocks`**
```
StockListPage
├── FilterBar（板块、市场、市盈率区间等）
├── StockTable
│   ├── StockRow（代码、名称、价格、涨跌幅、市盈率、成交量）
│   └── Pagination
└── QuickChart（hover 时显示迷你 sparkline）
```

**个股详情 `/stocks/[code]`**
```
StockDetailPage
├── StockHeader（名称、代码、现价、涨跌幅、总市值）
├── KlineChart（蜡烛图 + 成交量 + 均线叠加）
├── TabPanel
│   ├── Tab：基本面（市盈率、市净率、ROE、营收增速）
│   ├── Tab：AI 评审（该股历史评审记录）
│   └── Tab：关联策略（绑定的策略与信号）
└── NewsPanel（近期公告）
```

**策略列表 `/strategies`**
```
StrategyListPage
├── StrategyCard[]
│   ├── 名称、描述、状态标签
│   ├── 指标（胜率、总收益、夏普比率）
│   └── 操作（编辑、回测、删除）
└── CreateStrategyButton → Modal
```

**策略详情 `/strategies/[id]`**
```
StrategyDetailPage
├── StrategyHeader（名称、编辑按钮、状态切换）
├── StrategyCode（语法高亮代码块）
├── BacktestSummary（迷你权益曲线 + 关键指标）
├── SignalLog（近期买卖信号）
└── BacktestHistory（关联回测列表）
```

**回测详情 `/backtests/[id]`**
```
BacktestDetailPage
├── BacktestHeader（策略名称、回测区间、状态）
├── EquityCurveChart（权益曲线 vs 基准）
├── MetricsGrid
│   ├── 总收益率、年化收益、最大回撤
│   ├── 夏普比率、卡尔玛比率、胜率
│   ├── 平均盈亏比、盈亏因子
│   └── 换手率、交易次数
├── TradeList（逐笔交易明细表）
├── MonthlyReturns（月度收益热力图）
└── DrawdownChart（回撤曲线）
```

**AI 评审详情 `/reviews/[id]`**
```
ReviewDetailPage
├── ReviewHeader（股票、日期、模型版本）
├── ScoreCard（综合评分 + 子项评分）
├── AnalysisText（Markdown 分析报告）
├── RelatedCharts（关联图表快照）
└── ActionHistory（人工反馈记录）
```

### 3.3 共享组件

```
components/
├── ui/                    # 基础 UI 组件
│   ├── Button
│   ├── Input
│   ├── Select
│   ├── Table
│   ├── Tabs
│   ├── Card
│   ├── Badge
│   ├── Modal
│   ├── Spinner
│   └── Pagination
├── charts/
│   ├── KlineChart          # lightweight-charts 封装
│   ├── EquityCurve         # lightweight-charts 封装
│   ├── BarChart            # recharts 封装
│   ├── PieChart            # recharts 封装
│   └── Heatmap             # recharts 封装
├── data/
│   ├── DataTable           # 带排序/筛选/分页的表格
│   ├── FilterBar           # 可复用的筛选栏
│   └── StatCard            # 单指标展示卡片
├── layout/
│   ├── Sidebar
│   ├── Header
│   └── PageContainer
└── stock/
    ├── StockSearch         # 自动补全股票搜索
    ├── StockBadge          # 代码 + 名称 + 市场标签
    └── PriceChange         # 红涨绿跌价格展示
```

## 4. API 契约（前端类型定义）

```typescript
// types/api.ts

// --- 股票 ---
interface StockListItem {
  code: string;        // 如 "600519"
  name: string;        // 如 "贵州茅台"
  market: 'sh' | 'sz' | 'bj';
  price: number;
  change_pct: number;
  pe: number;
  pb: number;
  volume: number;
  turnover: number;
  sector: string;
}

interface StockDetail extends StockListItem {
  market_cap: number;
  circulating_cap: number;
  high_52w: number;
  low_52w: number;
  roe: number;
  revenue_growth: number;
  kline: KlineData[];
}

interface KlineData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// --- 策略 ---
interface Strategy {
  id: string;
  name: string;
  description: string;
  code: string;
  status: 'active' | 'paused' | 'draft';
  metrics: StrategyMetrics | null;
  created_at: string;
  updated_at: string;
}

interface StrategyMetrics {
  win_rate: number;
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe: number;
  trade_count: number;
}

// --- 回测 ---
interface Backtest {
  id: string;
  strategy_id: string;
  strategy_name: string;
  period: { start: string; end: string };
  status: 'running' | 'completed' | 'failed';
  metrics: BacktestMetrics | null;
  equity_curve: EquityPoint[];
  trades: Trade[];
  created_at: string;
}

interface BacktestMetrics {
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  sharpe: number;
  calmar: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  profit_factor: number;
  turnover_rate: number;
  trade_count: number;
}

interface EquityPoint {
  date: string;
  equity: number;
  benchmark: number;
}

interface Trade {
  date: string;
  type: 'buy' | 'sell';
  code: string;
  price: number;
  quantity: number;
  pnl: number;
  pnl_pct: number;
  reason: string;
}

// --- AI 评审 ---
interface Review {
  id: string;
  stock_code: string;
  stock_name: string;
  date: string;
  model_version: string;
  overall_score: number;
  sub_scores: Record<string, number>;
  report: string;   // markdown 格式
  charts: string[];  // 图表图片 URL
}

// --- 仪表盘 ---
interface DashboardData {
  index: { name: string; value: number; change_pct: number }[];
  stats: {
    total_stocks: number;
    up_count: number;
    down_count: number;
    active_strategies: number;
  };
  sectors: { name: string; change_pct: number }[];
  top_movers: StockListItem[];
  recent_reviews: Review[];
}
```

## 5. 状态管理

### React Query（服务端状态）
- `useStockList(filters)` — 股票列表，带分页
- `useStockDetail(code)` — 单只股票详情
- `useKlineData(code, period)` — K 线数据
- `useStrategyList()` — 全部策略
- `useStrategy(id)` — 单条策略
- `useBacktestList(filters)` — 回测历史
- `useBacktest(id)` — 回测详情（状态为 running 时自动轮询）
- `useReviewList(filters)` — AI 评审历史
- `useReview(id)` — 单条评审
- `useDashboard()` — 仪表盘聚合数据

### Zustand（客户端状态）
```typescript
interface AppStore {
  // 主题
  theme: 'light' | 'dark';
  toggleTheme: () => void;

  // 侧边栏
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;

  // 全局股票搜索
  searchQuery: string;
  setSearchQuery: (q: string) => void;

  // 筛选条件
  stockFilters: StockFilters;
  setStockFilters: (f: Partial<StockFilters>) => void;
}
```

## 6. 实施顺序

### 第一阶段：骨架搭建（1-2 天）
1. `create-next-app` 初始化，TypeScript、Tailwind、App Router
2. 安装依赖
3. 搭建布局：Sidebar + Header + PageContainer
4. 实现主题切换（暗色/亮色）
5. 初始化 Zustand store
6. 初始化 React Query provider + axios 实例
7. 创建 API 类型定义文件
8. 所有页面路由占位

### 第二阶段：核心页面（3-5 天）
1. 仪表盘页面，使用 mock 数据
2. 股票列表页面，包含 DataTable
3. 个股详情页面，包含 KlineChart
4. 接入 React Query hooks（指向 mock 或 BFF 层）

### 第三阶段：策略与回测（6-8 天）
1. 策略列表 + 创建/编辑弹窗
2. 策略详情页面
3. 回测详情页面，包含全部图表
4. 回测列表页面

### 第四阶段：评审与打磨（9-10 天）
1. 评审列表 + 详情页面
2. 空状态、加载骨架屏、错误边界
3. 响应式适配
4. 性能审查（包体积、懒加载）

## 7. 待定问题

1. **认证方案** — 是否需要用户/认证系统？如果需要，用 JWT 还是 session？
2. **实时数据** — 仪表盘是否需要 WebSocket 推送实时行情，还是轮询就够了？
3. **回测执行** — 回测是前端触发（长时任务）还是服务端预先计算好的？
4. **K 线图表库** — 推荐 `lightweight-charts` 以获得最佳性能，是否有其他偏好（如 `echarts`）？
5. **UI 组件库** — 基于 Tailwind 从零构建基础组件，还是使用 headless 库如 Radix UI / shadcn/ui？