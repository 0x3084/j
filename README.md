# QRS — Quantitative Research System

A research-first platform for discovering, validating and paper-trading systematic strategies on **real** market data.
It covers data ingestion and validation, a realistic backtest engine, walk-forward research with multiple-testing
control, portfolio and capital simulation, a risk-gated paper-trading engine, a FastAPI backend and a React dashboard.

> **Headline finding:** of 28 strategy/market combinations (200 trials), two ETF regime-timing rules passed the
> pre-registered gate, and both decayed to roughly cash-like returns in the untouched 2022–2026 holdout. No strategy
> beat a passive 60/40 portfolio. Read **[reports/RESEARCH_REPORT.md](reports/RESEARCH_REPORT.md)** before anything else.

Real-money trading is **disabled** and not implemented. No broker credentials are used.

## Layout

```
configs/      universe.yaml (instruments, costs) · research.yaml (pre-registered protocol & gate)
              experiments.yaml (strategy grids) · risk.yaml (mandatory risk limits)
qrs/data/     sources (Binance archive, Yahoo mirror, EIA/FRED/CBOE) · validation · Parquet/DuckDB store
qrs/backtest/ engine (next-open execution, costs, funding, borrow, delistings) · metrics · stats (bootstrap, DSR, SPA)
qrs/strategies/ trend · meanrev · momentum · statarb · vol (incl. crypto funding carry) · ml (purged walk-forward)
qrs/research/ market contexts (point-in-time universes) · runner (walk-forward, stress, gate) · run_all (leaderboard)
qrs/portfolio/ multi-strategy allocation · capital levels & withdrawal simulation
qrs/risk/     independent risk manager (caps, daily loss, drawdown halt, stale data, kill switch, signed approvals)
qrs/paper/    feeds (replay / Binance REST) · simulated broker · SQLite journal · crash recovery · backtest comparison
qrs/api/      FastAPI backend (serves dashboard/dist)
dashboard/    React + TypeScript + Recharts dashboard
reports/      research report, leaderboard, per-strategy JSON/Parquet results, data-quality report, trial ledger
tests/        engine accounting, stats, validation, look-ahead truncation tests, risk & paper engine
```

## Setup

```bash
pip install -e .[dev] exchange_calendars
python -m scripts.ingest                     # real data -> data/processed (+ reports/data_quality.md)
python -m qrs.research.run_all               # research phase (holdout masked)
python -m qrs.research.run_all --holdout     # one-time holdout evaluation
python -m scripts.portfolio_capital
python -m scripts.paper replay --strategy vix_regime_spy --start 2025-11-03 --fresh
pytest -q
cd dashboard && npm install && npm run build && cd ..
uvicorn qrs.api.app:app --port 8000          # dashboard at http://localhost:8000
```

Docker: `docker compose up --build`. The image ingests data on first start if `data/processed` is empty.

## Design choices

- **Parquet + DuckDB** for immutable, columnar research data. The raw downloads are checksummed in `data/manifest.json`.
- **pandas/NumPy** for the research panels and **Polars** for ingestion and validation. The day loop in the engine is NumPy-vectorised across assets.
  It is the reference implementation, and two independent simulators reconcile against it: an integer-share simulator and the paper broker.
- **SQLite (WAL)** for the paper journal: a single writer, zero ops and crash-safe. The schema is plain SQL and portable to PostgreSQL.
- **Holdout lock:** the research runner truncates every backtest before the holdout unless `--holdout` is passed. Each unlock is
  logged with its git commit in `reports/trial_ledger.csv`. The strategy set was frozen at tag `frozen-pre-holdout`.

## Data sources and limitations

This research sandbox blocks most market-data APIs. The data comes from the official Binance public archive (SHA-256 verified),
a GitHub mirror of Yahoo Finance daily adjusted bars (cross-checked against Shiller, Fed H.10 and EIA), and `datasets/*`
repositories (EIA, Fed H.10, CBOE VIX, BLS CPI).

Not available, and not substituted:
- contract-level futures
- intraday and order-book data
- point-in-time single-stock data with delistings
- UCITS ETF histories

See the report, §9.
