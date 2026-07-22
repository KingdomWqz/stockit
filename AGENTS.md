# AGENTS.md

This file provides guidance to AI coding agents when working with code in this repository.

## Project: Stockit

AI Investment System V3 — a strategy iteration and auto-review platform for Chinese stock markets.

## Tech Stack

- **Python 3.12+** with `uv` for package management
- **FastAPI** + **uvicorn** for the backend server
- **Next.js** for the frontend framework
- **akshare** for Chinese stock market data

## Directory Structure

- `vercel.json` — Vercel Services config, routes `/svc/api/*` to backend
- `server/` — FastAPI backend application (Python project root, contains pyproject.toml)
- `web/` — Next.js frontend application
- `docs/` — Project documentation and planning artifacts

## Conventions

- Use `uv` for all Python package operations (not pip), run from `server/`
- Python code follows standard PEP 8 style
- Frontend calls backend at `/svc/api/...` (same origin, handled by Vercel rewrites)

## Deployment

The entire project deploys to Vercel as a single monorepo using Vercel Services:

- **Backend** (`server/`): FastAPI, declared as `backend` service in `vercel.json`
- **Frontend** (`web/`): Next.js, declared as `frontend` service in `vercel.json`
- Rewrites: `/svc/api/*` → backend, `/*` → frontend