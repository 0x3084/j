"""Market-data feeds for paper trading. Every bar carries its source and a data class so the UI can
show whether information is LIVE, DELAYED, HISTORICAL-REPLAY or SIMULATED.

* ``BinanceRESTFeed``   live daily/hourly klines from api.binance.com (public, no credentials).
                        NOTE: blocked by this sandbox's egress policy; works on a normal network.
* ``YahooMirrorFeed``   daily ETF bars from the GitHub Yahoo mirror (end-of-day, DELAYED).
* ``ReplayFeed``        replays the validated historical Parquet store bar by bar, exactly as a live
                        feed would deliver them (used for end-to-end tests and dry runs).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

import pandas as pd


@dataclass
class Bar:
    ts: pd.Timestamp           # bar open time (UTC date for daily bars)
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str
    data_class: str            # LIVE | DELAYED | HISTORICAL-REPLAY
    received_utc: str


class Feed:
    def history(self) -> dict[str, pd.DataFrame]:
        raise NotImplementedError

    def bars(self) -> Iterator[list[Bar]]:
        raise NotImplementedError


class ReplayFeed(Feed):
    """Replays a slice of the processed store. history() returns data strictly before `start`."""

    def __init__(self, panels: dict[str, pd.DataFrame], start: str, end: str | None = None, source: str = "replay"):
        self.p = panels
        self.start, self.end = pd.Timestamp(start), pd.Timestamp(end) if end else None
        self.source = source

    def history(self) -> dict[str, pd.DataFrame]:
        return {k: v.loc[v.index < self.start] for k, v in self.p.items()}

    def bars(self) -> Iterator[list[Bar]]:
        c = self.p["close"]
        idx = c.index[(c.index >= self.start) & ((c.index <= self.end) if self.end is not None else True)]
        for t in idx:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            out = []
            for s in c.columns:
                cl = c.at[t, s]
                if pd.notna(cl):
                    out.append(Bar(t, s, float(self.p["open"].at[t, s]), float(self.p["high"].at[t, s]),
                                   float(self.p["low"].at[t, s]), float(cl), float(self.p["volume"].at[t, s] or 0),
                                   self.source, "HISTORICAL-REPLAY", now))
            yield out


class BinanceRESTFeed(Feed):  # pragma: no cover - requires network access to api.binance.com
    URL = "https://api.binance.com/api/v3/klines"

    def __init__(self, symbols: list[str], interval: str = "1d", lookback: int = 400):
        self.symbols, self.interval, self.lookback = symbols, interval, lookback

    def _klines(self, sym: str, limit: int) -> pd.DataFrame:
        import httpx
        r = httpx.get(self.URL, params={"symbol": sym, "interval": self.interval, "limit": limit}, timeout=20)
        r.raise_for_status()
        df = pd.DataFrame(r.json()).iloc[:, :6]
        df.columns = ["ts", "open", "high", "low", "close", "volume"]
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        return df.set_index("ts").astype(float)

    def history(self) -> dict[str, pd.DataFrame]:
        frames = {s: self._klines(s, self.lookback).iloc[:-1] for s in self.symbols}   # drop forming bar
        return {f: pd.DataFrame({s: d[f] for s, d in frames.items()}) for f in ("open", "high", "low", "close", "volume")}

    def bars(self) -> Iterator[list[Bar]]:
        import time
        last = None
        while True:
            frames = {s: self._klines(s, 3) for s in self.symbols}
            done_ts = max(d.index[-2] for d in frames.values())
            if last is None or done_ts > last:
                now = datetime.now(timezone.utc).isoformat(timespec="seconds")
                yield [Bar(done_ts, s, *d.loc[done_ts, ["open", "high", "low", "close", "volume"]].tolist(),
                           "binance-rest", "LIVE", now) for s, d in frames.items() if done_ts in d.index]
                last = done_ts
            time.sleep(60)
