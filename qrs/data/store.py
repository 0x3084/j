"""Ingestion into Parquet + loaders for research.

Architecture: raw downloads (immutable, checksummed) -> validated, tidy long-format Parquet files in
data/processed -> wide pandas frames for research.  DuckDB can query the Parquet files directly
(``qrs.data.store.duck()``) for ad-hoc analysis and for the API.
"""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache

import numpy as np
import pandas as pd
import polars as pl

from qrs.config import PROC_DIR, REPORT_DIR, crypto_specs, etf_specs, universe
from qrs.data import sources
from qrs.data.validate import cross_check, validate_bars

QUALITY_FILE = PROC_DIR / "data_quality.json"


def nyse_sessions(start: str, end: str) -> list[date]:
    import exchange_calendars as xc
    cal = xc.get_calendar("XNYS", start="1990-01-01")
    return [d.date() for d in cal.sessions_in_range(start, end)]


# -------------------------------------------------------------------------------------- ingestion
def ingest_etfs() -> dict:
    frames, reports = [], {}
    sessions = nyse_sessions("1993-01-01", sources.YAHOO_SNAPSHOT)
    for sym in etf_specs():
        df = sources.fetch_yahoo_mirror(sym)
        keep = [c for c in ("date", "open", "high", "low", "close", "volume", "dividends", "stock_splits", "symbol")
                if c in df.columns]
        df = df.select(keep)
        rep, df = validate_bars(df, sym, "date", sessions)
        reports[sym] = rep.as_dict()
        frames.append(df)
    out = pl.concat(frames, how="diagonal_relaxed")
    # A reverting spike is only treated as a data error if it is idiosyncratic. If >= 3 series spike on
    # the same session it is a genuine market event (e.g. 2020-03-12) and the bars stay valid.
    common = (out.filter(pl.col("spike")).group_by("date").len().filter(pl.col("len") >= 3)["date"])
    out = out.with_columns((~pl.col("hard_invalid") & ~(pl.col("spike") & ~pl.col("date").is_in(common.implode())))
                           .alias("valid"))
    for sym in reports:
        sub = out.filter(pl.col("symbol") == sym)
        reports[sym]["flagged_rows"] = int((~sub["valid"]).sum())
        reports[sym]["outlier_examples"] = [str(d) for d in sub.filter(~pl.col("valid"))["date"].to_list()[:10]]
        reports[sym]["outliers"] = len(reports[sym]["outlier_examples"])
    out.write_parquet(PROC_DIR / "etf_daily.parquet")
    return reports


def _daily_from_klines(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(pl.col("ts").dt.date().alias("date")).select(
        "date", "symbol", "open", "high", "low", "close", "volume", "quote_volume", "trades")


def _crypto_validity(d: pl.DataFrame) -> pl.DataFrame:
    # Binance's own archive is the primary record of trades that actually happened on the venue, and
    # crypto crashes (LUNA, FTT) are genuine: spikes are reported but only hard errors invalidate a bar.
    return d.with_columns((~pl.col("hard_invalid")).alias("valid"))


def ingest_crypto() -> dict:
    spec = crypto_specs()
    reports = {}
    spot, perp, fund = [], [], []
    for sym in spec["instruments"]:
        df = sources.fetch_binance(sym, "spot", "klines", "1d")
        if df.height == 0:
            reports[f"spot:{sym}"] = {"missing": True}
            continue
        d = _daily_from_klines(df)
        days = pl.date_range(d["date"].min(), d["date"].max(), "1d", eager=True).to_list()
        rep, d = validate_bars(d, sym, "date", days)
        reports[f"spot:{sym}"] = rep.as_dict()
        spot.append(_crypto_validity(d))
    for sym in spec["perps"]:
        df = sources.fetch_binance(sym, "um", "klines", "1d")
        if df.height:
            d = _daily_from_klines(df)
            days = pl.date_range(d["date"].min(), d["date"].max(), "1d", eager=True).to_list()
            rep, d = validate_bars(d, sym, "date", days)
            reports[f"perp:{sym}"] = rep.as_dict()
            perp.append(_crypto_validity(d))
        f = sources.fetch_binance(sym, "um", "fundingRate")
        if f.height:
            fund.append(f.select("ts", "symbol", "funding_rate"))
    pl.concat(spot, how="diagonal_relaxed").write_parquet(PROC_DIR / "crypto_spot_daily.parquet")
    pl.concat(perp, how="diagonal_relaxed").write_parquet(PROC_DIR / "crypto_perp_daily.parquet")
    pl.concat(fund, how="diagonal_relaxed").write_parquet(PROC_DIR / "crypto_funding.parquet")
    return reports


def ingest_reference() -> dict:
    ref = universe()["reference"]["series"]
    info = {}
    for name, s in ref.items():
        df = sources.fetch_github_dataset(name, s["repo"], s["path"])
        df.write_parquet(PROC_DIR / f"ref_{name}.parquet")
        info[name] = {"rows": df.height, "columns": df.columns, "origin": s["origin"]}
    return info


def run_cross_checks() -> dict:
    """Validate the third-party Yahoo mirror against independent official series."""
    out = {}
    px = load_wide("etf", "close")
    r = np.log(px).diff()
    wti = pl.read_parquet(PROC_DIR / "ref_wti_spot.parquet").to_pandas()
    wti = wti.set_index(wti.columns[0])[wti.columns[1]].astype(float)
    wti.index = pd.to_datetime(wti.index)
    wti = wti[wti > 0]
    # USO holds front-month WTI futures: daily correlation with EIA spot should be high but not 1.
    rr = np.log(wti).diff().reindex(r.index)
    out["USO_vs_EIA_WTI_spot"] = cross_check(r["USO"].values, rr.values)
    # FXE vs Fed H.10 EUR/USD noon-buying rate
    fx = pl.read_parquet(PROC_DIR / "ref_fx_h10.parquet").to_pandas()
    fx.columns = [c.lower() for c in fx.columns]
    eur = fx[fx["country"].str.contains("Euro")].set_index("date")["exchange rate"].astype(float)
    eur.index = pd.to_datetime(eur.index)
    eur = eur[eur > 0]
    # H.10 quotes USD per EUR inverse for some series: detect by level
    if eur.median() < 1.0:
        eur = 1 / eur
    re_ = np.log(eur).diff().reindex(r.index)
    out["FXE_vs_H10_EURUSD"] = cross_check(r["FXE"].values, re_.values)
    # SPY total-return vs Shiller monthly S&P 500 price (monthly averages, so only a coarse check)
    sh = pl.read_parquet(PROC_DIR / "ref_shiller_sp500.parquet").to_pandas()
    sh = sh.set_index(pd.to_datetime(sh["Date"]))["SP500"].astype(float)
    sh = sh[sh > 0]
    spy_m = px["SPY"].resample("MS").mean()
    a = np.log(spy_m).diff()
    b = np.log(sh).diff().reindex(a.index)
    out["SPY_monthly_vs_Shiller"] = cross_check(a.values, b.values, periods=12)
    return out


def ingest_all() -> dict:
    q = {"etf": ingest_etfs(), "crypto": ingest_crypto(), "reference": ingest_reference()}
    load_wide.cache_clear()
    q["cross_checks"] = run_cross_checks()
    QUALITY_FILE.write_text(json.dumps(q, indent=1, default=str))
    write_quality_report(q)
    return q


def write_quality_report(q: dict) -> None:
    lines = ["# Data quality report", "", "Generated by `python -m scripts.ingest`. All series are real market data; "
             "nothing is synthesised or silently filled.", "",
             "ETF: flagged rows (OHLC inconsistency, non-positive prices, idiosyncratic reverting spikes not shared by >=3 other series) are marked non-tradable "
             "in backtests; they are not altered. Crypto: spikes are reported only (venue is the primary record; crashes like LUNA/FTT are real).", ""]
    for section in ("etf", "crypto"):
        lines += [f"## {section.upper()}", "",
                  "| series | rows | start | end | dup | missing sessions | OHLC bad | stale runs | spikes | >25% moves | flagged |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for k, r in q[section].items():
            if r.get("missing"):
                lines.append(f"| {k} | not available in archive | | | | | | | | | |")
                continue
            lines.append(f"| {k} | {r['rows']} | {r['start'][:10]} | {r['end'][:10]} | {r['duplicates']} | "
                         f"{r['missing_sessions']} | {r['ohlc_inconsistent']} | {r['stale_runs']} | {r['outliers']} | "
                         f"{r['large_moves']} | {r['flagged_rows']} |")
        lines.append("")
    lines += ["## Cross-source checks (third-party Yahoo mirror vs official series)", "",
              "| check | n | corr | mean abs diff (bps) | ann. drift diff |", "|---|---|---|---|---|"]
    for k, r in q.get("cross_checks", {}).items():
        lines.append(f"| {k} | {r.get('n')} | {r.get('corr', float('nan')):.3f} | "
                     f"{r.get('mean_abs_diff_bps', float('nan')):.1f} | {r.get('ann_return_diff', float('nan')):+.3f} |")
    lines += ["", "Notes: USO tracks front-month futures, not spot, so drift differs by roll yield (contango); "
              "H.10 is a noon NY fixing vs FXE's 4pm close, so daily correlation < 1 is expected; Shiller data are "
              "monthly *averages* of the price index (no dividends) vs SPY total return.", ""]
    (REPORT_DIR / "data_quality.md").write_text("\n".join(lines))


# ---------------------------------------------------------------------------------------- loaders
_FILES = {"etf": "etf_daily.parquet", "spot": "crypto_spot_daily.parquet", "perp": "crypto_perp_daily.parquet"}


@lru_cache(maxsize=64)
def _long(dataset: str) -> pd.DataFrame:
    df = pl.read_parquet(PROC_DIR / _FILES[dataset]).to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    return df


@lru_cache(maxsize=128)
def load_wide(dataset: str, field: str) -> pd.DataFrame:
    """Wide date x symbol frame. Invalid bars are set to NaN (non-tradable)."""
    df = _long(dataset)
    if field != "valid" and "valid" in df.columns:
        df = df.assign(**{field: df[field].where(df["valid"])})
    w = df.pivot_table(index="date", columns="symbol", values=field, aggfunc="last").sort_index()
    return w


@lru_cache(maxsize=4)
def load_funding_daily() -> pd.DataFrame:
    """Sum of funding rates paid per UTC day (positive = longs pay shorts)."""
    f = pl.read_parquet(PROC_DIR / "crypto_funding.parquet").to_pandas()
    f["date"] = pd.to_datetime(f["ts"]).dt.normalize()
    return f.pivot_table(index="date", columns="symbol", values="funding_rate", aggfunc="sum").sort_index()


def load_vix() -> pd.Series:
    v = pl.read_parquet(PROC_DIR / "ref_vix.parquet").to_pandas()
    v.columns = [c.lower() for c in v.columns]
    s = v.set_index(pd.to_datetime(v["date"]))["close"].astype(float)
    return s.sort_index()


def duck():
    """DuckDB connection with views over the processed Parquet files."""
    import duckdb
    con = duckdb.connect()
    for name, f in _FILES.items():
        p = PROC_DIR / f
        if p.exists():
            con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{p}')")
    return con
