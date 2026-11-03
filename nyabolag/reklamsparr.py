"""Import advertising opt-out flags (reklamspärr) and look them up.

Where the flag exists (verified against real responses / documentation, see docs/04):
  * Bolagsverket "API för värdefulla datamängder" (free, OAuth client credentials after a
    free registration): every organisation object has a top-level `reklamsparr` field
    (source SCB). In 300 real responses for companies registered 2026-09-21 it was null
    for all of them; null is read as "no reklamspärr registered" (assumption to confirm
    with Bolagsverket/SCB, see docs/04).
  * SCB "Företagsregistret" free API (personal API key via SCB's Registreringsportalen,
    BankID): `reklamSparrTyp` 1 = accepts advertising, 2 = has opted out.

This module never calls those APIs itself (both need credentials the owner must create);
it imports saved JSON/JSONL responses: `nyabolag import-reklamsparr responses.jsonl`.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Iterator

from .db import now_iso, tx


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
        for nr, blocked, source in extract(doc):
            prev = found.get(nr)
            found[nr] = (max(blocked, prev[0]) if prev else blocked, source, checked)  # any opt-out wins
    with tx(conn):
        conn.executemany(
            "INSERT INTO reklamsparr (orgnr, blocked, source, checked_at) VALUES (?,?,?,?) "
            "ON CONFLICT(orgnr) DO UPDATE SET blocked=excluded.blocked, source=excluded.source, "
            "checked_at=excluded.checked_at",
            [(nr, b, s, c) for nr, (b, s, c) in found.items()],
        )
    return {"checked": len(found), "blocked": sum(v[0] for v in found.values())}
