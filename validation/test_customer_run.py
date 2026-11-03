"""End-to-end TEST of the customer experience with FICTIONAL demonstration companies.

usage:
  NYABOLAG_TEST_MODE=1 TEST_RECIPIENTS=you@example.com NYABOLAG_DATA_DIR=/tmp/nb-test \\
    python validation/test_customer_run.py you@example.com --label "Norrköping och Linköping"

What it does (no payment, no Stripe, no web server):
  1. builds a bulk file in Bolagsverket's real format with fictional companies ("DEMO …",
     org numbers that FAIL the Luhn check so they can never be real, fictional street names);
  2. ingests it, runs the reklamspärr verification against a local DEMO stub (marked
     source "DEMO-fiktiv", never presented as a real check);
  3. creates the test customer (manual billing, status active, no charge), sends/previews the
     welcome e-mail and runs the normal weekly delivery;
  4. checks every e-mail and attachment it produced.
Without SMTP settings nothing leaves the machine: e-mails are written to $NYABOLAG_DATA_DIR/outbox.
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from datetime import date, timedelta
from email import message_from_bytes, policy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyabolag.cli import main as cli  # noqa: E402
from nyabolag.config import Config  # noqa: E402
from nyabolag.db import connect, tx  # noqa: E402
from nyabolag.ingest import ingest  # noqa: E402
from nyabolag.reklamsparr import candidates, verify  # noqa: E402

HEADER = ["organisationsidentitet", "namnskyddslopnummer", "registreringsland", "organisationsnamn",
          "organisationsform", "avregistreringsdatum", "avregistreringsorsak",
          "pagandeAvvecklingsEllerOmstruktureringsforfarande", "registreringsdatum",
          "verksamhetsbeskrivning", "postadress"]


def luhn_ok(num: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(num)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def fake_orgnr(i: int) -> str:
    """10 digits, org-number shaped, guaranteed INVALID check digit -> cannot be a real company."""
    base = f"559999{i:03d}"
    for last in range(10):
        if not luhn_ok(base + str(last)):
            return base + str(last)
    raise AssertionError


# (name, form, town, postcode, days_ago, description)
DEMO = [
    ("DEMO Kvarnholmen Bygg AB", "AB", "NORRKÖPING", "60228", 2, "Bygg- och renoveringsverksamhet, främst badrum och kök."),
    ("DEMO Strömsholmen Konsult AB", "AB", "NORRKÖPING", "60224", 3, "Konsultverksamhet inom inköp och logistik."),
    ("DEMO Åby Fastighetsservice AB", "AB", "ÅBY", "61631", 4, "Fastighetsskötsel, snöröjning och trädgårdsarbete."),
    ("DEMO Kolmården Café & Bageri AB", "AB", "KOLMÅRDEN", "61834", 5, "Café- och bageriverksamhet samt catering."),
    ("DEMO Holmentorget Holding AB", "AB", "NORRKÖPING", "60232", 6, "Äga och förvalta aktier och andelar."),
    ("DEMO Östgöta Elteknik HB", "HB", "NORRKÖPING", "60361", 6, "Elinstallationer i bostäder och lokaler."),
    ("DEMO Valla Mjukvara AB", "AB", "LINKÖPING", "58330", 1, "Utveckling och försäljning av programvara för vårdsektorn."),
    ("DEMO Trädgårdstorget Redovisningspartner AB", "AB", "LINKÖPING", "58224", 2, "Ekonomisk rådgivning och administration."),
    ("DEMO Ljungsbro Snickeri AB", "AB", "LJUNGSBRO", "59032", 3, "Snickeri, inredning och mindre byggprojekt."),
    ("DEMO Malmslätt Hälsa AB", "AB", "MALMSLÄTT", "59030", 4, "Friskvård, massage och personlig träning."),
    ("DEMO Ryd Transport AB", "AB", "LINKÖPING", "58431", 5, "Godstransporter och budtjänster i Östergötland."),
    ("=DEMO Formeltest AB", "AB", "LINKÖPING", "58222", 6, "+Testar att Excel inte kör formler från registertext."),
]
EXCLUDED = [  # must NOT reach the customer
    ("DEMO Spärrad Reklam AB", "AB", "LINKÖPING", "58223", 2, "DEMO: har reklamspärr (stub) – ska uteslutas.", "rs"),
    ("DEMO Stockholm Utanför AB", "AB", "STOCKHOLM", "11122", 2, "DEMO: utanför kundens område.", "area"),
] + [(f"Demohyllan {900100 + i} AB", "AB", "DEMOSTAD", "99999", 3, "DEMO: lagerbolag hos bolagsbildare.", "shelf")
     for i in range(3)]


def build_bulk(path: Path, today: date) -> dict[str, str]:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    w.writerow(HEADER)
    names = {}
    for i, rec in enumerate(DEMO + EXCLUDED):
        name, form, town, pc, ago, desc = rec[:6]
        nr = fake_orgnr(i)
        names[nr] = name
        reg = (today - timedelta(days=ago)).isoformat()
        w.writerow([f"{nr}$ORGNR-IDORG", "", "SE-LAND", f"{name}$FORETAGSNAMN-ORGNAM${reg}", f"{form}-ORGFO",
                    "", "", "", reg, desc, f"Demogatan {i + 1}$$TOWN$PC$SE-LAND".replace("TOWN", town).replace("PC", pc)])
    # a fictional sole trader (personnummer-shaped, invalid) – the parser must drop it
    w.writerow(["199901019999$PERSONNUMMER-IDORG", "", "SE-LAND", "DEMO Enskild Firma$FORETAGSNAMN-ORGNAM",
                "EF-ORGFO", "", "", "", today.isoformat(), "DEMO", "Demogatan 99$$LINKÖPING$58222$SE-LAND"])
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("bolagsverket_bulkfil.txt", buf.getvalue())
    return names


class DemoHvd:
    """Local stand-in for Bolagsverket's API. Only for fictional companies; result labelled DEMO."""

    def __init__(self, opted_out: set[str]):
        self.opted_out = opted_out

    def organisation(self, nr):
        return 200, {"organisationer": [{"organisationsidentitet": {"identitetsbeteckning": nr},
                                         "reklamsparr": {"kod": "JA"} if nr in self.opted_out else None}]}


def check_outbox(cfg: Config, email: str) -> list[str]:
    from openpyxl import load_workbook
    problems, report = [], []
    mails = sorted(cfg.outbox_dir.glob("*.eml"))
    for p in mails:
        msg = message_from_bytes(p.read_bytes(), policy=policy.default)
        subj = msg["Subject"]
        report.append(f"• {p.name}: To={msg['To']} Subject={subj!r}")
        if msg["To"] != email:
            problems.append(f"{p.name}: wrong recipient")
        if not subj.startswith("[TEST]"):
            problems.append(f"{p.name}: subject lacks [TEST]")
        text = msg.get_body(("plain",)).get_content()
        html = msg.get_body(("html",)).get_content()
        (p.with_suffix(".html")).write_text(html, encoding="utf-8")
        if "TESTLEVERANS" not in text or "TESTLEVERANS" not in html:
            problems.append(f"{p.name}: test banner missing")
        links = re.findall(r'href="([^"]+)"', html) + re.findall(r"https?://\S+", text)
        report.append(f"  links: {links or 'none (manual mode: reply to change/cancel)'}")
        for link in links:
            if "localhost" in link:
                problems.append(f"{p.name}: link to localhost {link}")
        for part in msg.iter_attachments():
            data = part.get_content()
            fn = part.get_filename()
            report.append(f"  attachment: {fn} ({len(data)} bytes, {part.get_content_type()})")
            if fn.endswith(".xlsx"):
                ws = load_workbook(io.BytesIO(data)).active
                if any(c.data_type != "s" for row in ws.iter_rows() for c in row if c.value is not None):
                    problems.append("xlsx: a cell is not stored as plain text (formula risk)")
                rows = list(ws.iter_rows(values_only=True))
                report.append(f"    xlsx rows: {len(rows) - 1}; header: {rows[0]}")
                for r in rows[1:]:
                    if "DEMO" not in str(r[1]):
                        problems.append(f"xlsx: non-demo company {r[1]}")
                    if r[8] != "DEMO – fiktiv kontroll":
                        problems.append(f"xlsx: reklamspärr label {r[8]!r}")
            if fn.endswith(".csv"):
                rows = list(csv.reader(io.StringIO(data.decode("utf-8-sig") if isinstance(data, bytes) else data),
                                       delimiter=";"))
                report.append(f"    csv rows: {len(rows) - 1}")
    print("\n".join(report))
    return problems


def send_single(cfg: Config, conn, a) -> int:
    """Exactly one e-mail: welcome + demo weekly report, Excel attachment only."""
    from nyabolag.db import get_filters, now_iso
    from nyabolag.delivery import matches, new_companies_since, to_xlsx, verified_cutoff
    from nyabolag.emails import combined_test_email
    from nyabolag.mailer import send_mail

    cust = conn.execute("SELECT * FROM customers WHERE email = ?", (a.email.lower(),)).fetchone()
    filters = get_filters(cust)
    latest = conn.execute("SELECT MAX(id) FROM snapshots").fetchone()[0]
    rows = [r for r in new_companies_since(conn, latest - 1, latest, verified_cutoff(cfg)) if matches(r, filters)]
    assert rows and all("DEMO" in r["name"] for r in rows), "only fictional DEMO companies may be sent"
    name = f"DEMO-nya-bolag-v{date.today().isocalendar()[1]}.xlsx"
    xlsx = to_xlsx(rows, "DEMO nya bolag")
    subject, text, html = combined_test_email(cfg, cust, filters, rows, True, [name])
    for needle in ("TESTLEVERANS", "FIKTIVA"):
        assert needle in text and needle in html, f"test labelling missing: {needle}"
    print(f"sending 1 e-mail via '{cfg.mail_transport}' from {cfg.mail_from} to {a.email}: "
          f"{len(rows)} DEMO companies, attachment {name}")
    path = send_mail(cfg, a.email, subject, text, html=html, attachments=[
        (name, xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")])
    if not path:  # really sent -> lock so it cannot be sent twice by accident
        (cfg.data_dir / "single-test-email.sent").write_text(f"{now_iso()} to {a.email} via {cfg.mail_transport}\n")
    if path:
        print(f"preview written (nothing sent): {path}")
        problems = check_outbox(cfg, a.email)
        print("CHECKS:", "all passed" if not problems else problems)
        return 1 if problems else 0
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("email")
    ap.add_argument("--label", default="Norrköping och Linköping")
    ap.add_argument("--single-email", action="store_true",
                    help="send exactly ONE e-mail: welcome + demo report, Excel attached (refuses to run twice)")
    ap.add_argument("--again", action="store_true", help="allow --single-email to send a second time")
    a = ap.parse_args()
    cfg = Config()
    if not cfg.test_mode or a.email.lower() not in cfg.test_recipients:
        raise SystemExit("refusing: set NYABOLAG_TEST_MODE=1 and TEST_RECIPIENTS to include the test address")
    cfg.ensure_dirs()
    marker = cfg.data_dir / "single-test-email.sent"
    if a.single_email and marker.exists() and not a.again:
        raise SystemExit(f"refusing: a single test e-mail was already sent ({marker.read_text().strip()}). "
                         "Use --again only if you really want another one.")
    today = date.today()
    zpath = cfg.raw_dir / f"DEMO-bulkfil-{today.isoformat()}.zip"
    names = build_bulk(zpath, today)
    conn = connect(cfg.db_path)
    print("ingest:", {k: v for k, v in ingest(conn, zpath, cfg, today=today).items() if k in
                      ("new", "shelf_flagged", "yielded", "skipped_person", "bad_rows")})

    towns = ("Norrköping,Kolmården,Krokek,Åby,Skärblacka,Svärtinge,Vikbolandet,Kimstad,Norsholm,Östra Husby,"
             "Arkösund,Simonstorp,Strömsfors,Linköping,Linghem,Ljungsbro,Malmslätt,Sturefors,Vikingstad,"
             "Vreta Kloster,Brokind,Nykil,Ulrika")
    cli(["add-customer", a.email, "--company", "TEST – Nathan (testkund)", "--label", a.label,
         "--cities", towns, "--forms", "AB,HB,KB,EK"])
    opted_out = {nr for nr, n in names.items() if n == "DEMO Spärrad Reklam AB"}
    stats = verify(conn, cfg, candidates(conn, cfg), DemoHvd(opted_out))
    with tx(conn):
        conn.execute("UPDATE reklamsparr SET source = 'DEMO-fiktiv (lokal stub, ingen riktig kontroll)'")
    print("reklamspärr (DEMO stub):", {k: stats[k] for k in ("candidates", "verified", "blocked", "failed")})
    if a.single_email:
        return send_single(cfg, conn, a)
    cli(["welcome", a.email])
    cli(["deliver"])
    problems = check_outbox(cfg, a.email)
    print("\nCHECKS:", "all passed" if not problems else problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
