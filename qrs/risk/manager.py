"""Independent, mandatory pre-trade and portfolio risk controls.

Design: strategies only *propose* target weights. ``RiskManager.approve`` is the single gate that
turns proposals into an ``Approval`` (clipped weights + an HMAC-style digest). The simulated broker
refuses any order set whose digest does not match an approval issued by the risk manager, so a
strategy cannot route around the controls.

States:  ACTIVE -> REDUCE_ONLY (daily-loss breach; resets next session)
         ACTIVE/REDUCE_ONLY -> HALTED (drawdown breach, kill switch, critical errors, feed down;
         needs explicit manual reset)
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd


class State(str, Enum):
    ACTIVE = "ACTIVE"
    REDUCE_ONLY = "REDUCE_ONLY"
    HALTED = "HALTED"


@dataclass
class RiskLimits:
    max_position_weight: float = 0.25        # |w_i| per instrument (fraction of equity)
    max_gross: float = 1.5                   # sum |w|
    max_net: float = 1.0                     # |sum w|
    max_leverage: float = 1.5                # gross / equity incl. cash borrow
    max_group_weight: float = 0.6            # concentration per asset-class / correlation cluster
    max_portfolio_vol: float = 0.20          # ex-ante annualised vol from trailing covariance
    max_daily_loss: float = 0.03             # -3% on the day -> REDUCE_ONLY
    max_drawdown: float = 0.20               # -20% from high-water mark -> HALTED
    max_data_age_hours: float = 36.0         # per instrument; older -> instrument frozen
    max_stale_fraction: float = 0.5          # if more than half the universe is stale -> HALTED (feed down)
    max_consecutive_errors: int = 3          # critical errors -> HALTED

    @classmethod
    def from_dict(cls, d: dict) -> "RiskLimits":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Approval:
    weights: dict[str, float]
    digest: str
    issued_utc: str
    state: str
    notes: list[str] = field(default_factory=list)


@dataclass
class RiskEvent:
    utc: str
    level: str
    code: str
    message: str


class RiskManager:
    def __init__(self, limits: RiskLimits, groups: dict[str, str] | None = None, kill_file: Path | None = None):
        self.limits = limits
        self.groups = groups or {}
        self.kill_file = kill_file
        self.state = State.ACTIVE
        self.events: list[RiskEvent] = []
        self.hwm: float | None = None
        self.day_start_equity: float | None = None
        self.day: str | None = None
        self.consecutive_errors = 0
        self._secret = secrets.token_bytes(32)

    # ---------------------------------------------------------------------------------- events
    def _event(self, level: str, code: str, msg: str) -> None:
        self.events.append(RiskEvent(datetime.now(timezone.utc).isoformat(timespec="seconds"), level, code, msg))

    def halt(self, reason: str) -> None:
        if self.state != State.HALTED:
            self._event("CRITICAL", "HALT", reason)
        self.state = State.HALTED

    def reset(self, operator: str) -> None:
        """Manual reset after a HALT (operator acknowledges)."""
        self._event("INFO", "RESET", f"manual reset by {operator}")
        self.state = State.ACTIVE
        self.consecutive_errors = 0

    def kill_switch_engaged(self) -> bool:
        return bool(self.kill_file and self.kill_file.exists())

    def record_error(self, msg: str, critical: bool = True) -> None:
        self._event("ERROR", "ERROR", msg)
        if critical:
            self.consecutive_errors += 1
            if self.consecutive_errors >= self.limits.max_consecutive_errors:
                self.halt(f"{self.consecutive_errors} consecutive critical errors")

    def record_success(self) -> None:
        self.consecutive_errors = 0

    # ---------------------------------------------------------------------------- portfolio
    def update_equity(self, equity: float, session: str) -> None:
        if self.hwm is None or equity > self.hwm:
            self.hwm = equity
        if session != self.day:
            self.day, self.day_start_equity = session, equity
            if self.state == State.REDUCE_ONLY:
                self._event("INFO", "NEW_SESSION", "daily-loss lock released")
                self.state = State.ACTIVE
        dd = equity / self.hwm - 1
        if dd <= -self.limits.max_drawdown:
            self.halt(f"drawdown {dd:.1%} breached limit {-self.limits.max_drawdown:.0%}")
        day_ret = equity / self.day_start_equity - 1 if self.day_start_equity else 0.0
        if day_ret <= -self.limits.max_daily_loss and self.state == State.ACTIVE:
            self.state = State.REDUCE_ONLY
            self._event("WARN", "DAILY_LOSS", f"daily loss {day_ret:.1%} -> reduce-only")

    # ------------------------------------------------------------------------------ approve
    def approve(self, proposed: dict[str, float], current: dict[str, float], data_age_hours: dict[str, float],
                cov: pd.DataFrame | None = None, ppy: int = 252) -> Approval:
        L = self.limits
        notes: list[str] = []
        if self.kill_switch_engaged():
            self.halt("kill switch file present")
        syms = sorted(set(proposed) | set(current))
        cur = np.array([current.get(s, 0.0) for s in syms])
        w = np.array([proposed.get(s, 0.0) for s in syms], float)
        w = np.nan_to_num(w)

        # stale data protection
        ages = np.array([data_age_hours.get(s, np.inf) for s in syms])
        stale = ages > L.max_data_age_hours
        relevant = (np.abs(w) > 0) | (np.abs(cur) > 0)
        if relevant.any() and stale[relevant].mean() > L.max_stale_fraction:
            self.halt(f"market data stale for {int(stale[relevant].sum())}/{int(relevant.sum())} instruments (feed down?)")
        if stale.any():
            w = np.where(stale, cur, w)          # cannot trade instruments without fresh data
            notes.append(f"frozen (stale data): {[s for s, x in zip(syms, stale) if x]}")

        if self.state == State.HALTED:
            return self._sign(dict(zip(syms, cur)), notes + ["HALTED: no new orders; positions frozen"])

        # per-position cap
        if np.any(np.abs(w) > L.max_position_weight):
            notes.append("position cap applied")
            w = np.clip(w, -L.max_position_weight, L.max_position_weight)
        # concentration per group
        if self.groups:
            gser = pd.Series([self.groups.get(s, s) for s in syms])
            for g in gser.unique():
                mask = (gser == g).to_numpy()
                gw = np.abs(w[mask]).sum()
                if gw > L.max_group_weight:
                    w[mask] *= L.max_group_weight / gw
                    notes.append(f"group cap {g}")
        # net / gross / leverage
        if abs(w.sum()) > L.max_net:
            w *= L.max_net / abs(w.sum())
            notes.append("net cap")
        g = np.abs(w).sum()
        cap = min(L.max_gross, L.max_leverage)
        if g > cap:
            w *= cap / g
            notes.append("gross/leverage cap")
        # ex-ante portfolio vol (correlation-aware)
        if cov is not None:
            C = cov.reindex(index=syms, columns=syms).fillna(0.0).to_numpy()
            v = float(np.sqrt(max(w @ C @ w, 0.0) * ppy))
            if v > L.max_portfolio_vol:
                w *= L.max_portfolio_vol / v
                notes.append(f"vol cap ({v:.1%} -> {L.max_portfolio_vol:.0%})")
        # reduce-only: each position may only move toward zero
        if self.state == State.REDUCE_ONLY:
            w = np.where(np.sign(w) == np.sign(cur), np.sign(cur) * np.minimum(np.abs(w), np.abs(cur)), 0.0)
            notes.append("REDUCE_ONLY")
        for n in notes:
            self._event("INFO", "ADJUST", n)
        return self._sign(dict(zip(syms, w.tolist())), notes)

    def _sign(self, weights: dict[str, float], notes: list[str]) -> Approval:
        payload = json.dumps({k: round(v, 10) for k, v in sorted(weights.items())}).encode()
        digest = hashlib.blake2b(payload, key=self._secret, digest_size=16).hexdigest()
        return Approval(weights, digest, datetime.now(timezone.utc).isoformat(timespec="seconds"), self.state.value, notes)

    def verify(self, ap: Approval) -> bool:
        payload = json.dumps({k: round(v, 10) for k, v in sorted(ap.weights.items())}).encode()
        return hashlib.blake2b(payload, key=self._secret, digest_size=16).hexdigest() == ap.digest

    def status(self) -> dict:
        return {"state": self.state.value, "limits": asdict(self.limits), "hwm": self.hwm,
                "consecutive_errors": self.consecutive_errors, "kill_switch": self.kill_switch_engaged(),
                "recent_events": [asdict(e) for e in self.events[-50:]]}
