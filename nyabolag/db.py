"""SQLite storage. One file, WAL mode, fine for a single small VPS."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    imported_at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    new_count INTEGER NOT NULL,
    is_baseline INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS companies (
    orgnr TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    form TEXT NOT NULL,
    reg_date TEXT,
    street TEXT,
    postcode TEXT,
    city TEXT,
    description TEXT,
    first_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    last_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    is_new INTEGER NOT NULL DEFAULT 0,
    is_shelf INTEGER NOT NULL DEFAULT 0  -- shelf company (lagerbolag) at a formation agent's address
);
-- Advertising opt-out (reklamspärr) as reported by SCB, via SCB's API or Bolagsverket's
-- värdefulla-datamängder API. blocked: 1 = opted out, 0 = checked and not opted out.
CREATE TABLE IF NOT EXISTS reklamsparr (
    orgnr TEXT PRIMARY KEY,
    blocked INTEGER NOT NULL,
    source TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_companies_new ON companies(first_snapshot_id) WHERE is_new = 1;

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL DEFAULT '',
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|active|past_due|canceled
    filters TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    sent_at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    csv_path TEXT NOT NULL,
    UNIQUE(customer_id, snapshot_id)
);
CREATE TABLE IF NOT EXISTS stripe_events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    message TEXT
);
"""

ACTIVE_STATUSES = ("active",)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
    if "is_shelf" not in cols:  # migrate databases created before is_shelf existed
        conn.execute("ALTER TABLE companies ADD COLUMN is_shelf INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def get_filters(row: sqlite3.Row) -> dict:
    try:
        return json.loads(row["filters"] or "{}")
    except json.JSONDecodeError:
        return {}
