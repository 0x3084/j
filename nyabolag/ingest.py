"""Fetch the bulk file, store it, and diff it against the previous snapshot."""
from __future__ import annotations

import hashlib
import re
import shutil
from collections import Counter
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


# Shelf companies (lagerbolag) are registered in bulk by formation agents under numbered
# names ("Grundbulten 163173 AB") at the agent's address and renamed when sold. In the
# 2026-10-26 file they were ~27 % of all new registrations. They are real registrations
# but useless as leads, so they are flagged and never delivered.
SHELF_NAME_RE = re.compile(r"^(?P<stem>\D+?)\s*(?:nr\s*)?\d{3,}\s+(?:AB|Aktiebolag)$", re.I)
SHELF_STEM_MIN = 3     # same numbered stem used >= 3 times among recent registrations
SHELF_ADDRESS_MIN = 10  # >= 10 recent registrations at one address = formation agent


def _flag_shelf_companies(conn: sqlite3.Connection, cutoff: date) -> int:
    rows = conn.execute(
        "SELECT orgnr, name, upper(street) AS st, postcode FROM companies WHERE is_new = 1 AND reg_date >= ?",
        (cutoff.isoformat(),)).fetchall()
    stems = Counter(m.group("stem").strip().lower() for r in rows if (m := SHELF_NAME_RE.match(r["name"])))
    addresses = Counter((r["st"], r["postcode"]) for r in rows if r["st"])
    shelf = []
    for r in rows:
        m = SHELF_NAME_RE.match(r["name"])
        if (m and stems[m.group("stem").strip().lower()] >= SHELF_STEM_MIN) or \
                (r["st"] and addresses[(r["st"], r["postcode"])] >= SHELF_ADDRESS_MIN):
            shelf.append((r["orgnr"],))
    conn.executemany("UPDATE companies SET is_shelf = 1 WHERE orgnr = ?", shelf)
    return len(shelf)


def ingest(conn: sqlite3.Connection, path: Path, cfg: Config, today: date | None = None) -> dict:
    """Import one snapshot. Idempotent per file hash.

    "New" is decided by Bolagsverket's registration date, not by first appearance:
    a company is new when it was never seen in an earlier snapshot AND its
    registreringsdatum lies within NEW_MAX_AGE_DAYS before `today` (the file date).
    Records that merely appear late, reappear, or change are therefore never "new".
    The file holds the full register history, so the first import needs no baseline.
    """
    today = today or date.today()
    digest = sha256_file(path)
    existing = conn.execute("SELECT id FROM snapshots WHERE sha256 = ?", (digest,)).fetchone()
    if existing:
        return {"snapshot_id": existing["id"], "skipped": True, "new": 0}

    is_first = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0] == 0
    cutoff = today - timedelta(days=cfg.new_max_age_days)
    stats: dict = {}
    new_count = 0
    with tx(conn):
        cur = conn.execute(
            "INSERT INTO snapshots (sha256, imported_at, row_count, new_count, is_baseline) VALUES (?,?,?,?,?)",
            (digest, now_iso(), 0, 0, int(is_first)),
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
            is_new = c.reg_date is not None and cutoff <= c.reg_date <= today
            new_count += int(is_new)
            conn.execute(
                "INSERT INTO companies (orgnr, name, form, reg_date, street, postcode, city, description, "
                "first_snapshot_id, last_snapshot_id, is_new) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (c.orgnr, c.name, c.form, reg, c.street, c.postcode, c.city, c.description, sid, sid, int(is_new)),
            )
        shelf = _flag_shelf_companies(conn, cutoff)
        conn.execute(
            "UPDATE snapshots SET row_count=?, new_count=? WHERE id=?", (stats["yielded"], new_count, sid)
        )
    return {"snapshot_id": sid, "skipped": False, "new": new_count, "shelf_flagged": shelf,
            "first_import": is_first, **stats}
