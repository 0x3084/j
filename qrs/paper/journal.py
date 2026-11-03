"""Persistent trade journal (SQLite).

SQLite is chosen for the paper-trading journal because it is a single-writer, zero-operations,
crash-safe (WAL) embedded database that is trivially backed up as one file. The schema is plain SQL
so it can be moved to PostgreSQL unchanged when multiple writers or remote access are required.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, started_utc TEXT, config TEXT, mode TEXT);
CREATE TABLE IF NOT EXISTS bars(run_id TEXT, ts TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL,
    source TEXT, data_class TEXT, received_utc TEXT, PRIMARY KEY(run_id, ts, symbol));
CREATE TABLE IF NOT EXISTS signals(run_id TEXT, ts TEXT, strategy TEXT, symbol TEXT, proposed REAL, approved REAL,
    action TEXT, PRIMARY KEY(run_id, ts, strategy, symbol));
CREATE TABLE IF NOT EXISTS orders(order_id TEXT PRIMARY KEY, run_id TEXT, created_ts TEXT, symbol TEXT, qty REAL,
    status TEXT, approval_digest TEXT);
CREATE TABLE IF NOT EXISTS fills(order_id TEXT, run_id TEXT, ts TEXT, symbol TEXT, qty REAL, price REAL,
    ref_price REAL, cost REAL, PRIMARY KEY(order_id));
CREATE TABLE IF NOT EXISTS equity(run_id TEXT, ts TEXT, equity REAL, cash REAL, gross REAL, net REAL,
    realized REAL, unrealized REAL, costs REAL, financing REAL, PRIMARY KEY(run_id, ts));
CREATE TABLE IF NOT EXISTS positions(run_id TEXT, ts TEXT, symbol TEXT, qty REAL, avg_price REAL, mark REAL,
    PRIMARY KEY(run_id, ts, symbol));
CREATE TABLE IF NOT EXISTS events(run_id TEXT, utc TEXT, level TEXT, code TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS state(run_id TEXT PRIMARY KEY, payload TEXT, updated_utc TEXT);
"""


class Journal:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.con = sqlite3.connect(path, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)

    def now(self) -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def start_run(self, run_id: str, config: dict, mode: str) -> None:
        self.con.execute("INSERT OR IGNORE INTO runs VALUES(?,?,?,?)", (run_id, self.now(), json.dumps(config), mode))
        self.con.commit()

    def many(self, sql: str, rows: list[tuple]) -> None:
        if rows:
            self.con.executemany(sql, rows)

    def one(self, sql: str, row: tuple) -> None:
        self.con.execute(sql, row)

    def commit(self) -> None:
        self.con.commit()

    def save_state(self, run_id: str, payload: dict) -> None:
        self.con.execute("INSERT OR REPLACE INTO state VALUES(?,?,?)", (run_id, json.dumps(payload), self.now()))
        self.con.commit()

    def load_state(self, run_id: str) -> dict | None:
        r = self.con.execute("SELECT payload FROM state WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.con.execute(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
