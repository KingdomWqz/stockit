# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Stockit is an AI Investment System V3 — a strategy iteration and auto-review platform. It uses Python 3.12+ with FastAPI, uvicorn, and akshare for Chinese stock market data.

## Commands

```bash
# Install Python dependencies
cd server && uv sync

# Run the server
cd server && uv run stockit
# or
cd server && uv run uvicorn server.main:app --reload
```

## Architecture

- `server/` — FastAPI backend (Python project root, contains pyproject.toml)
- `web/` — Next.js frontend application
- `docs/` — Project documentation and plans

## Deployment

- **Frontend** (`web/`): Deploy to Vercel, set Root Directory to `web`
- **Backend** (`server/`): Deploy to Railway / Render / Fly.io, or a VPS