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

- `server/` — FastAPI backend application (Python project root, contains pyproject.toml)
- `web/` — Next.js frontend application
- `docs/` — Project documentation and planning artifacts

## Conventions

- Use `uv` for all Python package operations (not pip), run from `server/`
- Python code follows standard PEP 8 style
- The frontend and backend are independent deployment units, decoupled via REST APIs

## Deployment

- **Frontend** (`web/`): Deploy to Vercel, set Root Directory to `web`
- **Backend** (`server/`): Deploy to Railway / Render / Fly.io, or a VPS