# AGENTS.md

本文件为 AI 编程代理在本仓库中工作时提供指引。

## 项目:Stockit

选股器

## 技术栈

- **Python 3.12+**,使用 `uv` 管理依赖
- **FastAPI** + **uvicorn** 作为后端服务器
- **Next.js** 作为前端框架
- **akshare** 获取中国股市数据

## 目录结构

- `server/` - FastAPI 后端应用(Python 项目根目录,含 `pyproject.toml`)
- `web/` - Next.js 前端应用
- `docs/` - 项目文档与规划资料

## 约定

- 所有 Python 包操作使用 `uv`(而非 pip),在 `server/` 下运行
- Python 代码遵循标准 PEP 8 风格
- 前端通过 `/svc/api/...` 调用后端(同源反向代理)
