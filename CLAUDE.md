# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Stockit is an AI Investment System V3 — a strategy iteration and auto-review platform. It uses Python 3.12+ with FastAPI, uvicorn, and akshare for Chinese stock market data.

## Commands

```bash
# Install Python dependencies
cd server && uv sync

# Run the FastAPI backend locally
cd server && uv run uvicorn main:app --reload --port 8000

# Initialize Next.js frontend (one-time)
cd web && pnpm install

# Run the Next.js frontend locally
cd web && pnpm dev
```

## Architecture

```
stockit/
├── vercel.json       # Vercel Services config — routes /svc/api/* to backend
├── server/           # FastAPI backend (Python project root)
│   ├── pyproject.toml
│   ├── uv.lock
│   └── main.py       # FastAPI entry point: app = FastAPI()
├── web/              # Next.js frontend
└── docs/             # Project documentation and plans
```

## Deployment

The entire project deploys to Vercel as a single monorepo using Vercel Services:

- **`vercel.json`** declares two services:
  - `backend` — `server/` directory, FastAPI via `entrypoint: "main:app"`
  - `frontend` — `web/` directory, Next.js
- Rewrites route `/svc/api/*` → backend, everything else → frontend
- Frontend calls the backend at `/svc/api/...` (same origin, no CORS issues in production)

Local development runs both services separately (see Commands above).