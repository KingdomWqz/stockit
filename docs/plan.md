# Stockit Implementation Plan

## Context

Building the AI Investment System V3 from scratch — a personal AI-driven investment research platform that automates strategy iteration, daily review, and market analysis. The project is greenfield (only `docs/design.md` exists). Python 3.12 with uv, SQLite for storage, FastAPI for API, runs on local machine.

## Architecture

```
stockit/
├── server/                  # Python backend
│   ├── __init__.py
│   ├── cli.py              # CLI entry (typer)
│   ├── config.py           # Pydantic Settings
│   ├── data/               # Data layer
│   │   ├── __init__.py
│   │   ├── providers/      # AKShare, Baostock, iTick adapters
│   │   │   ├── __init__.py
│   │   │   ├── base.py     # Common interface
│   │   │   ├── akshare_adapter.py
│   │   │   ├── baostock_adapter.py
│   │   │   └── itick_adapter.py
│   │   ├── pipeline.py     # ETL: clean, dedup, cross-validate
│   │   ├── store.py        # SQLAlchemy models + queries
│   │   └── models.py       # DB schema definitions
│   ├── agents/             # AI Agent layer
│   │   ├── __init__.py
│   │   ├── base.py         # Agent base class (LLM client, tool use, JSON output)
│   │   ├── prompts/        # Prompt templates per agent
│   │   │   ├── strategy_decomposer.md
│   │   │   ├── strategy_distiller.md
│   │   │   ├── market_analyzer.md
│   │   │   ├── review_analyst.md
│   │   │   └── strategy_iterator.md
│   │   ├── orchestrator.py # Agent workflow orchestration
│   │   ├── strategy_decomposer.py
│   │   ├── strategy_distiller.py
│   │   ├── market_analyzer.py
│   │   ├── review_analyst.py
│   │   └── strategy_iterator.py
│   ├── scheduler/          # 24/7 task scheduling
│   │   ├── __init__.py
│   │   ├── daemon.py       # APScheduler daemon
│   │   └── tasks.py        # Task definitions
│   ├── pipeline/           # Strategy iteration engine
│   │   ├── __init__.py
│   │   ├── backtest.py     # Rule-based backtest engine
│   │   └── workflow.py     # Decompose→Distill→Recombine→Iterate
│   ├── reports/            # Report generation
│   │   ├── __init__.py
│   │   ├── templates/      # Jinja2 markdown templates
│   │   └── generator.py    # 15k-word daily review generator
│   └── api/                # FastAPI routes
│       ├── __init__.py
│       └── routes.py
├── web/                    # Frontend (Phase 6)
├── pyproject.toml
└── .python-version
```

## Key Technical Decisions

1. **SQLite** — zero-config, single-user, no server. SQLAlchemy ORM for future migration to PostgreSQL
2. **Custom agent framework** — NOT LangChain. Lightweight base class with LLM client abstraction, tool use, structured JSON output. Too much abstraction in LangChain for this use case
3. **APScheduler** — for task scheduling, not Celery (no Redis/RabbitMQ needed)
4. **Custom backtest engine** — needs tight integration with agent output (structured rules), off-the-shelf frameworks don't fit
5. **LLM abstraction** — supports OpenAI, Anthropic, and local models via Ollama
6. **Typer** — for CLI (rich output, autocompletion)
7. **FastAPI** — for API layer (Phase 5+)

## Implementation Phases

### Phase 1: Data Layer Foundation
**Files:** `server/config.py`, `server/data/models.py`, `server/data/store.py`, `server/data/providers/*`, `server/data/pipeline.py`, `server/cli.py`

- Pydantic Settings config (data sources, DB path, schedule intervals)
- SQLAlchemy models: `market_daily`, `market_minute`, `fund_flow`, `dragon_tiger`, `sector_data`, `trade_records`, `strategy_rules`, `strategy_versions`
- AKShare adapter (primary — covers 95% of data needs)
- Baostock adapter (backtest-calibrated historical data)
- iTick adapter (real-time monitoring)
- ETL pipeline: clean, dedup, cross-validate, normalize
- CLI: `stockit data fetch`, `stockit data status`

**Dependencies:** `akshare`, `baostock`, `sqlalchemy`, `pydantic-settings`, `typer`, `pandas`, `rich`

### Phase 2: AI Agent Core
**Files:** `server/agents/base.py`, `server/agents/prompts/*`, `server/agents/orchestrator.py`, `server/agents/strategy_decomposer.py`, `server/agents/strategy_distiller.py`, `server/agents/market_analyzer.py`, `server/agents/review_analyst.py`, `server/agents/strategy_iterator.py`

- Agent base class: `system_prompt`, `async run(input) → AgentOutput`, LLM client, tool binding, JSON schema validation
- 5 specialized agents with prompt templates
- Orchestrator: sequential pipelines + parallel execution
- Database tables: `agent_run_logs`, `strategy_rules`, `strategy_versions`

**Dependencies:** `openai`, `httpx`, `pydantic`

### Phase 3: Scheduler
**Files:** `server/scheduler/daemon.py`, `server/scheduler/tasks.py`

- Task definitions: real-time monitoring (market hours), daily review (closing bell), nightly iteration (overnight)
- APScheduler daemon with cron-style triggers
- A-share trading hours detection (9:30-15:00 CST)
- CLI: `stockit scheduler start|stop|status`

**Dependencies:** `apscheduler`

### Phase 4: Strategy Iteration Pipeline
**Files:** `server/pipeline/backtest.py`, `server/pipeline/workflow.py`

- Rule-based backtest engine (signals, position sizing, risk rules)
- Parameter sweep / walk-forward testing
- Performance metrics: Sharpe, max drawdown, win rate, profit factor
- 4-step iteration workflow orchestration
- Version management (V1→V2→V3) with changelogs
- Overfitting detection via out-of-sample validation

**Dependencies:** `numpy`, `pandas`

### Phase 5: Report Generation
**Files:** `server/reports/templates/*`, `server/reports/generator.py`, `server/api/routes.py`

- 6-section Jinja2 markdown templates (market, sector, fund flow, watchlist, trade review, strategy optimization)
- Report generator: aggregate data + agent outputs → rendered markdown
- Archive to `~/.stockit/reports/YYYY-MM-DD/`
- FastAPI endpoints: `GET /api/reports`, `GET /api/strategies`, `GET /api/market-status`

**Dependencies:** `jinja2`, `fastapi`, `uvicorn`

### Phase 6: Web UI (optional, later)
**Files:** `web/` (Vue 3 SPA)

- Dashboard: market overview, agent status, report viewer, strategy history
- Chart.js or ECharts for visualization

## Verification

1. **Phase 1:** `stockit data fetch` pulls real data from AKShare, stores in SQLite, `stockit data status` shows table counts
2. **Phase 2:** Each agent can be invoked independently via CLI, returns validated JSON output
3. **Phase 3:** `stockit scheduler start` runs daemon, logs show tasks firing at correct times
4. **Phase 4:** Run a known strategy (e.g., MA crossover) through backtest, verify metrics match reference
5. **Phase 5:** Generate a full daily report, verify it's ~15k words with all 6 sections
6. **Phase 6:** `npm run dev` in web/, dashboard loads and shows data from API