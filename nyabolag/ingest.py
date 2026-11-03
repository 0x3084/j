"""Fetch the bulk file, store it, and diff it against the previous snapshot."""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from .bulkfile import iter_companies
from .config import Config
from .db import now_iso, tx


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(cfg: Config) -> Path:
    """Download the bulk file to data/raw/. Returns the local path."""
    if not cfg.bulkfile_url:
        raise RuntimeError("BULKFILE_URL is not set")
    cfg.ensure_dirs()
    tmp = cfg.raw_dir / "download.tmp"
    req = urllib.request.Request(cfg.bulkfile_url, headers={"User-Agent": "nyabolag/0.1"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    digest = sha256_file(tmp)
    final = cfg.raw_dir / f"bulkfil-{date.today().isoformat()}-{digest[:12]}.zip"
    tmp.replace(final)
    return final


def ingest(conn: sqlite3.Connection, path: Path, cfg: Config, today: date | None = None) -> dict:
    """Import one snapshot. Idempotent per file hash.

    The first snapshot ever imported is a baseline: nothing in it is "new".
    Later snapshots mark companies whose org number was never seen before as new,
    provided their registration date (when known) is recent. This avoids sending
    old companies that merely reappear after a data correction.
    """
    today = today or date.today()
    digest = sha256_file(path)
    existing = conn.execute("SELECT id FROM snapshots WHERE sha256 = ?", (digest,)).fetchone()
    if existing:
        return {"snapshot_id": existing["id"], "skipped": True, "new": 0}

    is_baseline = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
    cutoff = today - timedelta(days=cfg.new_max_age_days)
    stats: dict = {}
    new_count = 0
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO snapshots (sha256, imported_at, row_count, new_count, is_baseline) VALUES (?,?,?,?,?)",
            (digest, now_iso(), 0, 0, int(is_baseline)),
        )
        sid = cur.lastrowid
        for c in iter_companies(path, stats):
            reg = c.reg_date.isoformat() if c.reg_date else None
            row = conn.execute("SELECT orgnr FROM companies WHERE orgnr = ?", (c.orgnr,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE companies SET name=?, form=?, reg_date=?, street=?, postcode=?, city=?, "
                    "description=?, last_snapshot_id=? WHERE orgnr=?",
                    (c.name, c.form, reg, c.street, c.postcode, c.city, c.description, sid, c.orgnr),
                )
                continue
            is_new = (not is_baseline) and (c.reg_date is None or c.reg_date >= cutoff)
            new_count += int(is_new)
            conn.execute(
                "INSERT INTO companies (orgnr, name, form, reg_date, street, postcode, city, description, "
                "first_snapshot_id, last_snapshot_id, is_new) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (c.orgnr, c.name, c.form, reg, c.street, c.postcode, c.city, c.description, sid, sid, int(is_new)),
            )
        conn.execute(
            "UPDATE snapshots SET row_count=?, new_count=? WHERE id=?", (stats["yielded"], new_count, sid)
        )
    return {"snapshot_id": sid, "skipped": False, "new": new_count, "baseline": is_baseline, **stats}
