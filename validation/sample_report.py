"""Privacy-safe, customer-facing sample report for accounting firms (Norrköping + Linköping).

usage: NYABOLAG_DATA_DIR=... python validation/sample_report.py <out_dir> --file-date YYYY-MM-DD [--draft-note TEXT]

Privacy rules (docs/05): no org numbers, no street addresses, no postcodes, no c/o lines.
Company names are masked except generic business words, so no individual company (or the
person behind a one-person company) can be identified or targeted from the sample. Aggregates
(counts per week, form, industry) are shown in full.

Writes <out_dir>/provrapport-redovisningsbyraer.html and, if Playwright is available, .pdf.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyabolag.config import Config  # noqa: E402
from nyabolag.db import connect  # noqa: E402
from nyabolag.delivery import normalise_filters, preview  # noqa: E402

BRAND = "Veckans Nya Bolag"
PRICE = "249 kr/mån"
CITIES = {
    "Norrköping": ["Norrköping", "Kolmården", "Krokek", "Åby", "Skärblacka", "Svärtinge", "Vikbolandet",
                   "Kimstad", "Norsholm", "Östra Husby", "Arkösund", "Simonstorp", "Strömsfors"],
    "Linköping": ["Linköping", "Linghem", "Ljungsbro", "Malmslätt", "Sturefors", "Vikingstad", "Vreta Kloster",
                  "Brokind", "Nykil", "Ulrika"],
}
FORMS = ["AB", "HB", "KB", "EK"]
FORM_NAMES = {"AB": "Aktiebolag", "HB": "Handelsbolag", "KB": "Kommanditbolag", "EK": "Ekonomisk förening"}
EXAMPLES_PER_CITY = 10
COLORS = {"Norrköping": "#2a78d6", "Linköping": "#eb6834"}  # validated: dataviz validate_palette.js, light

GENERIC = {
    "ab", "aktiebolag", "aktiebolaget", "hb", "handelsbolag", "kb", "kommanditbolag", "i", "och", "&", "sverige",
    "sweden", "nordic", "norden", "group", "holding", "invest", "konsult", "konsulting", "consulting", "bygg",
    "fastighet", "fastigheter", "förvaltning", "service", "services", "städ", "el", "teknik", "it", "ekonomi",
    "redovisning", "måleri", "transport", "design", "partner", "partners", "solutions", "management", "advisory",
    "öst", "östergötland", "linköping", "norrköping", "medical", "fotboll", "intelligence", "rådgivning",
    "elteknik", "invest", "media", "data", "tech", "trading", "handel", "the", "and", "of",
}

INDUSTRIES = [
    ("Holding & förvaltning", r"äga och förvalta (aktier|andelar|värdepapper)|holding"),
    ("Fastighet", r"fastighet"),
    ("Bygg & hantverk", r"bygg|snickeri|måleri|målning|elinstall|elarbet|elteknik|vvs|rörarbet|plåt|anläggning|"
                        r"renover|hantverk|svets|konstruktion"),
    ("IT & digitalt", r"programvar|mjukvar|\bit\b|it-|digital|webb|system|plattform|data"),
    ("Vård & hälsa", r"vård|hälsa|läkar|tandv|terapi|behandling|friskvård|sjuk"),
    ("Handel", r"handel|försäljning av|e-handel|butik|import|export"),
    ("Transport & fordon", r"transport|åkeri|fordon|\bbil|logistik|taxi|camper"),
    ("Restaurang & livsmedel", r"restaurang|café|kafé|livsmedel|catering"),
    ("Konsult & rådgivning", r"konsult|rådgivning|advisory|management|utbildning"),
]


def industry(r) -> str:
    text = f"{r['name']} {r['description'] or ''}".lower()
    for label, pattern in INDUSTRIES:
        if re.search(pattern, text):
            return label
    return "Övrigt"


def mask_name(name: str) -> str:
    out = []
    for tok in name.split():
        core = tok.strip(".,()")
        if core.lower() in GENERIC or len(core) <= 1:
            out.append(tok)
        else:
            out.append(core[0] + "•" * min(len(core) - 1, 6))
    return " ".join(out)


def short(text: str, n: int = 95) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + " …"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def week(d: str) -> int:
    return date.fromisoformat(d).isocalendar()[1]


def bar_chart(weeks: list[int], per_city: dict[str, Counter]) -> str:
    """Grouped bars per ISO week, one hue per city. Native SVG <title> tooltips; table follows."""
    w, h, left, bottom, top = 640, 240, 36, 28, 18
    ymax = max([c[wk] for c in per_city.values() for wk in weeks] + [1])
    ymax = int(-(-ymax // 5) * 5)  # round up to 5
    plot_w, plot_h = w - left - 8, h - bottom - top
    group = plot_w / len(weeks)
    bw = min(26, (group - 18) / len(per_city))
    parts = [f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='Nya bolag per vecka' class='chart'>"]
    for i in range(0, ymax + 1, 5):
        y = top + plot_h - plot_h * i / ymax
        parts.append(f"<line x1='{left}' x2='{w - 8}' y1='{y:.1f}' y2='{y:.1f}' class='grid'/>"
                     f"<text x='{left - 6}' y='{y + 4:.1f}' class='tick' text-anchor='end'>{i}</text>")
    for gi, wk in enumerate(weeks):
        gx = left + gi * group + (group - bw * len(per_city) - 2 * (len(per_city) - 1)) / 2
        for ci, (city, counts) in enumerate(per_city.items()):
            v = counts[wk]
            bh = plot_h * v / ymax
            x, y = gx + ci * (bw + 2), top + plot_h - bh
            r = min(4, bh / 2)
            path = (f"M{x:.1f},{top + plot_h:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                    f"H{x + bw - r:.1f} Q{x + bw:.1f},{y:.1f} {x + bw:.1f},{y + r:.1f} V{top + plot_h:.1f} Z")
            parts.append(f"<path d='{path}' fill='{COLORS[city]}'><title>{city}, vecka {wk}: {v} nya bolag</title></path>"
                         f"<text x='{x + bw / 2:.1f}' y='{y - 4:.1f}' class='val' text-anchor='middle'>{v}</text>")
        parts.append(f"<text x='{left + gi * group + group / 2:.1f}' y='{h - 8}' class='tick' "
                     f"text-anchor='middle'>v. {wk}</text>")
    parts.append(f"<line x1='{left}' x2='{w - 8}' y1='{top + plot_h}' y2='{top + plot_h}' class='axis'/></svg>")
    legend = "".join(f"<span class='key'><i style='background:{COLORS[c]}'></i>{c}</span>" for c in per_city)
    return f"<div class='legend'>{legend}</div>" + "".join(parts)


CSS = """
:root{--ink:#14181d;--ink-2:#4a5360;--ink-3:#77808c;--line:#e4e7eb;--bg:#ffffff;--soft:#f5f7fa;--brand:#123a5a;
--accent:#1f6fb2;--warn:#7a4b00;--warnbg:#fff4dc;color-scheme:light}
*{box-sizing:border-box}html{background:var(--bg)}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.55 "Inter","Segoe UI",system-ui,-apple-system,sans-serif}
.page{max-width:860px;margin:0 auto;padding:40px 24px 56px}
header.top{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;border-bottom:3px solid var(--brand);padding-bottom:18px}
.logo{font-weight:800;font-size:15px;letter-spacing:.02em;color:var(--brand)}.logo span{color:var(--accent)}
.meta{text-align:right;color:var(--ink-3);font-size:12px}
h1{font-size:28px;line-height:1.2;margin:22px 0 6px;letter-spacing:-.01em}h2{font-size:17px;margin:34px 0 10px;color:var(--brand)}
.lead{color:var(--ink-2);font-size:15px;max-width:640px;margin:0}
.draft{background:var(--warnbg);color:var(--warn);border-radius:8px;padding:10px 14px;margin:18px 0 0;font-size:12.5px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:24px 0 6px}
.kpi{background:var(--soft);border-radius:10px;padding:14px 16px}.kpi b{display:block;font-size:26px;line-height:1.1;font-variant-numeric:tabular-nums}
.kpi span{color:var(--ink-2);font-size:12.5px}
.chart{width:100%;height:auto;display:block}.grid{stroke:var(--line);stroke-width:1}.axis{stroke:#c9ced5;stroke-width:1}
.tick{fill:var(--ink-3);font-size:11px}.val{fill:var(--ink-2);font-size:11px;font-variant-numeric:tabular-nums}
.legend{display:flex;gap:18px;font-size:12.5px;color:var(--ink-2);margin:4px 0 6px}.key i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:28px}
table{width:100%;border-collapse:collapse;font-size:12.5px}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink-3);font-weight:600}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.nw{white-space:nowrap}.hbar{display:flex;align-items:center;gap:8px}.hbar i{height:8px;border-radius:0 4px 4px 0;background:#2a78d6;display:block}
.masked{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:12px}
.offer{background:var(--brand);color:#fff;border-radius:12px;padding:22px 24px;margin-top:34px;display:grid;grid-template-columns:1.4fr 1fr;gap:20px}
.offer h2{color:#fff;margin:0 0 8px}.offer ul{margin:0;padding-left:18px}.offer li{margin:3px 0}
.price{font-size:30px;font-weight:800}.price small{display:block;font-size:12.5px;font-weight:400;opacity:.85}
.note{color:var(--ink-3);font-size:11.5px;margin-top:26px;border-top:1px solid var(--line);padding-top:12px}
.scroll{overflow-x:auto}
@media (max-width:640px){.kpis{grid-template-columns:1fr 1fr}.cols,.offer{grid-template-columns:1fr}.meta{display:none}}
@media print{.page{padding:0 4px}h2{break-after:avoid}table,.offer{break-inside:avoid}}
@page{size:A4;margin:16mm 14mm}
"""


def build(out: Path, file_date: str, draft_note: str | None, contact: str) -> Path:
    cfg = Config()
    conn = connect(cfg.db_path)
    snaps = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
    rows = {c: preview(conn, normalise_filters({"cities": towns, "forms": FORMS}), snaps) for c, towns in CITIES.items()}
    every = [r for rs in rows.values() for r in rs]
    if not every:
        raise SystemExit("no matching companies – ingest a bulk file first")
    dates = sorted(r["reg_date"] for r in every)
    weeks = sorted({week(d) for d in dates})
    per_city_week = {c: Counter(week(r["reg_date"]) for r in rs) for c, rs in rows.items()}
    n_weeks = len(weeks)
    ind = Counter(industry(r) for r in every)
    forms = Counter(r["form"] for r in every)
    holding = ind.get("Holding & förvaltning", 0)

    p = [f"<!doctype html><html lang='sv'><head><meta charset='utf-8'><meta name='viewport' "
         f"content='width=device-width,initial-scale=1'><title>{BRAND} – provrapport</title><style>{CSS}</style>"
         "</head><body><div class='page'>",
         f"<header class='top'><div class='logo'>VECKANS <span>NYA BOLAG</span></div>"
         f"<div class='meta'>Provrapport för redovisningsbyråer<br>Sammanställd {date.today().isoformat()}</div></header>",
         "<h1>Nya bolag i Norrköping och Linköping</h1>",
         f"<p class='lead'>{len(every)} nya bolag registrerades hos Bolagsverket under {n_weeks} veckor "
         f"({esc(dates[0])} – {esc(dates[-1])}). Alla behöver bokföring, bokslut och årsredovisning. "
         "Som prenumerant får du listan varje måndag, med namn, organisationsnummer och postadress.</p>"]
    if draft_note:
        p.append(f"<div class='draft'>{esc(draft_note)}</div>")
    p.append("<div class='kpis'>")
    for c, rs in rows.items():
        p.append(f"<div class='kpi'><b>{len(rs) / n_weeks:.0f}</b><span>nya bolag per vecka i {c}</span></div>")
    p.append(f"<div class='kpi'><b>{forms.get('AB', 0) * 100 // len(every)} %</b><span>aktiebolag – krav på "
             f"årsredovisning</span></div><div class='kpi'><b>{len(every)}</b><span>nya bolag totalt, {n_weeks} veckor"
             "</span></div></div>")

    p.append("<h2>Nyregistreringar per vecka</h2>" + bar_chart(weeks, per_city_week))
    p.append("<div class='scroll'><table><tr><th>Vecka</th>" + "".join(f"<th class='num'>{c}</th>" for c in rows) +
             "<th class='num'>Totalt</th></tr>")
    for wk in weeks:
        vals = [per_city_week[c][wk] for c in rows]
        p.append(f"<tr><td>v. {wk}</td>" + "".join(f"<td class='num'>{v}</td>" for v in vals) +
                 f"<td class='num'>{sum(vals)}</td></tr>")
    p.append("</table></div>")

    top = ind.most_common()
    mx = top[0][1]
    p.append("<div class='cols'><div><h2>Bransch (enligt verksamhetsbeskrivning)</h2><table>")
    for label, v in top:
        p.append(f"<tr><td>{esc(label)}</td><td class='num' style='width:52%'><div class='hbar'>"
                 f"<i style='width:{v / mx * 100:.0f}%'></i>{v}</div></td></tr>")
    p.append("</table></div><div><h2>Vad betyder det för en byrå?</h2>"
             f"<p>Med {len(every) / n_weeks:.0f} nya bolag i veckan i de två städerna är det ett jämnt flöde av "
             "företag som just ska välja redovisningsbyrå, ofta innan de har hunnit bestämma sig.</p>"
             f"<p>{holding} av {len(every)} är holdingbolag. De har låg löpande bokföring, men behöver bokslut, "
             "årsredovisning och deklaration varje år.</p>"
             "<p>Lagerbolag från bolagsbildare, enskilda firmor, avregistrerade bolag och bolag med "
             "reklamspärr hos SCB är redan bortrensade.</p></div></div>")

    p.append("<h2>Exempel på rader</h2><p class='lead' style='font-size:13px'>Namnen är maskerade i provrapporten. "
             "Prenumeranter får fullständigt namn, organisationsnummer, registreringsdatum, postadress och "
             "verksamhetsbeskrivning.</p>")
    for c, rs in rows.items():
        p.append(f"<h2 style='font-size:14px;margin-top:20px'>{c} – {EXAMPLES_PER_CITY} av {len(rs)}</h2>"
                 "<div class='scroll'><table><tr><th>Reg.datum</th><th>Bolag</th><th>Form</th><th>Ort</th>"
                 "<th>Bransch</th><th>Verksamhet (förkortad)</th></tr>")
        for r in rs[:EXAMPLES_PER_CITY]:
            p.append(f"<tr><td class='nw'>{esc(r['reg_date'])}</td><td class='masked'>{esc(mask_name(r['name']))}</td>"
                     f"<td>{esc(r['form'])}</td><td>{esc(r['city'])}</td><td>{esc(industry(r))}</td>"
                     f"<td>{esc(short(r['description']))}</td></tr>")
        p.append("</table></div>")

    p.append(f"<section class='offer'><div><h2>Så fungerar {BRAND}</h2><ul>"
             "<li>Varje måndag: alla nya bolag i ditt område som Excel-fil, direkt i mejlen</li>"
             "<li>Du väljer område med postnummer eller orter, och vilka bolagsformer du vill ha</li>"
             "<li>Lagerbolag, enskilda firmor och bolag med reklamspärr är bortrensade</li>"
             "<li>Ingen bindningstid. Säg upp när du vill</li></ul></div>"
             f"<div><div class='price'>{PRICE}<small>Ingen bindningstid · första listan nästa måndag</small></div>"
             f"<p style='margin:14px 0 0'>{esc(contact)}</p></div></section>")
    p.append("<p class='note'>Källa: Bolagsverket och SCB, värdefulla datamängder (EU 2023/138), egen bearbetning. "
             f"Veckofil {esc(file_date)}. Kommuntillhörighet bestäms av postort och kan avvika något från "
             "kommungränsen. Branschindelningen är en automatisk tolkning av bolagets verksamhetsbeskrivning. "
             "Provrapporten innehåller inga organisationsnummer, adresser eller personuppgifter.</p>"
             "</div></body></html>")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "provrapport-redovisningsbyraer.html"
    path.write_text("\n".join(p), encoding="utf-8")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page()
            page.goto(path.resolve().as_uri())
            page.pdf(path=str(path.with_suffix(".pdf")), format="A4", print_background=True,
                     margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"})
            b.close()
    except Exception as exc:  # PDF is optional
        print(f"PDF skipped: {exc}")
    print({c: len(r) for c, r in rows.items()}, "weeks", weeks)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--file-date", required=True)
    ap.add_argument("--draft-note")
    ap.add_argument("--contact", default="Svara på mejlet eller ring [telefon] så skickar jag en betalningslänk.")
    a = ap.parse_args()
    build(Path(a.out), a.file_date, a.draft_note, a.contact)
