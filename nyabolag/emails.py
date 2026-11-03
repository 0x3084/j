"""Customer-facing e-mails (Swedish): welcome and weekly delivery, as plain text + HTML.

HTML uses inline styles and a single 600 px table layout so it renders in Outlook, Gmail and
iPhone Mail. Links: in manual mode (no deployed dashboard) e-mails contain no web links and ask
the customer to reply instead, so no link in an e-mail can point to a page that does not exist.
"""
from __future__ import annotations

import html as _html
from collections import Counter
from datetime import date

from .config import Config

FORM_NAMES = {"AB": "Aktiebolag", "HB": "Handelsbolag", "KB": "Kommanditbolag", "EK": "Ekonomisk förening"}
INK, MUTED, LINE, BRAND, ACCENT, SOFT = "#14181d", "#5b6470", "#e4e7eb", "#123a5a", "#1f6fb2", "#f4f6f9"


def e(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _area(filters: dict) -> str:
    if filters.get("label"):
        return filters["label"]
    parts = [c.title() for c in filters.get("cities", [])] + [f"postnummer {p}…" for p in filters.get("postcode_prefixes", [])]
    return ", ".join(parts) or "hela Sverige"


def _forms(filters: dict) -> str:
    return ", ".join(FORM_NAMES.get(f, f) for f in (filters.get("forms") or ["AB"]))


def _test_banner_html(cfg: Config, demo: bool) -> str:
    if not cfg.test_mode:
        return ""
    msg = "TESTLEVERANS – ingen betalning, ingen riktig prenumeration."
    if demo:
        msg += " Bolagen i listan är FIKTIVA demonstrationsdata, inte riktiga företag."
    return (f"<tr><td style='background:#fff4dc;color:#7a4b00;padding:10px 24px;font-size:13px;"
            f"font-weight:600'>{e(msg)}</td></tr>")


def _test_banner_text(cfg: Config, demo: bool) -> str:
    if not cfg.test_mode:
        return ""
    msg = "*** TESTLEVERANS – ingen betalning, ingen riktig prenumeration."
    if demo:
        msg += " Bolagen i listan är FIKTIVA demonstrationsdata, inte riktiga företag."
    return msg + " ***\n\n"


def _change_text(cfg: Config) -> str:
    if cfg.dashboard_enabled:
        return f"Ändra område eller säg upp: {cfg.base_url}/login"
    return "Vill du ändra område eller säga upp? Svara bara på det här mejlet."


def _shell(cfg: Config, title: str, preheader: str, inner: str, demo: bool = False) -> str:
    return f"""<!doctype html><html lang="sv"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">
<title>{e(title)}</title></head>
<body style="margin:0;padding:0;background:{SOFT};font-family:Segoe UI,Helvetica,Arial,sans-serif;color:{INK}">
<span style="display:none;max-height:0;overflow:hidden">{e(preheader)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{SOFT}"><tr><td align="center" style="padding:16px 8px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:10px;overflow:hidden">
<tr><td style="background:{BRAND};color:#ffffff;padding:16px 24px;font-weight:800;letter-spacing:.03em;font-size:14px">
VECKANS <span style="color:#9cc8ef">NYA BOLAG</span></td></tr>
{_test_banner_html(cfg, demo)}
{inner}
<tr><td style="padding:16px 24px 22px;border-top:1px solid {LINE};color:{MUTED};font-size:12px;line-height:1.5">
{e(_change_text(cfg))}<br>
Källa: Bolagsverket och SCB, värdefulla datamängder (EU 2023/138), egen bearbetning.<br>
Du får det här mejlet eftersom du prenumererar på {e(cfg.brand)}.
</td></tr></table></td></tr></table></body></html>"""


def welcome_email(cfg: Config, customer, filters: dict, inner_only: bool = False):
    """(subject, text, html) sent when a subscription starts. inner_only: (subject, text, inner rows)."""
    price = f"{cfg.price_sek_month} kr/mån"
    billing = ("TEST: ingen faktura skickas och inget dras." if cfg.test_mode
               else "Faktura eller kvitto kommer separat. Ingen bindningstid.")
    subject = f"Välkommen till {cfg.brand}"
    text = (f"{_test_banner_text(cfg, False)}Hej{(' ' + customer['company_name']) if customer['company_name'] else ''}!\n\n"
            f"Tack för att du prenumererar på {cfg.brand}. Det här gäller för din prenumeration:\n\n"
            f"  Område:        {_area(filters)}\n"
            f"  Bolagsformer:  {_forms(filters)}\n"
            f"  Pris:          {price} ({cfg.vat_text}), ingen bindningstid\n"
            f"  Leverans:      varje måndag, till {customer['email']}\n\n"
            "Varje vecka får du:\n"
            "  - en Excel-fil med alla bolag i ditt område som registrerats sedan förra listan:\n"
            "    namn, organisationsnummer, registreringsdatum, postadress och verksamhet\n"
            "  - en sammanfattning direkt i mejlet\n\n"
            "Lagerbolag, enskilda firmor, avregistrerade bolag och bolag med reklamspärr hos SCB\n"
            "är bortrensade. Varje bolag kontrolleras mot Bolagsverkets register innan leverans.\n\n"
            "Att tänka på när du kontaktar bolagen: skriv vem du är och hur mottagaren slipper\n"
            "fler utskick, och respektera ett nej. Listan innehåller inga e-postadresser.\n\n"
            f"{billing}\n{_change_text(cfg)}\n\n"
            f"Välkommen!\n{cfg.brand}\n")
    rows = "".join(
        f"<tr><td style='padding:6px 0;color:{MUTED};width:130px;vertical-align:top'>{e(k)}</td>"
        f"<td style='padding:6px 0;font-weight:600'>{e(v)}</td></tr>"
        for k, v in [("Område", _area(filters)), ("Bolagsformer", _forms(filters)),
                     ("Pris", f"{price} · {cfg.vat_text} · ingen bindningstid"),
                     ("Leverans", f"Varje måndag till {customer['email']}")])
    inner = f"""<tr><td style="padding:24px 24px 8px">
<h1 style="margin:0 0 8px;font-size:22px;line-height:1.25">Välkommen{(' ' + e(customer['company_name'])) if customer['company_name'] else ''}!</h1>
<p style="margin:0 0 14px;font-size:15px;line-height:1.55;color:{INK}">Tack för att du prenumererar på {e(cfg.brand)}. Första listan kommer på måndag.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;border-top:1px solid {LINE};border-bottom:1px solid {LINE};margin:6px 0 16px">{rows}</table>
<p style="margin:0 0 6px;font-size:14px;font-weight:700">Varje vecka får du</p>
<ul style="margin:0 0 14px;padding-left:20px;font-size:14px;line-height:1.6">
<li>en Excel-fil med alla nya bolag i ditt område: namn, org.nr, registreringsdatum, postadress och verksamhet</li>
<li>en sammanfattning direkt i mejlet</li></ul>
<p style="margin:0 0 14px;font-size:14px;line-height:1.55">Lagerbolag, enskilda firmor, avregistrerade bolag och bolag med reklamspärr hos SCB är bortrensade. Varje bolag kontrolleras mot Bolagsverkets register innan leverans.</p>
<p style="margin:0 0 14px;font-size:13px;line-height:1.55;color:{MUTED};background:{SOFT};padding:10px 12px;border-radius:6px"><b>Att tänka på när du kontaktar bolagen:</b> skriv vem du är och hur mottagaren slipper fler utskick, och respektera ett nej. Listan innehåller inga e-postadresser.</p>
<p style="margin:0 0 18px;font-size:14px">{e(billing)}</p></td></tr>"""
    if inner_only:
        return subject, text, inner
    return subject, text, _shell(cfg, subject, f"Din prenumeration: {_area(filters)}, {price}", inner)


def weekly_email(cfg: Config, customer, filters: dict, rows: list, demo: bool, attachment_names: list[str],
                 inner_only: bool = False):
    """(subject, text, html) for the weekly delivery. inner_only: (subject, text, inner rows)."""
    n = len(rows)
    dates = sorted(r["reg_date"] for r in rows if r["reg_date"])
    week = date.today().isocalendar()[1]
    period = f"{dates[0]} – {dates[-1]}" if dates else "–"
    towns = Counter(r["city"] for r in rows).most_common()
    subject = f"Nya bolag v. {week}: {n} st i {_area(filters)}"
    text = [f"{_test_banner_text(cfg, demo)}Hej!\n",
            f"Här är veckans nyregistrerade bolag i {_area(filters)}: {n} st (registrerade {period}).\n"]
    if towns:
        text.append("Per ort: " + ", ".join(f"{t} {c}" for t, c in towns) + "\n")
    text.append("")
    for r in rows:
        text.append(f"  {r['reg_date']}  {r['name']} ({r['form']}), {r['city']}")
    text.append(f"\nFullständig lista med organisationsnummer och postadress i bilagan: {', '.join(attachment_names)}.")
    if n == 0:
        text.append("Inga nya bolag i ditt område den här veckan. Listan kommer som vanligt nästa måndag.")
    text.append(f"\n{_change_text(cfg)}\n\n{cfg.brand}")
    trs = "".join(
        f"<tr><td style='padding:8px 6px 8px 0;border-bottom:1px solid {LINE};vertical-align:top;font-size:13px'>"
        f"<div style='font-weight:600;color:{INK}'>{e(r['name'])}</div>"
        f"<div style='color:{MUTED};font-size:12px'>{e(r['city'])} · {e(FORM_NAMES.get(r['form'], r['form']))} · "
        f"reg. {e(r['reg_date'])}</div>"
        f"<div style='color:{INK};font-size:12px;margin-top:2px'>{e(_short(r['description']))}</div></td></tr>"
        for r in rows)
    town_html = " · ".join(f"{e(t)} <b>{c}</b>" for t, c in towns)
    inner = f"""<tr><td style="padding:22px 24px 6px">
<p style="margin:0;color:{MUTED};font-size:13px">Vecka {week} · registrerade {e(period)}</p>
<h1 style="margin:4px 0 6px;font-size:24px;line-height:1.2">{n} nya bolag i {e(_area(filters))}</h1>
<p style="margin:0 0 12px;font-size:13px;color:{MUTED}">{town_html}</p>
<p style="margin:0 0 14px;font-size:14px;line-height:1.5;background:{SOFT};padding:10px 12px;border-radius:6px">
📎 <b>Excel-fil bifogad</b> med organisationsnummer, postadress och full verksamhetsbeskrivning:<br>
<span style="color:{MUTED};font-size:12.5px">{e(", ".join(attachment_names))}</span></p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{trs or
    f"<tr><td style='padding:10px 0;font-size:14px'>Inga nya bolag i ditt område den här veckan.</td></tr>"}</table>
<p style="margin:16px 0 18px;font-size:12px;color:{MUTED};line-height:1.5">Bortrensat: lagerbolag, enskilda firmor,
avregistrerade bolag, bolag i likvidation/konkurs och bolag med reklamspärr. Kontakta bolagen med brev, besök eller
telefon. Ange vem du är och hur mottagaren slipper fler utskick.</p></td></tr>"""
    if inner_only:
        return subject, "\n".join(text) + "\n", inner
    return subject, "\n".join(text) + "\n", _shell(cfg, subject, f"{n} nya bolag denna vecka", inner, demo)


def combined_test_email(cfg: Config, customer, filters: dict, rows: list, demo: bool, attachment_names: list[str]):
    """ONE test e-mail: the welcome e-mail followed by a demo weekly report (TEST MODE only)."""
    _, wtext, winner = welcome_email(cfg, customer, filters, inner_only=True)
    _, rtext, rinner = weekly_email(cfg, customer, filters, rows, demo, attachment_names, inner_only=True)
    divider = (f"<tr><td style='padding:6px 24px 0'><div style='border-top:3px solid {BRAND};padding-top:14px;"
               f"font-size:12px;font-weight:700;letter-spacing:.06em;color:{BRAND}'>SÅ HÄR SER EN VECKOLEVERANS UT"
               f"{' – DEMORAPPORT MED FIKTIVA BOLAG' if demo else ''}</div></td></tr>")
    subject = f"Välkommen till {cfg.brand} + exempel på veckoleverans"
    text = (wtext + "\n" + "=" * 60 + "\nSÅ HÄR SER EN VECKOLEVERANS UT" +
            (" – DEMORAPPORT MED FIKTIVA BOLAG" if demo else "") + "\n" + "=" * 60 + "\n\n" +
            rtext.replace(_test_banner_text(cfg, demo), ""))
    return subject, text, _shell(cfg, subject, "Välkommen + exempel på veckoleverans", winner + divider + rinner, demo)


def _short(text: str, n: int = 110) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + " …"
