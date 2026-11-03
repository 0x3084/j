"""Paper-trading engine: feed -> validation -> strategy proposal -> RISK APPROVAL -> simulated broker
-> journal / attribution / alerts, with crash recovery from the journal.

REAL-MONEY TRADING IS NOT IMPLEMENTED. ``SimBroker`` is the only broker; there is no code path that
sends orders to an exchange, and no credentials are read anywhere.
"""
from __future__ import annotations

import logging
import math
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from qrs.config import PAPER_DIR
from qrs.paper.feeds import Bar, Feed
from qrs.paper.journal import Journal
from qrs.risk.manager import Approval, RiskLimits, RiskManager, State

log = logging.getLogger("qrs.paper")
LIVE_TRADING_ENABLED = False      # hard-coded. Enabling real money requires separate, explicit authorisation.


@dataclass
class Order:
    order_id: str
    symbol: str
    qty: float
    created: pd.Timestamp


@dataclass
class SimBroker:
    """Fills market orders at the NEXT bar's open, adverse by half-spread + slippage, plus commission
    max(bps * notional, min_fee). Quantities are rounded to the lot step; fills are capped at
    `max_participation` of the bar's volume (remainder cancelled and journaled)."""
    one_way_bps: dict[str, float]              # half-spread + slippage, bps
    commission_bps: dict[str, float]
    min_fee: float = 0.0
    lot_step: float = 1.0
    max_participation: float = 0.05
    risk: RiskManager | None = None
    cash: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)
    avg_price: dict[str, float] = field(default_factory=dict)
    pending: list[Order] = field(default_factory=list)
    realized: float = 0.0
    costs_paid: float = 0.0

    def submit(self, approval: Approval, marks: dict[str, float], equity: float, now: pd.Timestamp) -> list[Order]:
        if self.risk is None or not self.risk.verify(approval):
            raise PermissionError("order set not approved by the risk manager - rejected")
        if LIVE_TRADING_ENABLED:  # pragma: no cover
            raise RuntimeError("live trading is disabled in this build")
        self.pending = []
        for s, w in approval.weights.items():
            px = marks.get(s)
            if not px or not np.isfinite(px):
                continue
            tgt = w * equity / px
            q = math.floor(abs(tgt) / self.lot_step) * self.lot_step * np.sign(tgt)
            d = q - self.positions.get(s, 0.0)
            if abs(d) >= self.lot_step * 0.999:
                self.pending.append(Order(uuid.uuid4().hex[:12], s, float(d), now))
        return self.pending

    def execute(self, bars: dict[str, Bar]) -> list[dict]:
        fills, keep = [], []
        for o in self.pending:
            b = bars.get(o.symbol)
            if b is None or not np.isfinite(b.open):
                keep.append(o)              # no market today: order stays pending
                continue
            cap = self.max_participation * max(b.volume, 0.0)
            qty = float(np.sign(o.qty) * min(abs(o.qty), cap)) if cap > 0 else o.qty
            qty = math.floor(abs(qty) / self.lot_step) * self.lot_step * np.sign(qty)
            if qty == 0:
                continue
            slip = self.one_way_bps.get(o.symbol, 10.0) * 1e-4
            px = b.open * (1 + slip * np.sign(qty))
            notional = abs(qty) * px
            fee = max(self.commission_bps.get(o.symbol, 10.0) * 1e-4 * notional, self.min_fee)
            self.cash -= qty * px + fee
            self.costs_paid += fee + abs(qty) * abs(px - b.open)
            old = self.positions.get(o.symbol, 0.0)
            new = old + qty
            if old != 0 and np.sign(qty) != np.sign(old):           # closing (part of) a position
                closed = min(abs(qty), abs(old)) * np.sign(old)
                self.realized += closed * (px - self.avg_price.get(o.symbol, px))
            if new == 0:
                self.avg_price.pop(o.symbol, None)
            elif old == 0 or np.sign(new) != np.sign(old):
                self.avg_price[o.symbol] = px
            elif np.sign(qty) == np.sign(old):
                self.avg_price[o.symbol] = (self.avg_price[o.symbol] * abs(old) + px * abs(qty)) / abs(new)
            self.positions[o.symbol] = new
            if abs(new) < 1e-12:
                self.positions.pop(o.symbol)
            fills.append({"order_id": o.order_id, "ts": str(b.ts), "symbol": o.symbol, "qty": qty, "price": px,
                          "ref_price": b.open, "cost": fee + abs(qty) * abs(px - b.open)})
        self.pending = keep
        return fills

    def equity(self, marks: dict[str, float]) -> float:
        return self.cash + sum(q * marks.get(s, self.avg_price.get(s, 0.0)) for s, q in self.positions.items())


class PaperTrader:
    def __init__(self, name: str, feed: Feed, strategy_fn, market_builder, capital: float, limits: RiskLimits,
                 broker_kwargs: dict, groups: dict | None = None, journal_path: Path | None = None,
                 alert_fn=None, mode: str = "replay"):
        self.name, self.feed, self.strategy_fn, self.market_builder = name, feed, strategy_fn, market_builder
        self.capital = capital
        self.journal = Journal(journal_path or PAPER_DIR / f"{name}.sqlite")
        self.risk = RiskManager(limits, groups, kill_file=PAPER_DIR / "KILL")
        self.broker = SimBroker(risk=self.risk, cash=capital, **broker_kwargs)
        self.alert = alert_fn or (lambda level, msg: log.warning("[%s] %s", level, msg))
        self.mode = mode
        self.run_id = name
        self.hist = {k: v.copy() for k, v in feed.history().items()}
        self.last_seen: dict[str, pd.Timestamp] = {}
        self.journal.start_run(self.run_id, {"capital": capital, "limits": limits.__dict__}, mode)
        self._recover()

    # -------------------------------------------------------------------------------- recovery
    def _recover(self) -> None:
        st = self.journal.load_state(self.run_id)
        if not st:
            return
        b = self.broker
        b.cash, b.positions, b.avg_price = st["cash"], st["positions"], st["avg_price"]
        b.realized, b.costs_paid = st["realized"], st["costs"]
        b.pending = [Order(o["order_id"], o["symbol"], o["qty"], pd.Timestamp(o["created"])) for o in st["pending"]]
        self.risk.hwm = st.get("hwm")
        if st.get("risk_state") == State.HALTED.value:
            self.risk.state = State.HALTED
        self.resume_after = pd.Timestamp(st["last_ts"])
        self.alert("INFO", f"recovered state from journal at {st['last_ts']} (equity {st.get('equity'):.2f})")

    def _save(self, ts, equity) -> None:
        b = self.broker
        self.journal.save_state(self.run_id, {
            "cash": b.cash, "positions": b.positions, "avg_price": b.avg_price, "realized": b.realized,
            "costs": b.costs_paid, "pending": [{"order_id": o.order_id, "symbol": o.symbol, "qty": o.qty,
                                                "created": str(o.created)} for o in b.pending],
            "hwm": self.risk.hwm, "risk_state": self.risk.state.value, "last_ts": str(ts), "equity": equity})

    # ------------------------------------------------------------------------------------ loop
    def on_bars(self, bars: list[Bar]) -> None:
        if not bars:
            return
        ts = bars[0].ts
        if getattr(self, "resume_after", None) is not None and ts <= self.resume_after:
            return                           # already processed before the restart
        J, rid = self.journal, self.run_id
        bmap = {b.symbol: b for b in bars}
        J.many("INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?,?)",
               [(rid, str(b.ts), b.symbol, b.open, b.high, b.low, b.close, b.source, b.data_class, b.received_utc) for b in bars])
        # 1) fills at this bar's open for orders approved at the previous close
        fills = self.broker.execute(bmap)
        J.many("INSERT OR REPLACE INTO fills VALUES(?,?,?,?,?,?,?,?)",
               [(f["order_id"], rid, f["ts"], f["symbol"], f["qty"], f["price"], f["ref_price"], f["cost"]) for f in fills])
        # 2) append bar to history, mark to market
        for f in ("open", "high", "low", "close", "volume"):
            row = pd.DataFrame({b.symbol: [getattr(b, f)] for b in bars}, index=[ts])
            self.hist[f] = pd.concat([self.hist[f], row]) if ts not in self.hist[f].index else self.hist[f]
        for b in bars:
            self.last_seen[b.symbol] = ts
        marks = {s: float(self.hist["close"][s].dropna().iloc[-1]) for s in self.hist["close"].columns
                 if self.hist["close"][s].notna().any()}
        eq = self.broker.equity(marks)
        self.risk.update_equity(eq, str(ts.date()))
        gross = sum(abs(q * marks.get(s, 0)) for s, q in self.broker.positions.items())
        net = sum(q * marks.get(s, 0) for s, q in self.broker.positions.items())
        unreal = sum(q * (marks.get(s, 0) - self.broker.avg_price.get(s, 0)) for s, q in self.broker.positions.items())
        J.one("INSERT OR REPLACE INTO equity VALUES(?,?,?,?,?,?,?,?,?,?)",
              (rid, str(ts), eq, self.broker.cash, gross / eq if eq else 0, net / eq if eq else 0,
               self.broker.realized, unreal, self.broker.costs_paid, 0.0))
        J.many("INSERT OR REPLACE INTO positions VALUES(?,?,?,?,?,?)",
               [(rid, str(ts), s, q, self.broker.avg_price.get(s, 0), marks.get(s)) for s, q in self.broker.positions.items()])
        # 3) strategy proposal -> risk approval -> orders for next open
        try:
            m = self.market_builder(self.hist)
            W = self.strategy_fn(m)
            row = W.iloc[-1]
            cur_w = {s: q * marks.get(s, 0) / eq for s, q in self.broker.positions.items()} if eq > 0 else {}
            ages = {s: (ts - self.last_seen.get(s, pd.Timestamp.min)).total_seconds() / 3600 + 24
                    if s in self.last_seen else np.inf for s in m.symbols}
            if row.isna().all():
                proposed = None            # strategy says: no rebalance today (HOLD)
            else:
                proposed = {s: float(v) for s, v in row.fillna(0.0).items() if s in m.symbols}
            rets = m.close.pct_change(fill_method=None).iloc[-60:]
            cov = rets.cov()
            base = proposed if proposed is not None else cur_w
            ap = self.risk.approve(base, cur_w, ages, cov, m.ppy)
            sig_rows = []
            for s in sorted(set(ap.weights) | set(cur_w)):
                a, c = ap.weights.get(s, 0.0), cur_w.get(s, 0.0)
                p = (proposed or {}).get(s, c)
                action = _action(c, a)
                sig_rows.append((rid, str(ts), self.name, s, p, a, action))
            J.many("INSERT OR REPLACE INTO signals VALUES(?,?,?,?,?,?,?)", sig_rows)
            if self.risk.state != State.HALTED:
                orders = self.broker.submit(ap, marks, eq, ts)
                J.many("INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?)",
                       [(o.order_id, rid, str(ts), o.symbol, o.qty, "PENDING", ap.digest) for o in orders])
            else:
                self.broker.pending = []
            self.risk.record_success()
        except PermissionError:
            raise
        except Exception as e:  # noqa: BLE001 - every failure is journaled and counted
            self.risk.record_error(f"{type(e).__name__}: {e}")
            J.one("INSERT INTO events VALUES(?,?,?,?,?)", (rid, J.now(), "ERROR", "EXCEPTION", traceback.format_exc()[-2000:]))
            self.alert("ERROR", f"strategy/risk step failed: {e}")
        for ev in self.risk.events:
            J.one("INSERT INTO events VALUES(?,?,?,?,?)", (rid, ev.utc, ev.level, ev.code, ev.message))
            if ev.level in ("CRITICAL", "WARN"):
                self.alert(ev.level, ev.message)
        self.risk.events.clear()
        J.commit()
        self._save(ts, eq)

    def run(self, max_bars: int | None = None) -> None:
        for n, bars in enumerate(self.feed.bars()):
            self.on_bars(bars)
            if max_bars and n + 1 >= max_bars:
                break


def _action(cur: float, new: float, eps: float = 1e-6) -> str:
    if abs(new) < eps and abs(cur) < eps:
        return "NO_TRADE"
    if abs(new - cur) < 0.005:
        return "HOLD"
    if new > cur:
        return "BUY" if cur >= -eps else ("COVER" if new <= eps else "COVER+BUY")
    return "SELL" if new >= -eps else ("SHORT" if cur <= eps else "SELL+SHORT")
