"""Import advertising opt-out flags (reklamspärr) and look them up.

Where the flag exists (verified against real responses / documentation, see docs/04):
  * Bolagsverket "API för värdefulla datamängder" (free, OAuth client credentials after a
    free registration): every organisation object has a top-level `reklamsparr` field
    (source SCB). In 300 real responses for companies registered 2026-09-21 it was null
    for all of them; null is read as "no reklamspärr registered" (assumption to confirm
    with Bolagsverket/SCB, see docs/04).
  * SCB "Företagsregistret" free API (personal API key via SCB's Registreringsportalen,
    BankID): `reklamSparrTyp` 1 = accepts advertising, 2 = has opted out.

Two ways in:
  * `nyabolag verify-reklamsparr`: looks up candidates live in the HVD API (hvd_api.py) and
    stores the result with the time of the lookup. A minimised evidence line per lookup
    (org number, HTTP status, time, raw reklamsparr value) is kept in data/raw/api/.
  * `nyabolag import-reklamsparr <file>`: imports saved VDM/SCB responses.
A status only counts as verified if a 200 response contained the `reklamsparr` field for that
org number. Errors, timeouts and missing fields leave the company unverified, which means it
is excluded from customer deliveries (see delivery.verified_cutoff).
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Iterator

from datetime import datetime, timedelta, timezone

from .config import Config
from .db import ACTIVE_STATUSES, get_filters, now_iso, tx


def _orgnr(value) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 12 and digits.startswith("16"):
        digits = digits[2:]
    return digits if len(digits) == 10 and digits[2] not in "01" else None


def _vdm_blocked(value) -> int:
    """Bolagsverket VDM `reklamsparr`. null -> 0. Unknown non-null shapes fail safe -> 1."""
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, dict):
        value = value.get("kod", value.get("value", "unknown"))
    return 0 if str(value).strip().upper() in ("NEJ", "N", "FALSE") else 1


def _walk(obj) -> Iterator[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def extract(obj) -> Iterator[tuple[str, int, str]]:
    """Yield (orgnr, blocked, source) from any saved VDM or SCB API response."""
    for d in _walk(obj):
        if "reklamsparr" in d and "organisationsidentitet" in d:
            ident = d["organisationsidentitet"]
            nr = _orgnr(ident.get("identitetsbeteckning") if isinstance(ident, dict) else ident)
            if nr:
                yield nr, _vdm_blocked(d["reklamsparr"]), "bolagsverket-vdm"
        elif "reklamSparrTyp" in d and ("peOrgNr" in d or "PeOrgNr" in d):
            nr = _orgnr(d.get("peOrgNr", d.get("PeOrgNr")))
            if nr:
                try:
                    blocked = int(str(d["reklamSparrTyp"]).strip() == "2")
                except ValueError:
                    blocked = 1
                yield nr, blocked, "scb-foretagsregistret"


def import_file(conn: sqlite3.Connection, path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        docs = [json.loads(text)]
    except json.JSONDecodeError:
        docs = [json.loads(line) for line in text.splitlines() if line.strip()]
    found: dict[str, tuple[int, str, str]] = {}
    now = now_iso()
    for doc in docs:
        # Saved responses may carry their own fetch time; that is when the flag was checked.
        checked = doc.get("fetched_at", now) if isinstance(doc, dict) else now
        if isinstance(doc, dict) and doc.get("http_status", 200) != 200:
            continue  # an error response verifies nothing
        for nr, blocked, source in extract(doc):
            prev = found.get(nr)
            found[nr] = (max(blocked, prev[0]) if prev else blocked, source, checked)  # any opt-out wins
    with tx(conn):
        _upsert(conn, [(nr, b, s, c) for nr, (b, s, c) in found.items()])
    return {"checked": len(found), "blocked": sum(v[0] for v in found.values())}


def _upsert(conn: sqlite3.Connection, rows: list[tuple[str, int, str, str]]) -> None:
    conn.executemany(
        "INSERT INTO reklamsparr (orgnr, blocked, source, checked_at) VALUES (?,?,?,?) "
        "ON CONFLICT(orgnr) DO UPDATE SET blocked=excluded.blocked, source=excluded.source, "
        "checked_at=excluded.checked_at",
        rows,
    )


def candidates(conn: sqlite3.Connection, cfg: Config, extra_filters: list[dict] | None = None,
               snapshots: int = 1) -> list[str]:
    """Org numbers that need a (re-)check: new, non-shelf companies from the last `snapshots`
    snapshots that match an active customer's filter or one of `extra_filters`, and whose status
    is missing or will expire within 7 days."""
    from .delivery import matches, new_companies_since  # local import avoids a cycle

    ids = [r["id"] for r in conn.execute("SELECT id FROM snapshots ORDER BY id DESC LIMIT ?", (snapshots,))]
    if not ids:
        return []
    filters = [get_filters(c) for c in conn.execute(
        f"SELECT filters FROM customers WHERE status IN ({','.join('?' * len(ACTIVE_STATUSES))})",
        ACTIVE_STATUSES)] + list(extra_filters or [])
    if not filters:
        return []
    refresh_before = (datetime.now(timezone.utc)
                      - timedelta(days=max(cfg.reklamsparr_max_age_days - 7, 1))).replace(microsecond=0).isoformat()
    out = []
    for r in new_companies_since(conn, min(ids) - 1, max(ids)):
        if not any(matches(r, f) for f in filters):
            continue
        if r["rs_checked_at"] and r["rs_checked_at"] >= refresh_before:
            continue
        out.append(r["orgnr"])
    return out


def verify(conn: sqlite3.Connection, cfg: Config, orgnrs: list[str], client=None) -> dict:
    """Look up each org number in the HVD API and store verified statuses."""
    from .hvd_api import HvdClient

    client = client or HvdClient(cfg)
    cfg.ensure_dirs()
    evidence = cfg.raw_dir / "api"
    evidence.mkdir(parents=True, exist_ok=True)
    log_path = evidence / f"{datetime.now(timezone.utc).date().isoformat()}_hvd.jsonl"
    stats = {"candidates": len(orgnrs), "verified": 0, "blocked": 0, "failed": 0}
    with open(log_path, "a", encoding="utf-8") as log:
        for nr in orgnrs:
            status, body = client.organisation(nr)
            fetched = now_iso()
            hits = [(b, s) for o, b, s in extract(body) if o == nr] if status == 200 else []
            # Evidence log, minimised: no addresses, c/o names or descriptions are kept.
            raw_flags = [d.get("reklamsparr") for d in _walk(body) if isinstance(d, dict) and "reklamsparr" in d]
            log.write(json.dumps({"orgnr": nr, "http_status": status, "fetched_at": fetched,
                                  "reklamsparr_raw": raw_flags, "verified": bool(hits)},
                                 ensure_ascii=False) + "\n")
            if not hits:
                stats["failed"] += 1
                continue
            blocked = max(b for b, _ in hits)
            with tx(conn):
                _upsert(conn, [(nr, blocked, hits[0][1], fetched)])
            stats["verified"] += 1
            stats["blocked"] += blocked
    stats["evidence_file"] = str(log_path)
    return stats
