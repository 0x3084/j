"""Customer filters, CSV export and the weekly delivery run."""
from __future__ import annotations

import csv
import io
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .db import ACTIVE_STATUSES, get_filters, now_iso, tx
from .mailer import send_mail

DEFAULT_FORMS = ["AB"]
CSV_COLUMNS = ["Organisationsnummer", "Namn", "Bolagsform", "Registreringsdatum",
               "Adress", "Postnummer", "Ort", "Verksamhet", "Reklamspärr"]
# Data minimisation: no c/o names, no board members, no sole traders. The c/o line is not
# even stored (it is often a private person's name).


def normalise_filters(raw: dict) -> dict:
    """Clean user-provided filter input into a canonical dict."""
    def as_list(v) -> list[str]:
        if isinstance(v, str):
            v = re.split(r"[,\n;]+", v)
        return [s.strip() for s in (v or []) if s and s.strip()]

    prefixes = sorted({re.sub(r"\D", "", p) for p in as_list(raw.get("postcode_prefixes"))} - {""})
    prefixes = [p[:5] for p in prefixes]
    forms = sorted({f.upper() for f in as_list(raw.get("forms"))} - {"EF", "E"}) or DEFAULT_FORMS
    return {
        "postcode_prefixes": prefixes,
        "cities": sorted({c.lower() for c in as_list(raw.get("cities"))}),
        "forms": forms,
        "keywords": sorted({k.lower() for k in as_list(raw.get("keywords"))}),
    }


def matches(company: sqlite3.Row | dict, f: dict) -> bool:
    forms = f.get("forms") or DEFAULT_FORMS
    if company["form"] not in forms:
        return False
    prefixes, cities = f.get("postcode_prefixes") or [], f.get("cities") or []
    if prefixes or cities:
        pc = company["postcode"] or ""
        city = (company["city"] or "").lower()
        if not (any(pc.startswith(p) for p in prefixes) or city in cities):
            return False
    kws = f.get("keywords") or []
    if kws:
        text = f"{company['name']} {company['description'] or ''}".lower()
        if not any(k in text for k in kws):
            return False
    return True


def verified_cutoff(cfg: Config) -> str:
    """Oldest acceptable reklamspärr check timestamp (ISO, UTC)."""
    return (datetime.now(timezone.utc) - timedelta(days=cfg.reklamsparr_max_age_days)).replace(
        microsecond=0).isoformat()


def new_companies_since(conn: sqlite3.Connection, after_snapshot_id: int, upto_snapshot_id: int,
                        verified_since: str | None = None) -> list[sqlite3.Row]:
    """New, non-shelf companies that have no reklamspärr.

    verified_since=None: also returns companies whose status is unknown (internal use only).
    verified_since=<ISO timestamp>: only companies verified as NOT opted out at or after that
    time. Missing or stale statuses are treated as unverified and excluded. This is the mode
    used for every customer delivery.
    """
    if verified_since is None:
        join, extra, params = "LEFT JOIN", "", ()
    else:
        join, extra, params = "JOIN", "AND r.checked_at >= ? ", (verified_since,)
    return conn.execute(
        f"SELECT c.*, r.blocked AS rs_blocked, r.checked_at AS rs_checked_at FROM companies c "
        f"{join} reklamsparr r ON r.orgnr = c.orgnr "
        f"WHERE c.is_new = 1 AND c.is_shelf = 0 AND COALESCE(r.blocked, 0) = 0 {extra}"
        "AND c.first_snapshot_id > ? AND c.first_snapshot_id <= ? ORDER BY c.reg_date DESC, c.name",
        (*params, after_snapshot_id, upto_snapshot_id),
    ).fetchall()


def _rs_label(r) -> str:
    try:
        checked = r["rs_checked_at"]
    except (IndexError, KeyError):
        checked = None
    return f"Nej (kontrollerad {checked[:10]})" if checked else "Ej kontrollerad"


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value) -> str:
    """Neutralise spreadsheet formula injection: register data is third-party input."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def to_csv(rows: list) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")  # Swedish Excel expects ';'
    w.writerow(CSV_COLUMNS)
    for r in rows:
        pc = r["postcode"] or ""
        w.writerow([_cell(v) for v in (
            f"{r['orgnr'][:6]}-{r['orgnr'][6:]}", r["name"], r["form"], r["reg_date"] or "",
            r["street"] or "", f"{pc[:3]} {pc[3:]}" if len(pc) == 5 else pc, r["city"] or "", r["description"] or "",
            _rs_label(r),
        )])
    return ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel detects UTF-8


def preview(conn: sqlite3.Connection, filters: dict, last_n_snapshots: int = 4,
            verified_since: str | None = None) -> list[sqlite3.Row]:
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM snapshots ORDER BY id DESC LIMIT ?", (last_n_snapshots,)).fetchall()]
    if not ids:
        return []
    rows = new_companies_since(conn, min(ids) - 1, max(ids), verified_since)
    return [r for r in rows if matches(r, filters)]


def deliver_all(conn: sqlite3.Connection, cfg: Config) -> list[dict]:
    """Send every active customer the companies new since their last delivery. Idempotent."""
    latest = conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    if not latest:
        return []
    latest_id = latest["id"]
    cfg.ensure_dirs()
    results = []
    customers = conn.execute(
        f"SELECT * FROM customers WHERE status IN ({','.join('?' * len(ACTIVE_STATUSES))})", ACTIVE_STATUSES
    ).fetchall()
    for cust in customers:
        last = conn.execute(
            "SELECT MAX(snapshot_id) AS s FROM deliveries WHERE customer_id = ?", (cust["id"],)
        ).fetchone()["s"]
        if last is not None and last >= latest_id:
            continue  # already delivered this snapshot
        if last is None:
            # New customer: start from the previous snapshot so the first mail has one week of data.
            last = latest_id - 1
        filters = get_filters(cust)
        rows = [r for r in new_companies_since(conn, last, latest_id, verified_cutoff(cfg))
                if matches(r, filters)]
        data = to_csv(rows)
        path = cfg.deliveries_dir / f"c{cust['id']}-s{latest_id}.csv"
        path.write_bytes(data)
        body = (
            f"Hej!\n\nHär är veckans nyregistrerade bolag som matchar ditt urval: {len(rows)} st.\n"
            f"Listan finns som bifogad CSV-fil (öppnas i Excel).\n\n"
            f"Ändra urval eller hantera prenumerationen: {cfg.base_url}/login\n\n"
            "Källa: Bolagsverket, värdefulla datamängder (öppna data).\n"
        )
        send_mail(cfg, cust["email"], f"Nya bolag denna vecka: {len(rows)} st", body,
                  attachment=(path.name, data, "text/csv"))
        with tx(conn):
            conn.execute(
                "INSERT INTO deliveries (customer_id, snapshot_id, sent_at, row_count, csv_path) VALUES (?,?,?,?,?)",
                (cust["id"], latest_id, now_iso(), len(rows), str(path)),
            )
        results.append({"customer_id": cust["id"], "rows": len(rows)})
    return results


def export(conn: sqlite3.Connection, filters: dict, since_snapshots: int, out: Path,
           verified_since: str | None = None) -> int:
    """Manual export for concierge delivery. Pass verified_since (delivery rule) for anything a
    customer receives; None includes unverified companies and is for internal checks only."""
    rows = preview(conn, normalise_filters(filters), since_snapshots, verified_since)
    out.write_bytes(to_csv(rows))
    return len(rows)
