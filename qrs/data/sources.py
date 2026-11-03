"""Real market-data sources reachable from this environment.

Every download is cached under data/raw/, hashed (SHA-256) and recorded in data/manifest.json so that
experiments can be reproduced and silent upstream changes detected.  No synthetic data is generated
anywhere in this module.

Sources
-------
* ``binance_public``  Official Binance public-data archive (data.binance.vision, served from S3).
  Spot klines, USDT-M perpetual klines and funding-rate history.  Each zip ships with a .CHECKSUM
  file which we verify.
* ``yahoo_mirror``    Yahoo Finance daily bars (yfinance, auto-adjusted for splits and dividends,
  i.e. a total-return price series) mirrored on GitHub by ``o-lq/run``.  Yahoo itself is blocked by
  this sandbox's egress policy; the mirror is a third party, so we cross-validate it against
  independent sources (EIA / LBMA-derived series) in ``qrs.data.validate``.
* ``github_datasets`` ``datasets/*`` repositories (EIA oil and gas spot, Fed H.10 FX, CBOE VIX,
  BLS CPI, Shiller S&P 500) – used as reference / feature data, never traded directly.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import httpx
import polars as pl

from qrs.config import DATA_DIR, RAW_DIR

BINANCE_S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
YAHOO_MIRROR = "https://raw.githubusercontent.com/o-lq/run/main/data/us/1d/{snapshot}/{symbol}.csv"
YAHOO_SNAPSHOT = "2026-10-31"
GITHUB_RAW = "https://raw.githubusercontent.com/{repo}/main/{path}"
MANIFEST = DATA_DIR / "manifest.json"

_lock = threading.Lock()
_client = httpx.Client(timeout=60.0, follow_redirects=True, headers={"User-Agent": "qrs-research/0.1"})


# --------------------------------------------------------------------------------------------- utils
def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _get(url: str, retries: int = 4) -> httpx.Response:
    delay = 2.0
    for i in range(retries + 1):
        try:
            r = _client.get(url)
            if r.status_code in (200, 404):
                return r
            if r.status_code == 403 and "amazonaws" not in url:
                return r
        except httpx.HTTPError:
            if i == retries:
                raise
        time.sleep(delay)
        delay *= 2
    return r


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {}


def _record(key: str, **info) -> None:
    with _lock:
        m = load_manifest()
        m[key] = {**m.get(key, {}), **info, "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        MANIFEST.write_text(json.dumps(m, indent=1, sort_keys=True))


def _cached_fetch(url: str, dest: Path, force: bool = False) -> bytes | None:
    if dest.exists() and not force:
        return dest.read_bytes()
    r = _get(url)
    if r.status_code != 200:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return r.content


# ------------------------------------------------------------------------------------ binance public
def binance_list(prefix: str) -> list[str]:
    """List object keys under a prefix in the public Binance bucket (handles pagination)."""
    keys, marker = [], ""
    while True:
        url = f"{BINANCE_S3}?prefix={prefix}&marker={marker}"
        txt = _get(url).text
        found = re.findall(r"<Key>([^<]+)</Key>", txt)
        keys += found
        if "<IsTruncated>true</IsTruncated>" not in txt or not found:
            break
        marker = found[-1]
    return keys


def _binance_zip_to_df(content: bytes, kind: str) -> pl.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = z.read(z.namelist()[0])
    first = raw.split(b"\n", 1)[0]
    has_header = not first[:1].isdigit()
    if kind == "klines":
        cols = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume",
                "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
        df = pl.read_csv(io.BytesIO(raw), has_header=has_header, new_columns=cols, infer_schema_length=0)
        df = df.select(cols[:11]).with_columns(pl.all().cast(pl.Float64))
    else:  # funding
        df = pl.read_csv(io.BytesIO(raw), has_header=has_header, infer_schema_length=0)
        df.columns = ["calc_time", "funding_interval_hours", "funding_rate"][: len(df.columns)]
        df = df.with_columns(pl.all().cast(pl.Float64))
    return df


def _ms(col: str) -> pl.Expr:
    # Binance switched spot timestamps from milliseconds to microseconds on 2025-01-01.
    c = pl.col(col)
    return pl.when(c > 1e14).then(c / 1000).otherwise(c).cast(pl.Int64)


def fetch_binance(symbol: str, market: str = "spot", kind: str = "klines", interval: str = "1d",
                  workers: int = 12) -> pl.DataFrame:
    """Download every monthly archive for symbol and return a tidy frame.

    market: 'spot' or 'um' (USDT-M futures); kind: 'klines' or 'fundingRate'.
    """
    if market == "spot":
        prefix = f"data/spot/monthly/klines/{symbol}/{interval}/"
    elif kind == "klines":
        prefix = f"data/futures/um/monthly/klines/{symbol}/{interval}/"
    else:
        prefix = f"data/futures/um/monthly/fundingRate/{symbol}/"
    keys = [k for k in binance_list(prefix) if k.endswith(".zip")]
    if not keys:
        return pl.DataFrame()
    bad: list[str] = []

    def one(key: str) -> pl.DataFrame | None:
        dest = RAW_DIR / "binance" / key
        content = _cached_fetch(f"{BINANCE_S3}/{key}", dest)
        if content is None:
            return None
        ck = dest.with_suffix(".zip.CHECKSUM")
        csum = _cached_fetch(f"{BINANCE_S3}/{key}.CHECKSUM", ck)
        if csum is not None and csum.split()[0].decode() != _sha256(content):
            bad.append(key)
            dest.unlink(missing_ok=True)
            return None
        return _binance_zip_to_df(content, "klines" if kind == "klines" else "funding")

    with ThreadPoolExecutor(workers) as ex:
        parts = [p for p in ex.map(one, keys) if p is not None and p.height]
    df = pl.concat(parts, how="vertical_relaxed")
    if kind == "klines":
        df = (df.with_columns(_ms("open_time").alias("open_time"))
                .with_columns(pl.from_epoch("open_time", time_unit="ms").alias("ts"))
                .drop(["open_time", "close_time"]))
    else:
        df = (df.with_columns(_ms("calc_time").alias("calc_time"))
                .with_columns(pl.from_epoch("calc_time", time_unit="ms").alias("ts")).drop("calc_time"))
    df = df.with_columns(pl.lit(symbol).alias("symbol")).sort("ts")
    _record(f"binance/{market}/{kind}/{interval if kind == 'klines' else ''}/{symbol}",
            source="binance_public", url_prefix=f"{BINANCE_S3}/{prefix}", files=len(keys),
            checksum_failures=bad, rows=df.height, start=str(df["ts"].min()), end=str(df["ts"].max()))
    return df


# ------------------------------------------------------------------------------------- yahoo mirror
def fetch_yahoo_mirror(symbol: str, snapshot: str = YAHOO_SNAPSHOT) -> pl.DataFrame:
    url = YAHOO_MIRROR.format(snapshot=snapshot, symbol=symbol)
    dest = RAW_DIR / "yahoo_mirror" / snapshot / f"{symbol}.csv"
    content = _cached_fetch(url, dest)
    if content is None:
        raise FileNotFoundError(f"{symbol} not available in mirror snapshot {snapshot}")
    df = pl.read_csv(io.BytesIO(content.lstrip(b"\xef\xbb\xbf")), infer_schema_length=0)
    df = df.rename({c: c.strip().lower().replace(" ", "_") for c in df.columns})
    num = [c for c in df.columns if c != "date"]
    # yfinance writes the exchange-local midnight with UTC offset; the calendar date is the session.
    df = (df.with_columns(pl.col("date").str.slice(0, 10).str.to_date().alias("date"),
                          *[pl.col(c).cast(pl.Float64) for c in num])
            .with_columns(pl.lit(symbol).alias("symbol")).sort("date"))
    _record(f"yahoo_mirror/{symbol}", source="yahoo_mirror", url=url, sha256=_sha256(content),
            rows=df.height, start=str(df["date"].min()), end=str(df["date"].max()),
            note="yfinance auto_adjust=True (split+dividend adjusted OHLC)")
    return df


# ---------------------------------------------------------------------------------- github datasets
def fetch_github_dataset(name: str, repo: str, path: str) -> pl.DataFrame:
    url = GITHUB_RAW.format(repo=repo, path=path)
    dest = RAW_DIR / "github_datasets" / repo.replace("/", "__") / Path(path).name
    content = _cached_fetch(url, dest)
    if content is None:
        raise FileNotFoundError(url)
    df = pl.read_csv(io.BytesIO(content), infer_schema_length=10000, try_parse_dates=True)
    _record(f"github_datasets/{name}", source="github_datasets", url=url, sha256=_sha256(content), rows=df.height)
    return df
