# Stockit

个人量化选股工具 — 基于 akshare 获取中国 A 股数据，提供股票筛选与分析功能。

## 技术栈

- **后端**: Python 3.12+ / FastAPI / uvicorn / akshare
- **前端**: Next.js
- **部署**: Vercel（`/svc/api/*` 反向代理至后端）
- **数据**: 阿里云 RDS MySQL

## 目录

| 目录 | 说明 |
|------|------|
| `server/` | FastAPI 后端（Python，`uv` 管理依赖） |
| `web/` | Next.js 前端 |
| `docs/` | 数据库设计、前端规格、任务规划等文档 |
