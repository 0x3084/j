"""Generate the sample report for Norrköping, Linköping and Finspång from an ingested database.

usage: NYABOLAG_DATA_DIR=... python validation/region_report.py <out_dir> [--draft-note TEXT]

Writes:
  <out_dir>/nya-bolag-<kommun>.csv     full customer format (incl. street address)  -> internal
  <out_dir>/provrapport-intern.html    full report incl. addresses                   -> internal
  <out_dir>/provrapport-kund.html      prospect version: NO street addresses          -> show to prospects

Municipalities are matched on postal town (postort). Postal towns and municipal borders do
not coincide exactly; the lists below cover the towns observed in the data plus well-known
postal towns of each municipality.
"""
from __future__ import annotations

import argparse
import html
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyabolag.config import Config  # noqa: E402
from nyabolag.db import connect  # noqa: E402
from nyabolag.delivery import _rs_label, normalise_filters, preview, to_csv  # noqa: E402

KOMMUNER = {
    "Norrköping": ["Norrköping", "Kolmården", "Krokek", "Åby", "Skärblacka", "Svärtinge", "Vikbolandet",
                   "Kimstad", "Norsholm", "Östra Husby", "Arkösund", "Simonstorp", "Strömsfors"],
    "Linköping": ["Linköping", "Linghem", "Ljungsbro", "Malmslätt", "Sturefors", "Vikingstad", "Vreta Kloster",
                  "Brokind", "Nykil", "Ulrika"],
    "Finspång": ["Finspång", "Rejmyre", "Hällestad", "Igelfors", "Lotorp", "Grytgöl", "Ljusfallshammar"],
}
FORMS = ["AB", "HB", "KB", "EK"]
FORM_NAMES = {"AB": "Aktiebolag", "HB": "Handelsbolag", "KB": "Kommanditbolag", "EK": "Ekonomisk förening"}

CSS = """
:root{--fg:#1b1f24;--muted:#5b6470;--bg:#fff;--line:#dfe2e6;--accent:#1f5f8b;--warn:#8a5a00;--warnbg:#fff6e0}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--fg);background:var(--bg)}
main{max-width:1000px;margin:0 auto;padding:28px 16px 48px}h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.15rem;margin:28px 0 8px}
.muted{color:var(--muted)}.draft{background:var(--warnbg);color:var(--warn);border:1px solid #f0d9a8;border-radius:8px;padding:10px 14px;margin:14px 0}
.kpis{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 14px;min-width:150px}
.kpi b{display:block;font-size:1.5rem}table{width:100%;border-collapse:collapse;font-size:.88rem}th,td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#f5f7f9}td:first-child{white-space:nowrap}.scroll{overflow-x:auto}footer{margin-top:32px;font-size:.8rem;color:var(--muted)}
@media print{.scroll{overflow:visible}main{padding:0}}
"""


def esc(s) -> str:
    return html.escape(str(s or ""))


def short(text: str, n: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + " …"


def iso_week(d: str) -> str:
    y, w, _ = date.fromisoformat(d).isocalendar()
    return f"v{w}"


def build(out: Path, draft_note: str | None, file_date: str) -> None:
    cfg = Config()
    conn = connect(cfg.db_path)
    out.mkdir(parents=True, exist_ok=True)
    snaps = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    per_kommun = {}
    for kommun, towns in KOMMUNER.items():
        rows = preview(conn, normalise_filters({"cities": towns, "forms": FORMS}), snaps)
        per_kommun[kommun] = rows
        (out / f"nya-bolag-{kommun.lower()}.csv").write_bytes(to_csv(rows))

    all_rows = [r for rows in per_kommun.values() for r in rows]
    dates = sorted(r["reg_date"] for r in all_rows)
    period = f"{dates[0]} – {dates[-1]}" if dates else "–"
    excluded = conn.execute(
        "SELECT SUM(is_shelf) shelf, COUNT(*) n FROM companies WHERE is_new = 1").fetchone()

    for variant in ("intern", "kund"):
        with_address = variant == "intern"
        parts = [f"<!doctype html><html lang='sv'><head><meta charset='utf-8'>"
                 f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
                 f"<title>Nya bolag – Östergötland</title><style>{CSS}</style></head><body><main>",
                 "<h1>Nyregistrerade bolag i Norrköping, Linköping och Finspång</h1>",
                 f"<p class='muted'>Registreringsdatum {esc(period)} · Källa: Bolagsverket, värdefulla datamängder "
                 f"(veckofil {esc(file_date)}) · Sammanställt {date.today().isoformat()}</p>"]
        if draft_note:
            parts.append(f"<div class='draft'>{esc(draft_note)}</div>")
        parts.append("<div class='kpis'>")
        for kommun, rows in per_kommun.items():
            parts.append(f"<div class='kpi'><b>{len(rows)}</b>{esc(kommun)}</div>")
        weeks = len({iso_week(d) for d in dates}) or 1
        parts.append(f"<div class='kpi'><b>≈{len(all_rows) / weeks:.0f}/vecka</b>alla tre kommunerna</div></div>")
        parts.append("<p>Endast juridiska personer (aktiebolag, handelsbolag, kommanditbolag, ekonomiska föreningar). "
                     "Enskilda firmor, lagerbolag från bolagsbildare, avregistrerade bolag, bolag i likvidation/konkurs "
                     "och bolag med reklamspärr hos SCB tas inte med.</p>")
        for kommun, rows in per_kommun.items():
            wk = Counter(iso_week(r["reg_date"]) for r in rows)
            parts.append(f"<h2>{esc(kommun)} – {len(rows)} nya bolag</h2>")
            parts.append("<p class='muted'>Per registreringsvecka: " +
                         ", ".join(f"{w}: {n}" for w, n in sorted(wk.items(), key=lambda x: int(x[0][1:]))) + "</p>")
            head = ["Reg.datum", "Namn", "Form", "Ort"] + (["Adress", "Postnr"] if with_address else []) + \
                   ["Verksamhet (förkortad)", "Reklamspärr"]
            parts.append("<div class='scroll'><table><tr>" + "".join(f"<th>{h}</th>" for h in head) + "</tr>")
            for r in rows:
                pc = r["postcode"] or ""
                cells = [r["reg_date"], r["name"], FORM_NAMES.get(r["form"], r["form"]), r["city"]]
                if with_address:
                    cells += [r["street"], f"{pc[:3]} {pc[3:]}" if len(pc) == 5 else pc]
                cells += [short(r["description"]), _rs_label(r)]
                parts.append("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in cells) + "</tr>")
            parts.append("</table></div>")
        parts.append(
            "<footer>Data: Bolagsverket och SCB, värdefulla datamängder (EU 2023/138), egen bearbetning. "
            f"Lagerbolag exkluderade nationellt i perioden: {excluded['shelf']} av {excluded['n']} nyregistreringar. "
            "Kommun bestäms av postort och kan avvika från kommungränsen. "
            + ("Kundversionen visar inte gatuadresser; dessa ingår i prenumerationens CSV-fil." if not with_address else
               "INTERN VERSION – innehåller adresser. Sprid inte vidare.") + "</footer></main></body></html>")
        (out / f"provrapport-{variant}.html").write_text("\n".join(parts), encoding="utf-8")
    print({k: len(v) for k, v in per_kommun.items()}, "period", period)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--draft-note")
    ap.add_argument("--file-date", default="okänt datum")
    a = ap.parse_args()
    build(Path(a.out), a.draft_note, a.file_date)
