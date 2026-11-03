"""FastAPI backend for the research / paper-trading dashboard.

All payloads carry provenance: data source, as-of timestamps and a data class
(HISTORICAL | DELAYED | SIMULATED | HISTORICAL-REPLAY | LIVE). Simulated P&L is never labelled as earnings.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from qrs.config import PAPER_DIR, PROC_DIR, REPORT_DIR, ROOT
from qrs.paper.engine import LIVE_TRADING_ENABLED

RES = REPORT_DIR / "results"
app = FastAPI(title="QRS - Quant Research System", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    return o


def _read_json(p: Path):
    if not p.exists():
        raise HTTPException(404, f"{p.name} not found - run the research pipeline first")
    return json.loads(p.read_text())


def _weekly(s: pd.Series) -> list[dict]:
    s = s.dropna()
    if len(s) > 1500:
        s = s.resample("W-FRI").last().dropna()
    return [{"t": d.strftime("%Y-%m-%d"), "v": float(v)} for d, v in s.items()]


# --------------------------------------------------------------------------------------- status
@app.get("/api/status")
def status():
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text()) if (ROOT / "data" / "manifest.json").exists() else {}
    fresh = {}
    for key, v in manifest.items():
        src = key.split("/")[0]
        e = fresh.setdefault(src, {"series": 0, "latest": None, "earliest": None})
        e["series"] += 1
        end = (v.get("end") or "")[:10] or None
        st = (v.get("start") or "")[:10] or None
        if end and (e["latest"] is None or end > e["latest"]):
            e["latest"] = end
        if st and (e["earliest"] is None or st < e["earliest"]):
            e["earliest"] = st
    labels = {"binance": "Binance public archive (data.binance.vision) - HISTORICAL, daily, UTC",
              "yahoo_mirror": "Yahoo Finance daily via GitHub mirror o-lq/run - HISTORICAL/DELAYED end-of-day",
              "github_datasets": "EIA / Fed H.10 / CBOE / BLS / Shiller via datasets/* - HISTORICAL reference"}
    meta = json.loads((REPORT_DIR / "leaderboard_meta.json").read_text()) if (REPORT_DIR / "leaderboard_meta.json").exists() else {}
    paper = []
    for f in sorted(PAPER_DIR.glob("*.sqlite")):
        paper.append({"run": f.stem, "updated_utc": datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")})
    return _clean({"server_time_utc": _now(), "live_trading_enabled": LIVE_TRADING_ENABLED,
                   "real_money": "DISABLED - simulation only; no broker credentials configured",
                   "kill_switch": (PAPER_DIR / "KILL").exists(),
                   "data_sources": {k: {**v, "description": labels.get(k, k)} for k, v in fresh.items()},
                   "holdout_unlocked": meta.get("holdout_unlocked"), "paper_runs": paper,
                   "network_note": "Live exchange/broker APIs are blocked in the research sandbox; feeds are archive/mirror based."})


@app.post("/api/kill")
def kill_on():
    (PAPER_DIR / "KILL").write_text(_now())
    return {"kill_switch": True}


@app.delete("/api/kill")
def kill_off():
    (PAPER_DIR / "KILL").unlink(missing_ok=True)
    return {"kill_switch": False, "note": "risk manager still requires manual reset of HALTED runs"}


# ------------------------------------------------------------------------------------ research
@app.get("/api/leaderboard")
def leaderboard():
    p = REPORT_DIR / "leaderboard.csv"
    if not p.exists():
        raise HTTPException(404, "leaderboard missing")
    df = pd.read_csv(p)
    meta = json.loads((REPORT_DIR / "leaderboard_meta.json").read_text())
    return _clean({"rows": df.replace({np.nan: None}).to_dict("records"), "meta": meta,
                   "data_class": "SIMULATED (backtest on historical data, net of modelled costs)"})


@app.get("/api/experiments/{name}")
def experiment(name: str):
    return _clean(_read_json(RES / f"{name}.json"))


@app.get("/api/experiments/{name}/series")
def experiment_series(name: str):
    p = RES / f"{name}_returns.parquet"
    if not p.exists():
        raise HTTPException(404, "series missing")
    r = pd.read_parquet(p)
    eq = (1 + r["net"]).cumprod()
    dd = eq / eq.cummax() - 1
    gross_eq = (1 + r["gross"]).cumprod()
    s = json.loads((RES / f"{name}.json").read_text())
    bench = {}
    from qrs.research.runner import benchmark_returns
    kind = "etf" if s["market"] == "etf" else "crypto"
    try:
        b = benchmark_returns(kind, str(r.index[0].date()), str(r.index[-1].date()))
        key = "SPY_buy_hold" if kind == "etf" else "BTC_buy_hold"
        bench = {key: _weekly((1 + b[key]).cumprod())}
    except Exception:  # noqa: BLE001
        pass
    return {"equity": _weekly(eq), "gross_equity": _weekly(gross_eq), "drawdown": _weekly(dd),
            "cum_costs": _weekly(r["cost"].cumsum()), "exposure": _weekly(r["gross_exp"]), "benchmarks": bench,
            "holdout_start": s.get("holdout", {}).get("start"), "data_class": "SIMULATED"}


@app.get("/api/signals")
def signals():
    """Latest research target weights per strategy (as of the last historical bar)."""
    out = []
    for f in sorted(RES.glob("*_target.json")):
        name = f.stem.replace("_target", "")
        try:
            s = json.loads((RES / f"{name}.json").read_text())
        except FileNotFoundError:
            continue
        w = json.loads(f.read_text())["target_weight"]
        r = pd.read_parquet(RES / f"{name}_returns.parquet")
        pos = {k: v for k, v in w.items() if v is not None and abs(v) > 1e-4}
        out.append({"strategy": name, "market": s["market"], "gate": "PASS" if s.get("gate_pass") else "FAIL",
                    "as_of": str(r.index[-1].date()),
                    "state": "NO_TRADE" if not pos else ("LONG/SHORT" if any(v < 0 for v in pos.values()) else "LONG"),
                    "weights": pos})
    return _clean({"signals": out, "data_class": "HISTORICAL (research signal on last available bar; not a live order)"})


@app.get("/api/markets")
def markets():
    lb = pd.read_csv(REPORT_DIR / "leaderboard.csv")
    g = lb.groupby(["market", "family"]).agg(n=("experiment", "count"), best_wf_sharpe=("wf_sharpe", "max"),
                                             median_wf_sharpe=("wf_sharpe", "median"),
                                             passed=("gate", lambda x: int((x == "PASS").sum()))).reset_index()
    return _clean({"rows": g.replace({np.nan: None}).to_dict("records")})


@app.get("/api/data-quality")
def data_quality():
    return _clean(_read_json(PROC_DIR / "data_quality.json"))


@app.get("/api/portfolio")
def portfolio():
    return _clean(_read_json(REPORT_DIR / "portfolio.json"))


@app.get("/api/capital")
def capital():
    return _clean(_read_json(REPORT_DIR / "capital.json"))


# --------------------------------------------------------------------------------------- paper
def _journal(run: str):
    from qrs.paper.journal import Journal
    p = PAPER_DIR / f"{run}.sqlite"
    if not p.exists():
        raise HTTPException(404, "paper run not found")
    return Journal(p)


@app.get("/api/paper/{run}")
def paper(run: str):
    J = _journal(run)
    eq = J.query("SELECT ts, equity, cash, gross, net, realized, unrealized, costs FROM equity WHERE run_id=? ORDER BY ts", (run,))
    last_ts = eq[-1]["ts"] if eq else None
    pos = J.query("SELECT symbol, qty, avg_price, mark FROM positions WHERE run_id=? AND ts=?", (run, last_ts)) if last_ts else []
    sig = J.query("SELECT ts, symbol, proposed, approved, action FROM signals WHERE run_id=? ORDER BY ts DESC LIMIT 60", (run,))
    fills = J.query("SELECT ts, symbol, qty, price, ref_price, cost FROM fills WHERE run_id=? ORDER BY ts DESC LIMIT 100", (run,))
    ev = J.query("SELECT utc, level, code, message FROM events WHERE run_id=? ORDER BY rowid DESC LIMIT 100", (run,))
    bars = J.query("SELECT source, data_class, MAX(ts) AS last_bar, MAX(received_utc) AS received FROM bars WHERE run_id=? GROUP BY source, data_class", (run,))
    run_meta = J.query("SELECT * FROM runs WHERE run_id=?", (run,))
    cmp_p = REPORT_DIR / f"paper_vs_backtest_{run}.json"
    return _clean({"equity": eq[::max(1, len(eq) // 800)] + eq[-1:], "positions": pos, "signals": sig, "fills": fills,
                   "events": ev, "feeds": bars, "run": run_meta[0] if run_meta else None,
                   "vs_backtest": json.loads(cmp_p.read_text()) if cmp_p.exists() else None,
                   "data_class": "SIMULATED paper account (no real money)"})


# ------------------------------------------------------------------------------------- static UI
_dist = ROOT / "dashboard" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(_dist / "index.html")
