# Stockit 前端任务清单

每个任务 = 一个 MR，独立可验证。commit 自行决定。

---

## Phase 1：基础设施

### T1.1 安装依赖
```bash
cd web && pnpm add @tanstack/react-query axios lightweight-charts lucide-react zustand
```
**验证：** `pnpm list --depth=0` 确认 5 个包已安装

### T1.2 创建 API 类型定义
- 新建 `web/src/types/api.ts`
- 定义所有类型：`LoginRequest`、`LoginResponse`、`StockSearchResult`、`StockSnapshot`、`KlineData`
**验证：** `pnpm exec tsc --noEmit` 无类型错误

### T1.3 创建 axios 实例
- 新建 `web/src/lib/api.ts`
- `baseURL: '/svc/api'`
- 请求拦截器：从 localStorage 读取 token 注入 `Authorization: Bearer xxx`
- 响应拦截器：401 时清除 token，跳转 `/login`
**验证：** 导出 `api` 实例，拦截器逻辑自洽

### T1.4 创建 Auth Store
- 新建 `web/src/stores/auth.ts`
- zustand + localStorage 持久化 token 和 user
- 提供 `login()`、`logout()`、`isAuthenticated()` 方法
**验证：** 浏览器 DevTools 中可看到 token 存取正常

### T1.5 创建登录页
- 新建 `web/src/app/login/page.tsx`
- 表单：username + password + 登录按钮
- 调用 `/svc/api/auth/login` POST
- 登录成功写 token 到 AuthStore，跳转 `/`
- 登录失败展示错误提示
**验证：** 用错误的凭证登录应显示错误，正确的凭证应跳转首页

### T1.6 创建路由守卫
- 新建 `web/src/middleware.ts`
- 读取 cookie 中的 token（或检查 localStorage 不可用，改用 cookie 存储 token）
- 未登录访问 `/` 或 `/stocks/*` 时重定向到 `/login`
- 已登录访问 `/login` 时重定向到 `/`
**验证：** 未登录访问 `/` 跳转 `/login`，登录后访问 `/login` 跳转 `/`

### T1.7 创建 Layout
- 修改 `web/src/app/layout.tsx`
- 结构：Header（Logo + 搜索框占位）+ `<main>{children}</main>`
- 引入 React Query Provider
- 在 body 上根据 auth 状态控制渲染
**验证：** 页面展示 Header 和内容区域

### T1.8 创建路由占位
- 修改 `web/src/app/page.tsx`（首页占位，显示 "Dashboard"）
- 新建 `web/src/app/stocks/[code]/page.tsx`（个股页占位，显示股票代码）
**验证：** 三个路由 `/`、`/login`、`/stocks/600519` 均可访问且显示占位内容

---

## Phase 2：搜索

### T2.1 创建数据请求 hooks
- 新建 `web/src/hooks/use-stocks.ts`
- `useStockSearch(keyword)` — GET `/svc/api/stocks/search?keyword=xxx`，enabled 仅在 keyword 非空时
- `useStockSnapshot(code)` — GET `/svc/api/stocks/{code}`
- `useKlineData(code, period)` — GET `/svc/api/stocks/{code}/kline?period=xxx`
**验证：** 在浏览器 DevTools Network 中可看到请求发送

### T2.2 创建 StockSearch 搜索组件
- 新建 `web/src/components/stock/StockSearch.tsx`
- 输入框 + 搜索结果下拉列表
- 输入 debounce 300ms 后调用 `useStockSearch`
- 下拉列表展示匹配结果（代码、名称、市场标签）
- 点击结果跳转 `/stocks/{code}`
- 点击外部关闭下拉
- 加载中显示 spinner，无结果显示空状态
**验证：** 输入 "600" 应展示匹配结果下拉，点击跳转个股页

### T2.3 创建最近查看 Store
- 新建 `web/src/stores/recent.ts`
- zustand + localStorage 持久化
- 最多存 10 条，去重，最近查看在前
- 提供 `addStock(stock)`、`getRecent()` 方法
**验证：** 查看股票后，recent 列表中有该股票记录

### T2.4 实现首页
- 修改 `web/src/app/page.tsx`
- StockSearch 组件居中展示
- 最近查看股票列表（卡片形式：代码、名称、价格、涨跌幅）
- 空状态：无最近查看时显示引导文字
**验证：** 首页展示搜索框 + 最近查看列表

---

## Phase 3：K 线图

### T3.1 创建 KlineChart 组件
- 新建 `web/src/components/charts/KlineChart.tsx`
- lightweight-charts 封装
- 主图：蜡烛图（candlestick series）
- 主图叠加：MA5（白）、MA10（黄）、MA20（紫）、MA60（绿）均线
- 副图：成交量柱状图（histogram）
- 响应容器 resize
- 组件卸载时 remove chart 实例避免内存泄漏
**验证：** 传入 mock K 线数据，渲染蜡烛图 + 成交量 + 均线

### T3.2 创建 PeriodSelector 组件
- 新建 `web/src/components/stock/PeriodSelector.tsx`
- 三个按钮：日K / 周K / 月K
- 当前选中高亮
- 切换时触发父组件回调
**验证：** 点击周K，按钮高亮，父组件收到回调

### T3.3 创建 StockHeader 组件
- 新建 `web/src/components/stock/StockHeader.tsx`
- 展示：名称、代码、市场标签、最新价、涨跌幅（红涨绿跌）、涨跌额
- 加载态：骨架屏
- 错误态：提示文字
**验证：** 传入 mock 数据，正确展示红涨绿跌

### T3.4 实现个股 K 线页
- 修改 `web/src/app/stocks/[code]/page.tsx`
- 使用 `useStockSnapshot(code)` 获取个股快照
- 使用 `useKlineData(code, period)` 获取 K 线数据
- StockHeader + PeriodSelector + KlineChart 组合
- 进入页面时调用 `addStock` 记录到最近查看
- 加载态：骨架屏
- 错误态：错误提示 + 重试按钮
**验证：** 访问 `/stocks/600519`，展示完整 K 线页面，切周期刷新数据

---

## 完成标准

- [ ] 未登录 → 访问任何页面都跳转 `/login`
- [ ] 登录成功 → 跳转首页，显示搜索框
- [ ] 搜索框输入股票代码/名称 → 下拉展示匹配结果
- [ ] 点击搜索结果 → 跳转个股 K 线页
- [ ] K 线页展示蜡烛图 + 成交量 + MA 均线
- [ ] 切换日K/周K/月K → 图表数据更新
- [ ] 查看过的股票出现在首页最近查看列表
- [ ] token 过期（401）→ 自动跳转登录页