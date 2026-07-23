# Stockit 股票同步入库任务清单

对应需求文档：`docs/stock-sync-spec.md`。每个任务 = 一个 MR，独立可验证。

---

## Phase 1：JWT 鉴权

### TS1.1 添加 JWT 校验依赖函数
- 修改 `server/auth.py`
- 导入 `Depends`、`HTTPBearer`、`HTTPAuthorizationCredentials`
- 新增 `get_current_user(credentials)` 函数：从 Bearer token 解码 JWT，失败返回 401
- 使用 `HTTPBearer(auto_error=False)`，缺失 token 时返回 401（非 403），与前端 401 拦截逻辑一致
**验证：** `cd server && uv run python -c "from auth import get_current_user"` 无报错

### TS1.2 所有股票端点启用鉴权
- 修改 `server/main.py`
- 导入 `Depends` 和 `get_current_user`
- `stocks_router` 的 `include_router` 加 `dependencies=[Depends(get_current_user)]`
- `auth_router` 不加（login 端点无需鉴权）
**验证：** 不带 token 访问 `/svc/api/stocks/search` 返回 401；带正确 token 返回 200

---

## Phase 2：同步入库

### TS2.1 实现同步写入函数
- 修改 `server/db_client.py`
- 新增 `sync_stock_list(df, batch_size=500)` 函数，逻辑：
  1. 查询 DB 中现有 `is_active = true` 的 code 集合
  2. 将 df 转为 records（`code`、`name`、`is_active = True`），分批 UPSERT（`on_conflict='code'`）
  3. 计算 `现有 active 集合 - 新列表 code 集合`，分批将这些 code 的 `is_active` 置 `False`
  4. 返回 `{"total": int, "upserted": int, "deactivated": int}`
- UPSERT 显式带 `is_active = True`，确保重新上市的股票自动激活
**验证：** 传入 mock DataFrame（含一条 DB 已有 active 的 code），函数返回正确统计；DB 中该 code 的 name 已更新、is_active 仍为 true

### TS2.2 实现同步端点
- 修改 `server/stocks.py`
- 导入 `db_client` 模块
- 新增 `@router.post("/stocks/sync")` 端点
- 调用 `ak.stock_info_a_code_name()` 获取 DataFrame，失败返回 502
- 调用 `db_client.sync_stock_list(df)`，返回结果
**验证：** 携带 token 调用 `POST /svc/api/stocks/sync`，返回 `{"total": ~5530, "upserted": N, "deactivated": M}`；DB `stocks` 表有数据

---

## Phase 3：搜索改造

### TS3.1 搜索改为查询数据库
- 修改 `server/stocks.py` 的 `search_stocks` 函数
- 查询 `stocks` 表：`.select('code,name').eq('is_active', True).or_(f'name.ilike.%{keyword}%,code.like.{keyword}%').limit(20)`
- 返回 `[{code, name, market}]`，`market` 仍由 `_market_label` 推算
**验证：** 同步后搜索 "平安" 返回匹配股票；搜索结果不含退市股

### TS3.2 移除旧的内存缓存逻辑
- 修改 `server/stocks.py`
- 删除 `_CODE_NAME_CACHE` 变量和 `_get_code_name_df()` 函数
**验证：** `rg '_CODE_NAME_CACHE|_get_code_name_df' server/stocks.py` 无结果；服务启动无报错

---

## Phase 4：端到端验证

### TS4.1 端到端测试
- 启动服务：`cd server && uv run uvicorn main:app --reload`
- 登录获取 token：`POST /svc/api/auth/login`（admin / admin123）
- 调用同步：`POST /svc/api/stocks/sync`（带 token）
- 搜索验证：`GET /svc/api/stocks/search?keyword=600`（带 token）
- 鉴权验证：不带 token 访问 `/svc/api/stocks/search` 返回 401
**验证：** 全流程通过，sync 返回合理统计，搜索返回 DB 数据

---

## 完成标准

- [ ] 所有 `/svc/api/stocks/*` 端点无 token 时返回 401
- [ ] `POST /svc/api/stocks/sync` 成功将 ~5,530 只股票写入 `stocks` 表
- [ ] 重复 sync 后，退市股被标记 `is_active = false`，重新上市的股票被激活
- [ ] 搜索查询 `stocks` 表，过滤退市股，返回正确结果
- [ ] `stocks.py` 中不再有 `_CODE_NAME_CACHE` 和实时 AKShare 搜索调用
